from app.schemas.enums import TaskStatus

ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.NEW: frozenset(
        {TaskStatus.PENDING, TaskStatus.CANCELLED, TaskStatus.FAILED}
    ),
    TaskStatus.PENDING: frozenset(
        {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED, TaskStatus.FAILED}
    ),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def can_transition(old: TaskStatus, new: TaskStatus) -> bool:
    return new in ALLOWED_TRANSITIONS.get(old, frozenset())
