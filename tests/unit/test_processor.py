from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.messaging.publisher import NullPublisher
from app.repositories.task_repository import TaskRepository
from app.schemas.enums import TaskStatus
from app.schemas.task import TaskCreate
from app.services.task_service import TaskService
from app.worker.processor import TaskProcessor, TaskProcessingError


@pytest_asyncio.fixture
async def seed(session_factory: async_sessionmaker[AsyncSession]):
    async def _seed(status: TaskStatus = TaskStatus.PENDING):
        async with session_factory() as session:
            service = TaskService(TaskRepository(session), NullPublisher())
            task = await service.create_task(TaskCreate(title="work"))
            if status != task.status:
                task.status = status
                await TaskRepository(session).update(task)
            await session.commit()
            return task.id

    return _seed


async def _load_status(session_factory, task_id) -> TaskStatus:
    async with session_factory() as session:
        task = await TaskRepository(session).get(task_id)
        assert task is not None
        return task.status


async def test_processor_completes_pending_task(
    monkeypatch, session_factory, seed
) -> None:
    monkeypatch.setattr(
        "app.worker.processor.async_session_factory", lambda: session_factory
    )
    task_id = await seed(TaskStatus.PENDING)

    await TaskProcessor().process(task_id)

    assert await _load_status(session_factory, task_id) == TaskStatus.COMPLETED


async def test_processor_skips_cancelled_task(
    monkeypatch, session_factory, seed
) -> None:
    monkeypatch.setattr(
        "app.worker.processor.async_session_factory", lambda: session_factory
    )
    task_id = await seed(TaskStatus.CANCELLED)

    await TaskProcessor().process(task_id)

    assert await _load_status(session_factory, task_id) == TaskStatus.CANCELLED


@pytest.mark.parametrize(
    "status",
    [TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.FAILED],
)
async def test_processor_skips_non_pending_redelivery(
    monkeypatch, session_factory, seed, status
) -> None:
    monkeypatch.setattr(
        "app.worker.processor.async_session_factory", lambda: session_factory
    )
    task_id = await seed(status)

    await TaskProcessor().process(task_id)

    assert await _load_status(session_factory, task_id) == status


async def test_processor_skips_missing_task(
    monkeypatch, session_factory
) -> None:
    monkeypatch.setattr(
        "app.worker.processor.async_session_factory", lambda: session_factory
    )

    await TaskProcessor().process(uuid4())


async def test_processor_marks_failed_on_business_error(
    monkeypatch, session_factory, seed
) -> None:
    monkeypatch.setattr(
        "app.worker.processor.async_session_factory", lambda: session_factory
    )

    async def _boom(self, task) -> str:
        raise TaskProcessingError("nope")

    monkeypatch.setattr(TaskProcessor, "_execute", _boom)
    task_id = await seed(TaskStatus.PENDING)

    await TaskProcessor().process(task_id)

    assert await _load_status(session_factory, task_id) == TaskStatus.FAILED


async def test_processor_marks_failed_on_non_processing_business_error(
    monkeypatch, session_factory, seed
) -> None:
    monkeypatch.setattr(
        "app.worker.processor.async_session_factory", lambda: session_factory
    )

    async def _boom(self, task) -> str:
        raise ValueError("plain business error")

    monkeypatch.setattr(TaskProcessor, "_execute", _boom)
    task_id = await seed(TaskStatus.PENDING)

    await TaskProcessor().process(task_id)

    assert await _load_status(session_factory, task_id) == TaskStatus.FAILED


async def test_processor_propagates_infrastructure_error(
    monkeypatch, session_factory, seed
) -> None:
    monkeypatch.setattr(
        "app.worker.processor.async_session_factory", lambda: session_factory
    )

    async def _boom(self, task) -> str:
        raise OperationalError("SELECT 1", {}, Exception("connection lost"))

    monkeypatch.setattr(TaskProcessor, "_execute", _boom)
    task_id = await seed(TaskStatus.PENDING)

    with pytest.raises(OperationalError):
        await TaskProcessor().process(task_id)

    assert await _load_status(session_factory, task_id) != TaskStatus.COMPLETED
