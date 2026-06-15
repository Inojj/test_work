from __future__ import annotations

import asyncio
import json
import logging
import signal
from uuid import UUID

import aio_pika
from aio_pika import DeliveryMode, Message
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractRobustChannel,
    AbstractRobustConnection,
    AbstractRobustQueue,
)

from app.config import get_settings
from app.messaging.publisher import MAX_DELIVERY_ATTEMPTS, declare_task_topology
from app.worker.processor import TaskProcessor

logger = logging.getLogger(__name__)

RETRY_COUNT_HEADER = "x-retry-count"


class Worker:
    """Consumes task messages from RabbitMQ and processes them concurrently.

    Each delivery is handled in its own asyncio task with its own DB session.
    The channel prefetch caps the number of unacknowledged (in-flight) messages
    at WORKER_CONCURRENCY, bounding parallelism. Messages are acknowledged once
    handled (success or recorded business failure). On an unexpected
    infrastructure error the delivery is retried with a bound: the worker reads
    the ``x-retry-count`` header and, while attempts are below
    MAX_DELIVERY_ATTEMPTS, re-publishes a fresh persistent message (preserving
    priority) with an incremented count and ACKs the original; once the cap is
    reached it ``reject(requeue=False)`` so the message dead-letters to the DLX
    -> DLQ. Malformed messages are rejected to the DLQ immediately.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._processor = TaskProcessor()
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractRobustChannel | None = None
        self._queue: AbstractRobustQueue | None = None
        self._consumer_tag: str | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._stop = asyncio.Event()

    async def run(self) -> None:
        await self._connect()
        self._install_signal_handlers()
        logger.info(
            "Worker started: queue=%s concurrency=%d",
            self._settings.TASK_QUEUE_NAME,
            self._settings.WORKER_CONCURRENCY,
        )
        await self._stop.wait()
        await self._shutdown()

    async def _connect(self) -> None:
        self._connection = await aio_pika.connect_robust(self._settings.RABBITMQ_URL)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=self._settings.WORKER_CONCURRENCY)
        self._queue = await declare_task_topology(
            self._channel, self._settings.TASK_QUEUE_NAME
        )
        self._consumer_tag = await self._queue.consume(self._on_message)

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except NotImplementedError:
                signal.signal(sig, lambda *_: self._stop.set())

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        task = asyncio.create_task(self._handle(message))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        try:
            task_id = self._parse_task_id(message.body)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.error("Discarding malformed message: %s", exc)
            await message.reject(requeue=False)
            return

        try:
            await self._processor.process(task_id)
        except Exception:
            attempts = self._retry_count(message) + 1
            if attempts >= MAX_DELIVERY_ATTEMPTS:
                logger.exception(
                    "Task %s exceeded redelivery limit, dead-lettering", task_id
                )
                await message.reject(requeue=False)
            else:
                logger.exception(
                    "Infrastructure error for task %s, retry %d", task_id, attempts
                )
                await self._republish(message, attempts)
                await message.ack()
            return

        await message.ack()

    async def _republish(
        self, message: AbstractIncomingMessage, attempts: int
    ) -> None:
        assert self._channel is not None
        headers = dict(message.headers or {})
        headers[RETRY_COUNT_HEADER] = attempts
        await self._channel.default_exchange.publish(
            Message(
                body=message.body,
                delivery_mode=DeliveryMode.PERSISTENT,
                priority=message.priority,
                content_type=message.content_type,
                headers=headers,
            ),
            routing_key=self._settings.TASK_QUEUE_NAME,
        )

    @staticmethod
    def _retry_count(message: AbstractIncomingMessage) -> int:
        count = (message.headers or {}).get(RETRY_COUNT_HEADER)
        return count if isinstance(count, int) else 0

    @staticmethod
    def _parse_task_id(body: bytes) -> UUID:
        payload = json.loads(body.decode("utf-8"))
        return UUID(str(payload["task_id"]))

    async def _shutdown(self) -> None:
        logger.info("Shutting down worker")
        if self._queue is not None and self._consumer_tag is not None:
            await self._queue.cancel(self._consumer_tag)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._connection is not None:
            await self._connection.close()
        logger.info("Worker stopped")


async def main() -> None:
    await Worker().run()
