"""PostgreSQL integration tests for migrations and transactional persistence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from platform_api.config import DatabaseSettings, clear_settings_cache
from platform_api.database import DatabaseManager
from platform_api.persistence.models import (
    AuditLog,
    CrawlPolicyRecord,
    Project,
    ScanCampaign,
    ScanTarget,
    ScanTargetImport,
    ScanTargetImportRow,
    User,
)
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


@pytest.mark.anyio
async def test_scan_campaign_and_target_constraints_persist_in_postgresql(
    migrated_database: str,
) -> None:
    manager = DatabaseManager(DatabaseSettings(url=SecretStr(migrated_database)))
    try:
        async with manager.transaction() as session:
            user = User(email="scan-integration@local.test", display_name="Scan", status="active")
            session.add(user)
            await session.flush()
            project = Project(
                owner_id=user.id,
                name="Scan integration",
                slug="scan-integration",
                default_language="en",
                status="draft",
                settings={},
            )
            session.add(project)
            await session.flush()
            campaign = ScanCampaign(
                project_id=project.id,
                name="Production policy",
                authorization_attested_at=datetime.now(UTC),
                respect_robots_txt=True,
                max_discovered_pages_per_domain=100,
                max_visual_pages_per_domain=20,
                maximum_crawl_depth=5,
                per_domain_concurrency=2,
                crawl_delay_seconds=1,
                overall_concurrency=4,
                desktop_viewport={"width": 1440, "height": 900},
                mobile_viewport={"width": 390, "height": 844},
                allowed_content_types=["text/html"],
                include_url_patterns=[],
                exclude_url_patterns=[],
                timeout_limits={"campaign_seconds": 7200},
                artifact_retention_policy={"retention_days": 30},
                status="draft",
                workflow_attempt=0,
            )
            session.add(campaign)
            await session.flush()
            target_import = ScanTargetImport(
                campaign_id=campaign.id,
                requested_by_user_id=user.id,
                source_type="csv",
                filename="targets.csv",
                media_type="text/csv",
                dry_run=False,
                authorization_attested_at=datetime.now(UTC),
                allow_ip_literals=False,
                status="committed",
                total_rows=1,
                processed_rows=1,
                accepted_count=1,
                duplicate_count=0,
                invalid_count=0,
                blocked_count=0,
                already_present_count=0,
                committed_count=1,
            )
            session.add(target_import)
            await session.flush()
            target = ScanTarget(
                campaign_id=campaign.id,
                import_id=target_import.id,
                import_row_number=2,
                url="https://example.com/",
                normalized_url="https://example.com/",
                source_domain="example.com",
                status="pending",
                import_metadata={"category": "fixture"},
            )
            session.add(target)
            await session.flush()
            policy_record = CrawlPolicyRecord(
                campaign_id=campaign.id,
                target_id=target.id,
                source_domain="example.com",
                robots_url="https://example.com/robots.txt",
                final_robots_url="https://example.com/robots.txt",
                fetch_status="fetched",
                fetched_at=datetime.now(UTC),
                content_sha256="a" * 64,
                crawler_user_agent="AIWebsiteGeneratorBot/1.0",
                crawl_delay_seconds=1,
                redirect_count=0,
                sitemap_urls=["https://example.com/sitemap.xml"],
                effective_policy={"respect_robots_txt": True, "policy_version": 1},
            )
            session.add(policy_record)
            session.add(
                ScanTargetImportRow(
                    import_id=target_import.id,
                    row_number=2,
                    raw_value="example.com",
                    normalized_url="https://example.com/",
                    source_domain="example.com",
                    row_metadata={"category": "fixture"},
                    outcome="accepted",
                    target_id=target.id,
                )
            )

        async with manager.session() as session:
            stored = await session.scalar(select(ScanCampaign))
            stored_target = await session.scalar(select(ScanTarget))
            imported_row = await session.scalar(select(ScanTargetImportRow))
            stored_policy = await session.scalar(select(CrawlPolicyRecord))
            assert stored is not None and stored.respect_robots_txt
            assert stored_target is not None and stored_target.campaign_id == stored.id
            assert stored_target.import_metadata == {"category": "fixture"}
            assert imported_row is not None and imported_row.row_number == 2
            assert stored_policy is not None
            assert stored_policy.effective_policy == {
                "respect_robots_txt": True,
                "policy_version": 1,
            }
    finally:
        await manager.close()
