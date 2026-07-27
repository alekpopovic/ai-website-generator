"""SQLAlchemy 2 asynchronous database lifecycle and session boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from platform_api.config import DatabaseSettings
from platform_api.persistence.base import Base as Base

__all__ = ["Base", "DatabaseManager"]


class DatabaseManager:
    """Own one asynchronous engine and its session factory."""

    def __init__(self, settings: DatabaseSettings) -> None:
        if settings.url is None:
            raise ValueError("DATABASE_URL is required when fake dependencies are disabled")
        self.engine: AsyncEngine = create_async_engine(
            settings.url.get_secret_value(),
            echo=settings.echo,
            pool_pre_ping=True,
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_timeout=settings.pool_timeout_seconds,
            connect_args={
                "command_timeout": settings.command_timeout_seconds,
                "server_settings": {"timezone": "UTC"},
            },
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a transaction-neutral session owned by the request scope."""
        async with self.session_factory() as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """Yield a session with one explicit commit-or-rollback boundary."""
        async with self.session_factory() as session, session.begin():
            yield session

    async def check_health(self) -> None:
        """Execute the bounded PostgreSQL liveness query."""
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        """Dispose pooled database connections during application shutdown."""
        await self.engine.dispose()
