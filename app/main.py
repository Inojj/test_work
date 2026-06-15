from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.v1.tasks import router as tasks_router
from app.config import get_settings
from app.messaging.publisher import RabbitMQPublisher


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    publisher = RabbitMQPublisher(
        url=settings.RABBITMQ_URL,
        queue_name=settings.TASK_QUEUE_NAME,
    )
    await publisher.connect()
    app.state.publisher = publisher
    try:
        yield
    finally:
        await publisher.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        description="Asynchronous, scalable task management service.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(tasks_router)
    register_exception_handlers(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
