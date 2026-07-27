"""PostgreSQL integration tests for migrations and transactional persistence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from platform_api.config import DatabaseSettings, clear_settings_cache
from platform_api.database import DatabaseManager
from platform_api.persistence.models import AuditLog, Project, User
from pydantic import SecretStr
from sqlalchemy import select

pytestmark = pytest.mark.integration


def integration_database_url() -> str:
    """Require an explicitly named disposable PostgreSQL test database."""
    value = os.environ.get("INTEGRATION_DATABASE_URL")
    if value is None:
        pytest.skip("INTEGRATION_DATABASE_URL is not configured")
    if os.environ.get("INTEGRATION_DATABASE_RESET_ALLOWED") != "true":
        pytest.fail("set INTEGRATION_DATABASE_RESET_ALLOWED=true for the disposable test database")
    parsed = urlsplit(value)
    if parsed.scheme != "postgresql+asyncpg" or not parsed.path.rstrip("/").endswith("_test"):
        pytest.fail("INTEGRATION_DATABASE_URL must use asyncpg and a database ending in _test")
    return value


@pytest.fixture
def migrated_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Apply and later remove migrations only in an attested disposable database."""
    url = integration_database_url()
    monkeypatch.setenv("DATABASE_URL", url)
    clear_settings_cache()
    config = Config("apps/api/alembic.ini")
    command.upgrade(config, "head")
    try:
        yield url
    finally:
        command.downgrade(config, "base")
        clear_settings_cache()


@pytest.mark.anyio
async def test_transaction_commit_health_and_optimistic_versioning(migrated_database: str) -> None:
    """Real asyncpg sessions commit, probe, relate records, and increment versions."""
    manager = DatabaseManager(DatabaseSettings(url=SecretStr(migrated_database)))
    try:
        await manager.check_health()
        async with manager.transaction() as session:
            user = User(email="integration@local.test", display_name="Integration", status="active")
            session.add(user)
            await session.flush()
            project = Project(
                owner_id=user.id,
                name="Integration project",
                slug="integration-project",
                default_language="en",
                status="draft",
                settings={"source": "integration"},
            )
            session.add(project)
            await session.flush()
            session.add(
                AuditLog(
                    actor_user_id=user.id,
                    action="project.created",
                    resource_type="project",
                    resource_id=project.id,
                    details={"project_id": project.id},
                )
            )
            project.name = "Updated project"

        async with manager.session() as session:
            stored = await session.scalar(select(Project))
            assert stored is not None
            assert stored.version == 2
            assert stored.created_at.utcoffset() is not None
            assert await session.scalar(select(AuditLog)) is not None
    finally:
        await manager.close()


@pytest.mark.anyio
async def test_transaction_rolls_back_on_failure(migrated_database: str) -> None:
    """An exception prevents partial records from becoming visible."""
    manager = DatabaseManager(DatabaseSettings(url=SecretStr(migrated_database)))
    try:
        with pytest.raises(RuntimeError, match="force rollback"):
            async with manager.transaction() as session:
                session.add(
                    User(email="rollback@local.test", display_name="Rollback", status="active")
                )
                raise RuntimeError("force rollback")
        async with manager.session() as session:
            assert (
                await session.scalar(select(User).where(User.email == "rollback@local.test"))
                is None
            )
    finally:
        await manager.close()
