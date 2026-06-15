import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from app.messaging.publisher import MAX_DELIVERY_ATTEMPTS
from app.worker.worker import RETRY_COUNT_HEADER, Worker


class FakeIncomingMessage:
    def __init__(
        self,
        body: bytes,
        *,
        redelivered: bool = False,
        headers: dict | None = None,
        priority: int | None = 5,
        content_type: str | None = "application/json",
    ) -> None:
        self.body = body
        self.redelivered = redelivered
        self.headers = headers
        self.priority = priority
        self.content_type = content_type
        self.ack = AsyncMock()
        self.nack = AsyncMock()
        self.reject = AsyncMock()


def _valid_body(task_id=None) -> bytes:
    return json.dumps({"task_id": str(task_id or uuid4())}).encode("utf-8")


@pytest.fixture
def worker() -> Worker:
    w = Worker()
    w._processor = AsyncMock()
    channel = AsyncMock()
    channel.default_exchange = AsyncMock()
    w._channel = channel
    return w


async def test_handle_acks_on_success(worker: Worker) -> None:
    message = FakeIncomingMessage(_valid_body())

    await worker._handle(message)

    message.ack.assert_awaited_once()
    message.nack.assert_not_awaited()
    message.reject.assert_not_awaited()


async def test_handle_republishes_with_incremented_header_below_cap(
    worker: Worker,
) -> None:
    worker._processor.process.side_effect = OperationalError("x", {}, Exception("db"))
    message = FakeIncomingMessage(_valid_body(), priority=7)

    await worker._handle(message)

    worker._channel.default_exchange.publish.assert_awaited_once()
    args, kwargs = worker._channel.default_exchange.publish.call_args
    republished = args[0]
    assert republished.body == message.body
    assert republished.priority == 7
    assert republished.headers[RETRY_COUNT_HEADER] == 1
    assert kwargs["routing_key"] == worker._settings.TASK_QUEUE_NAME
    message.ack.assert_awaited_once()
    message.reject.assert_not_awaited()
    message.nack.assert_not_awaited()


async def test_handle_increments_existing_retry_header(worker: Worker) -> None:
    worker._processor.process.side_effect = OperationalError("x", {}, Exception("db"))
    message = FakeIncomingMessage(
        _valid_body(), headers={RETRY_COUNT_HEADER: 1}
    )

    await worker._handle(message)

    republished = worker._channel.default_exchange.publish.call_args.args[0]
    assert republished.headers[RETRY_COUNT_HEADER] == 2
    message.ack.assert_awaited_once()


async def test_handle_rejects_when_retry_count_reaches_cap(worker: Worker) -> None:
    worker._processor.process.side_effect = OperationalError("x", {}, Exception("db"))
    headers = {RETRY_COUNT_HEADER: MAX_DELIVERY_ATTEMPTS - 1}
    message = FakeIncomingMessage(_valid_body(), headers=headers)

    await worker._handle(message)

    message.reject.assert_awaited_once_with(requeue=False)
    worker._channel.default_exchange.publish.assert_not_awaited()
    message.nack.assert_not_awaited()
    message.ack.assert_not_awaited()


async def test_handle_rejects_malformed_body(worker: Worker) -> None:
    message = FakeIncomingMessage(b"not json")

    await worker._handle(message)

    message.reject.assert_awaited_once_with(requeue=False)
    worker._processor.process.assert_not_awaited()


async def test_handle_rejects_missing_task_id(worker: Worker) -> None:
    message = FakeIncomingMessage(json.dumps({"nope": 1}).encode("utf-8"))

    await worker._handle(message)

    message.reject.assert_awaited_once_with(requeue=False)
    worker._processor.process.assert_not_awaited()


def test_parse_task_id_round_trip() -> None:
    task_id = uuid4()
    assert Worker._parse_task_id(_valid_body(task_id)) == task_id


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (None, 0),
        ({}, 0),
        ({RETRY_COUNT_HEADER: 2}, 2),
        ({RETRY_COUNT_HEADER: "bad"}, 0),
    ],
)
def test_retry_count(headers, expected) -> None:
    message = FakeIncomingMessage(b"", headers=headers)
    assert Worker._retry_count(message) == expected
