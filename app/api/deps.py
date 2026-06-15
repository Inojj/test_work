from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.messaging.publisher import AbstractTaskPublisher
from app.repositories.task_repository import TaskRepository
from app.services.task_service import TaskService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_publisher(request: Request) -> AbstractTaskPublisher:
    return request.app.state.publisher


PublisherDep = Annotated[AbstractTaskPublisher, Depends(get_publisher)]


def get_task_service(
    session: SessionDep,
    publisher: PublisherDep,
) -> TaskService:
    return TaskService(TaskRepository(session), publisher)


TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
