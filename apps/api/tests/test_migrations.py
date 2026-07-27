"""Offline migration smoke tests that require no PostgreSQL process."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from platform_api.config import clear_settings_cache


def test_initial_migration_renders_postgresql_upgrade_sql(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The complete revision graph renders valid PostgreSQL DDL offline."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://migration:unused@127.0.0.1/platform_migration_test",
    )
    clear_settings_cache()
    config = Config("apps/api/alembic.ini")
    try:
        command.upgrade(config, "head", sql=True)
        upgrade_sql = capsys.readouterr().out
        command.downgrade(config, "20260727_0001:base", sql=True)
        downgrade_sql = capsys.readouterr().out
    finally:
        clear_settings_cache()

    assert "CREATE TABLE users" in upgrade_sql
    assert "CREATE TABLE refresh_tokens" in upgrade_sql
    assert "CREATE TABLE projects" in upgrade_sql
    assert "CREATE TABLE audit_logs" in upgrade_sql
    assert "CREATE TABLE job_events" in upgrade_sql
    assert "ck_users_status_allowed" in upgrade_sql
    assert "ck_users_ck_" not in upgrade_sql
    assert "CREATE TYPE" not in upgrade_sql
    assert "DROP TABLE job_events" in downgrade_sql
    assert "DROP TABLE users" in downgrade_sql
