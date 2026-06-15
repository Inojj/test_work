class TaskServiceError(Exception):
    """Base error for the task service domain."""

    status_code: int = 500


class TaskNotFoundError(TaskServiceError):
    status_code = 404


class TaskCancellationError(TaskServiceError):
    status_code = 409


class InvalidStatusTransitionError(TaskServiceError):
    status_code = 409


class MessagePublishError(TaskServiceError):
    status_code = 503
