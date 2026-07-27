"""Alembic environment using the same async SQLAlchemy configuration as the API."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from platform_api.config import get_settings
from platform_api.database import Base
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    """Return the configured migration URL without logging it."""
    configured_url = get_settings().database.url
    if configured_url is None:
        raise RuntimeError("DATABASE_URL is required for Alembic commands")
    return configured_url.get_secret_value()


def run_migrations_offline() -> None:
    """Generate SQL without opening a database connection."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_sync_migrations(connection: Connection) -> None:
    """Run migrations using an async-engine-provided synchronous connection."""
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations through SQLAlchemy's async engine boundary."""
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = database_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(run_sync_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
