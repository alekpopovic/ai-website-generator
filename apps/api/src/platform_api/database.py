"""SQLAlchemy 2 asynchronous database lifecycle and session boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from platform_api.config import DatabaseSettings


class Base(DeclarativeBase):
    """Declarative metadata root imported by Alembic."""


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
            connect_args={"command_timeout": settings.command_timeout_seconds},
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a transaction-neutral session owned by the request scope."""
        async with self.session_factory() as session:
            yield session

    async def close(self) -> None:
        """Dispose pooled database connections during application shutdown."""
        await self.engine.dispose()
