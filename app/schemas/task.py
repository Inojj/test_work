from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import TaskPriority, TaskStatus


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    priority: TaskPriority
    status: TaskStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: str | None
    error: str | None


class TaskStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: TaskStatus


class TaskList(BaseModel):
    items: list[TaskRead]
    total: int
    limit: int
    offset: int
