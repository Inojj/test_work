from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions import TaskServiceError


async def _task_service_error_handler(
    _request: Request, exc: TaskServiceError
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc)},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(TaskServiceError, _task_service_error_handler)
