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
        "postgresql+asyncpg://migration:unused@127.0.0.1/platform_migration_test",  # pragma: allowlist secret
    )
    clear_settings_cache()
    config = Config("apps/api/alembic.ini")
    try:
        command.upgrade(config, "head", sql=True)
        upgrade_sql = capsys.readouterr().out
        command.downgrade(config, "head:base", sql=True)
        downgrade_sql = capsys.readouterr().out
    finally:
        clear_settings_cache()

    assert "CREATE TABLE users" in upgrade_sql
    assert "CREATE TABLE refresh_tokens" in upgrade_sql
    assert "CREATE TABLE projects" in upgrade_sql
    assert "CREATE TABLE audit_logs" in upgrade_sql
    assert "CREATE TABLE job_events" in upgrade_sql
    assert "CREATE TABLE auth_action_tokens" in upgrade_sql
    assert "CREATE TABLE scan_campaigns" in upgrade_sql
    assert "CREATE TABLE scan_targets" in upgrade_sql
    assert "CREATE TABLE crawl_pages" in upgrade_sql
    assert "CREATE TABLE page_scans" in upgrade_sql
    assert "CREATE TABLE scan_failures" in upgrade_sql
    assert "CREATE TABLE scan_target_imports" in upgrade_sql
    assert "CREATE TABLE scan_target_import_rows" in upgrade_sql
    assert "CREATE TABLE crawl_policy_records" in upgrade_sql
    assert "ck_scan_campaigns_robots_required" in upgrade_sql
    assert "ALTER TABLE crawl_pages ADD COLUMN final_url" in upgrade_sql
    assert "uq_scan_failures_campaign_id_failure_key" in upgrade_sql
    assert "ALTER TABLE scan_targets ADD COLUMN import_id" in upgrade_sql
    assert "uq_projects_owner_id_slug" in upgrade_sql
    assert "ck_users_status_allowed" in upgrade_sql
    assert "ck_users_ck_" not in upgrade_sql
    assert "CREATE TYPE" not in upgrade_sql
    assert "DROP TABLE job_events" in downgrade_sql
    assert "DROP TABLE scan_campaigns" in downgrade_sql
    assert "DROP TABLE scan_target_imports" in downgrade_sql
    assert "DROP TABLE users" in downgrade_sql
