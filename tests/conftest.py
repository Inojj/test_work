from collections.abc import AsyncIterator
from typing import Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.api.deps import get_publisher
from app.database import get_session
from app.main import create_app
from app.messaging.publisher import NullPublisher
from app.models.base import Base


@pytest_asyncio.fixture
async def engine() -> AsyncIterator:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
def publisher() -> NullPublisher:
    return NullPublisher()


@pytest.fixture
def app(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: NullPublisher,
):
    application = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session
            await session.commit()

    def _override_get_publisher() -> NullPublisher:
        return publisher

    application.dependency_overrides[get_session] = _override_get_session
    application.dependency_overrides[get_publisher] = _override_get_publisher
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def make_task() -> Callable[..., dict]:
    def _make(**overrides) -> dict:
        body = {"title": "demo task", "priority": "MEDIUM"}
        body.update(overrides)
        return body

    return _make
