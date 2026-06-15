import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import aio_pika
import pytest

from app.messaging.publisher import (
    MAX_PRIORITY,
    RabbitMQPublisher,
    declare_task_topology,
    dlq_name,
    dlx_name,
    priority_to_amqp,
)
from app.schemas.enums import TaskPriority

QUEUE = "tasks"


@pytest.mark.parametrize(
    ("priority", "expected"),
    [
        (TaskPriority.LOW, 1),
        (TaskPriority.MEDIUM, 5),
        (TaskPriority.HIGH, 10),
    ],
)
def test_priority_to_amqp_mapping(priority: TaskPriority, expected: int) -> None:
    assert priority_to_amqp(priority) == expected


async def test_declare_task_topology_declares_dlx_dlq_and_main_queue() -> None:
    channel = MagicMock()
    exchange = MagicMock()
    dlq = MagicMock()
    dlq.bind = AsyncMock()
    main_queue = MagicMock()
    channel.declare_exchange = AsyncMock(return_value=exchange)
    channel.declare_queue = AsyncMock(side_effect=[dlq, main_queue])

    result = await declare_task_topology(channel, QUEUE)

    channel.declare_exchange.assert_awaited_once_with(
        dlx_name(QUEUE), aio_pika.ExchangeType.FANOUT, durable=True
    )
    dlq.bind.assert_awaited_once_with(exchange)

    declared_queues = channel.declare_queue.await_args_list
    assert declared_queues[0].args[0] == dlq_name(QUEUE)
    main_call = declared_queues[1]
    assert main_call.args[0] == QUEUE
    args = main_call.kwargs["arguments"]
    assert args["x-max-priority"] == MAX_PRIORITY
    assert args["x-dead-letter-exchange"] == dlx_name(QUEUE)
    assert result is main_queue


async def test_publish_task_builds_persistent_priority_message(monkeypatch) -> None:
    publisher = RabbitMQPublisher(url="amqp://test", queue_name=QUEUE)

    default_exchange = MagicMock()
    default_exchange.publish = AsyncMock()
    channel = MagicMock()
    channel.default_exchange = default_exchange
    publisher._channel = channel

    task_id = uuid4()
    await publisher.publish_task(task_id, TaskPriority.HIGH)

    default_exchange.publish.assert_awaited_once()
    message = default_exchange.publish.await_args.args[0]
    assert default_exchange.publish.await_args.kwargs["routing_key"] == QUEUE
    assert message.priority == priority_to_amqp(TaskPriority.HIGH)
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    assert json.loads(message.body.decode("utf-8")) == {"task_id": str(task_id)}
