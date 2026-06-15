from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/tasks"
    RABBITMQ_URL: str = "amqp://app:app@localhost:5672/"
    TASK_QUEUE_NAME: str = "tasks"
    WORKER_CONCURRENCY: int = 4
    APP_NAME: str = "async-task-service"
    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
