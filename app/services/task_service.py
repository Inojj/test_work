from datetime import datetime, timezone
from uuid import UUID

from app.exceptions import (
    InvalidStatusTransitionError,
    MessagePublishError,
    TaskCancellationError,
    TaskNotFoundError,
)
from app.messaging.publisher import AbstractTaskPublisher
from app.models.task import Task
from app.repositories.task_repository import AbstractTaskRepository
from app.schemas.enums import TaskPriority, TaskStatus
from app.schemas.task import TaskCreate
from app.services.transitions import can_transition


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskService:
    def __init__(
        self,
        repository: AbstractTaskRepository,
        publisher: AbstractTaskPublisher,
    ) -> None:
        self._repository = repository
        self._publisher = publisher

    async def create_task(self, data: TaskCreate) -> Task:
        task = Task(
            title=data.title,
            description=data.description,
            priority=data.priority,
            status=TaskStatus.NEW,
        )
        task = await self._repository.create(task)

        self._transition(task, TaskStatus.PENDING)
        task = await self._repository.update(task)
        await self._repository.commit()

        try:
            await self._publisher.publish_task(task.id, task.priority)
        except Exception as exc:
            try:
                self._transition(task, TaskStatus.FAILED)
            except InvalidStatusTransitionError as guard_error:
                raise MessagePublishError(str(exc)) from guard_error
            task.error = f"Failed to enqueue task: {exc}"
            task.finished_at = _utcnow()
            await self._repository.update(task)
            await self._repository.commit()
            raise MessagePublishError(str(exc)) from exc

        return task

    async def get_task(self, task_id: UUID) -> Task:
        task = await self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        return task

    async def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Task], int]:
        return await self._repository.list(
            status=status, priority=priority, limit=limit, offset=offset
        )

    async def cancel_task(self, task_id: UUID) -> Task:
        task = await self._repository.get(task_id, for_update=True)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        if task.status not in (TaskStatus.NEW, TaskStatus.PENDING):
            raise TaskCancellationError(
                f"Task in status {task.status.value} cannot be cancelled"
            )
        self._transition(task, TaskStatus.CANCELLED)
        task.finished_at = _utcnow()
        task = await self._repository.update(task)
        await self._repository.commit()
        return task

    async def get_status(self, task_id: UUID) -> TaskStatus:
        task = await self.get_task(task_id)
        return task.status

    async def mark_in_progress(self, task_id: UUID) -> Task | None:
        task = await self._repository.get(task_id, for_update=True)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        if task.status != TaskStatus.PENDING:
            return None
        self._transition(task, TaskStatus.IN_PROGRESS)
        task.started_at = _utcnow()
        return await self._repository.update(task)

    async def mark_completed(self, task_id: UUID, result: str | None) -> Task:
        task = await self.get_task(task_id)
        self._transition(task, TaskStatus.COMPLETED)
        task.result = result
        task.finished_at = _utcnow()
        return await self._repository.update(task)

    async def mark_failed(self, task_id: UUID, error: str) -> Task:
        task = await self.get_task(task_id)
        self._transition(task, TaskStatus.FAILED)
        task.error = error
        task.finished_at = _utcnow()
        return await self._repository.update(task)

    @staticmethod
    def _transition(task: Task, new_status: TaskStatus) -> None:
        if not can_transition(task.status, new_status):
            raise InvalidStatusTransitionError(
                f"Cannot transition from {task.status.value} to {new_status.value}"
            )
        task.status = new_status
