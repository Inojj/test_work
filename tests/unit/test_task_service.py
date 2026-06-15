from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    InvalidStatusTransitionError,
    MessagePublishError,
    TaskCancellationError,
    TaskNotFoundError,
)
from app.messaging.publisher import NullPublisher
from app.repositories.task_repository import TaskRepository
from app.schemas.enums import TaskPriority, TaskStatus
from app.schemas.task import TaskCreate
from app.services.task_service import TaskService


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def publish_task(self, task_id, priority) -> None:
        self.calls.append((task_id, priority))


class FailingPublisher:
    async def publish_task(self, task_id, priority) -> None:
        raise RuntimeError("broker down")


class SpyRepository:
    """Wraps a real TaskRepository and records commit calls and get kwargs."""

    def __init__(self, inner: TaskRepository) -> None:
        self._inner = inner
        self.commit_count = 0
        self.get_for_update: list[bool] = []

    async def create(self, task):
        return await self._inner.create(task)

    async def get(self, task_id, *, for_update: bool = False):
        self.get_for_update.append(for_update)
        return await self._inner.get(task_id, for_update=for_update)

    async def list(self, **kwargs):
        return await self._inner.list(**kwargs)

    async def update(self, task):
        return await self._inner.update(task)

    async def commit(self) -> None:
        self.commit_count += 1
        await self._inner.commit()


class StatusAssertingPublisher:
    """Records the durable (separately-committed) task status when publish runs."""

    def __init__(self, task_getter) -> None:
        self._task_getter = task_getter
        self.durable_status_at_publish: TaskStatus | None = None

    async def publish_task(self, task_id, priority) -> None:
        task = await self._task_getter(task_id)
        self.durable_status_at_publish = None if task is None else task.status


@pytest_asyncio.fixture
async def repository(session: AsyncSession) -> TaskRepository:
    return TaskRepository(session)


@pytest_asyncio.fixture
async def service(repository: TaskRepository) -> TaskService:
    return TaskService(repository, NullPublisher())


async def _create(service: TaskService, **kw) -> "object":
    data = TaskCreate(title=kw.pop("title", "demo"), **kw)
    return await service.create_task(data)


async def test_create_task_sets_pending_and_publishes(repository: TaskRepository) -> None:
    publisher = RecordingPublisher()
    service = TaskService(repository, publisher)

    task = await service.create_task(TaskCreate(title="demo", priority=TaskPriority.HIGH))

    assert task.status == TaskStatus.PENDING
    assert task.title == "demo"
    assert task.priority == TaskPriority.HIGH
    assert publisher.calls == [(task.id, TaskPriority.HIGH)]


async def test_create_task_commits_durable_row_before_publish(session_factory) -> None:
    async with session_factory() as session:
        repository = SpyRepository(TaskRepository(session))

        async def _read_in_separate_session(task_id):
            async with session_factory() as other:
                return await TaskRepository(other).get(task_id)

        publisher = StatusAssertingPublisher(_read_in_separate_session)
        service = TaskService(repository, publisher)

        task = await service.create_task(TaskCreate(title="demo"))

    assert task.status == TaskStatus.PENDING
    assert publisher.durable_status_at_publish == TaskStatus.PENDING
    assert repository.commit_count >= 1

    async with session_factory() as session:
        persisted = await TaskRepository(session).get(task.id)
    assert persisted is not None
    assert persisted.status == TaskStatus.PENDING


async def test_create_task_publish_failure_marks_failed_and_raises(
    session_factory,
) -> None:
    async with session_factory() as session:
        repository = SpyRepository(TaskRepository(session))
        service = TaskService(repository, FailingPublisher())

        with pytest.raises(MessagePublishError):
            await service.create_task(TaskCreate(title="demo"))

        commit_count = repository.commit_count

    async with session_factory() as session:
        items, total = await TaskRepository(session).list()

    assert total == 1
    assert items[0].status == TaskStatus.FAILED
    assert items[0].error is not None
    assert commit_count >= 2


async def test_cancel_task_requests_row_lock(repository: TaskRepository) -> None:
    spy = SpyRepository(repository)
    service = TaskService(spy, NullPublisher())
    task = await service.create_task(TaskCreate(title="demo"))
    spy.get_for_update.clear()
    commits_before = spy.commit_count

    cancelled = await service.cancel_task(task.id)

    assert spy.get_for_update == [True]
    assert cancelled.status == TaskStatus.CANCELLED
    assert spy.commit_count == commits_before + 1


async def test_mark_in_progress_requests_row_lock(repository: TaskRepository) -> None:
    spy = SpyRepository(repository)
    service = TaskService(spy, NullPublisher())
    task = await service.create_task(TaskCreate(title="demo"))
    spy.get_for_update.clear()

    await service.mark_in_progress(task.id)

    assert spy.get_for_update == [True]


async def test_get_task_missing_raises_not_found(service: TaskService) -> None:
    with pytest.raises(TaskNotFoundError):
        await service.get_task(uuid4())


async def test_get_status_returns_current_status(service: TaskService) -> None:
    task = await _create(service)
    assert await service.get_status(task.id) == TaskStatus.PENDING


@pytest.mark.parametrize("status", [TaskStatus.NEW, TaskStatus.PENDING])
async def test_cancel_allowed_from_new_or_pending(
    service: TaskService, repository: TaskRepository, status: TaskStatus
) -> None:
    task = await _create(service)
    task.status = status
    await repository.update(task)

    cancelled = await service.cancel_task(task.id)

    assert cancelled.status == TaskStatus.CANCELLED
    assert cancelled.finished_at is not None


@pytest.mark.parametrize(
    "status",
    [TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED],
)
async def test_cancel_from_terminal_or_in_progress_raises(
    service: TaskService, repository: TaskRepository, status: TaskStatus
) -> None:
    task = await _create(service)
    task.status = status
    await repository.update(task)

    with pytest.raises(TaskCancellationError):
        await service.cancel_task(task.id)


async def test_mark_in_progress_sets_started_at(
    service: TaskService,
) -> None:
    task = await _create(service)
    updated = await service.mark_in_progress(task.id)

    assert updated is not None
    assert updated.status == TaskStatus.IN_PROGRESS
    assert updated.started_at is not None


async def test_mark_in_progress_skips_cancelled_returns_none(
    service: TaskService, repository: TaskRepository
) -> None:
    task = await _create(service)
    task.status = TaskStatus.CANCELLED
    await repository.update(task)

    assert await service.mark_in_progress(task.id) is None


async def test_mark_completed_sets_result_and_finished(
    service: TaskService,
) -> None:
    task = await _create(service)
    await service.mark_in_progress(task.id)

    completed = await service.mark_completed(task.id, "done")

    assert completed.status == TaskStatus.COMPLETED
    assert completed.result == "done"
    assert completed.finished_at is not None


async def test_mark_failed_sets_error_and_finished(
    service: TaskService,
) -> None:
    task = await _create(service)
    await service.mark_in_progress(task.id)

    failed = await service.mark_failed(task.id, "boom")

    assert failed.status == TaskStatus.FAILED
    assert failed.error == "boom"
    assert failed.finished_at is not None


async def test_mark_completed_from_pending_invalid_transition(
    service: TaskService,
) -> None:
    task = await _create(service)
    with pytest.raises(InvalidStatusTransitionError):
        await service.mark_completed(task.id, "done")
