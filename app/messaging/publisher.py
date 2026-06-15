import json
from typing import Protocol
from uuid import UUID

import aio_pika
from aio_pika.abc import (
    AbstractRobustChannel,
    AbstractRobustConnection,
    AbstractRobustQueue,
)

from app.config import get_settings
from app.schemas.enums import TaskPriority

_PRIORITY_MAP: dict[TaskPriority, int] = {
    TaskPriority.LOW: 1,
    TaskPriority.MEDIUM: 5,
    TaskPriority.HIGH: 10,
}

MAX_PRIORITY = 10

MAX_DELIVERY_ATTEMPTS = 3


def priority_to_amqp(priority: TaskPriority) -> int:
    return _PRIORITY_MAP[priority]


def dlx_name(queue_name: str) -> str:
    return f"{queue_name}.dlx"


def dlq_name(queue_name: str) -> str:
    return f"{queue_name}.dlq"


def task_queue_arguments(queue_name: str) -> dict[str, object]:
    return {
        "x-max-priority": MAX_PRIORITY,
        "x-dead-letter-exchange": dlx_name(queue_name),
    }


async def declare_task_topology(
    channel: AbstractRobustChannel, queue_name: str
) -> AbstractRobustQueue:
    dlx = await channel.declare_exchange(
        dlx_name(queue_name), aio_pika.ExchangeType.FANOUT, durable=True
    )
    dlq = await channel.declare_queue(dlq_name(queue_name), durable=True)
    await dlq.bind(dlx)
    return await channel.declare_queue(
        queue_name, durable=True, arguments=task_queue_arguments(queue_name)
    )


class AbstractTaskPublisher(Protocol):
    async def publish_task(self, task_id: UUID, priority: TaskPriority) -> None: ...


class NullPublisher:
    async def publish_task(self, task_id: UUID, priority: TaskPriority) -> None:
        return None


class RabbitMQPublisher:
    def __init__(self, url: str | None = None, queue_name: str | None = None) -> None:
        settings = get_settings()
        self._url = url or settings.RABBITMQ_URL
        self._queue_name = queue_name or settings.TASK_QUEUE_NAME
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractRobustChannel | None = None

    async def connect(self) -> None:
        if self._connection is not None:
            return
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        await declare_task_topology(self._channel, self._queue_name)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            self._channel = None

    async def publish_task(self, task_id: UUID, priority: TaskPriority) -> None:
        if self._channel is None:
            await self.connect()
        assert self._channel is not None
        message = aio_pika.Message(
            body=json.dumps({"task_id": str(task_id)}).encode("utf-8"),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            priority=priority_to_amqp(priority),
            content_type="application/json",
        )
        await self._channel.default_exchange.publish(
            message, routing_key=self._queue_name
        )
