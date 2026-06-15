from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy.exc import DBAPIError, OperationalError

from app.database import async_session_factory
from app.exceptions import TaskNotFoundError
from app.messaging.publisher import NullPublisher
from app.models.task import Task
from app.repositories.task_repository import TaskRepository
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)


class TaskProcessingError(Exception):
    """Raised by the workload to signal a recoverable business-level failure.

    Such failures are recorded on the task (mark_failed) and the message is
    acknowledged. Anything else (DB/connection errors) propagates so the caller
    can requeue.
    """


_INFRA_ERRORS: tuple[type[BaseException], ...] = (OperationalError, DBAPIError)


def _is_infrastructure_error(exc: BaseException) -> bool:
    return isinstance(exc, _INFRA_ERRORS)


class TaskProcessor:
    """Processes a single task within its own database session."""

    async def process(self, task_id: UUID) -> None:
        factory = async_session_factory()
        async with factory() as session:
            repository = TaskRepository(session)
            service = TaskService(repository, NullPublisher())

            try:
                task = await service.mark_in_progress(task_id)
            except TaskNotFoundError:
                logger.info("Task %s no longer exists, skipping", task_id)
                return
            if task is None:
                logger.info("Task %s is cancelled, skipping", task_id)
                return

            try:
                result = await self._execute(task)
            except Exception as exc:
                if _is_infrastructure_error(exc):
                    raise
                logger.warning("Task %s failed: %s", task_id, exc)
                await service.mark_failed(task_id, str(exc))
                await session.commit()
                return

            await service.mark_completed(task_id, result)
            await session.commit()
            logger.info("Task %s completed", task_id)

    async def _execute(self, task: Task) -> str:
        """Simulated workload. Replace with real processing logic.

        Raise TaskProcessingError for recoverable business failures.
        """
        await asyncio.sleep(0.1)
        return f"Processed task '{task.title}'"
