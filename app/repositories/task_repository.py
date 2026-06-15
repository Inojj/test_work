from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.schemas.enums import TaskPriority, TaskStatus


class AbstractTaskRepository(Protocol):
    async def create(self, task: Task) -> Task: ...

    async def get(self, task_id: UUID, *, for_update: bool = False) -> Task | None: ...

    async def list(
        self,
        *,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Task], int]: ...

    async def update(self, task: Task) -> Task: ...

    async def commit(self) -> None: ...


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task: Task) -> Task:
        self._session.add(task)
        await self._session.flush()
        await self._session.refresh(task)
        return task

    async def get(self, task_id: UUID, *, for_update: bool = False) -> Task | None:
        if not for_update:
            return await self._session.get(Task, task_id)
        stmt = select(Task).where(Task.id == task_id).with_for_update()
        return await self._session.scalar(stmt)

    async def list(
        self,
        *,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Task], int]:
        filters = []
        if status is not None:
            filters.append(Task.status == status)
        if priority is not None:
            filters.append(Task.priority == priority)

        count_stmt = select(func.count()).select_from(Task)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = await self._session.scalar(count_stmt) or 0

        items_stmt = select(Task)
        if filters:
            items_stmt = items_stmt.where(*filters)
        items_stmt = items_stmt.order_by(Task.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.scalars(items_stmt)
        return list(result.all()), total

    async def update(self, task: Task) -> Task:
        await self._session.flush()
        await self._session.refresh(task)
        return task

    async def commit(self) -> None:
        await self._session.commit()
