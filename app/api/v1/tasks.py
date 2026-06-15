from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import TaskServiceDep
from app.schemas.enums import TaskPriority, TaskStatus
from app.schemas.task import TaskCreate, TaskList, TaskRead, TaskStatusRead

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post(
    "",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
    description="Persist a new task and enqueue it for asynchronous processing.",
)
async def create_task(data: TaskCreate, service: TaskServiceDep) -> TaskRead:
    task = await service.create_task(data)
    return TaskRead.model_validate(task)


@router.get(
    "",
    response_model=TaskList,
    summary="List tasks",
    description="List tasks with optional status/priority filters and pagination.",
)
async def list_tasks(
    service: TaskServiceDep,
    status: TaskStatus | None = Query(default=None, description="Filter by status"),
    priority: TaskPriority | None = Query(
        default=None, description="Filter by priority"
    ),
    limit: int = Query(default=20, ge=1, le=100, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
) -> TaskList:
    items, total = await service.list_tasks(
        status=status, priority=priority, limit=limit, offset=offset
    )
    return TaskList(
        items=[TaskRead.model_validate(t) for t in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{task_id}",
    response_model=TaskRead,
    summary="Get a task",
    description="Retrieve a single task by id.",
)
async def get_task(task_id: UUID, service: TaskServiceDep) -> TaskRead:
    task = await service.get_task(task_id)
    return TaskRead.model_validate(task)


@router.delete(
    "/{task_id}",
    response_model=TaskRead,
    summary="Cancel a task",
    description="Cancel a task; only NEW or PENDING tasks may be cancelled.",
)
async def cancel_task(task_id: UUID, service: TaskServiceDep) -> TaskRead:
    task = await service.cancel_task(task_id)
    return TaskRead.model_validate(task)


@router.get(
    "/{task_id}/status",
    response_model=TaskStatusRead,
    summary="Get task status",
    description="Retrieve the current status of a task.",
)
async def get_task_status(task_id: UUID, service: TaskServiceDep) -> TaskStatusRead:
    task = await service.get_task(task_id)
    return TaskStatusRead.model_validate(task)
