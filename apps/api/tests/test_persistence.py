"""Unit tests for shared persistence conventions and repository boundaries."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from platform_api.database import DatabaseManager
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.base import Base
from platform_api.persistence.json import normalize_json_value
from platform_api.persistence.models import (
    AuditLog,
    CrawlPage,
    CrawlPolicyRecord,
    PageScan,
    Project,
    ScanCampaign,
    ScanFailure,
    ScanTarget,
    ScanTargetImport,
    User,
)
from platform_api.persistence.pagination import apply_pagination
from platform_api.persistence.repositories import ProjectRepository, SqlAlchemyRepository
from platform_api.scans.repositories import ScanCampaignRepository
from sqlalchemy import DateTime, Enum, String, Table, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


def test_metadata_contains_named_foundation_tables_and_constraints() -> None:
    """Alembic sees every initial table through one naming convention."""
    assert set(Base.metadata.tables) == {
        "audit_logs",
        "analysis_runs",
        "auth_action_tokens",
        "job_events",
        "projects",
        "refresh_tokens",
        "users",
        "scan_campaigns",
        "scan_artifacts",
        "scan_targets",
        "crawl_pages",
        "crawl_policy_records",
        "datasets",
        "dataset_builds",
        "dataset_versions",
        "dataset_items",
        "dataset_quality_reports",
        "embedding_index_failures",
        "embedding_runs",
        "page_scans",
        "page_profiles",
        "scan_failures",
        "scan_target_imports",
        "scan_target_import_rows",
        "section_patterns",
        "section_pattern_embeddings",
        "website_profiles",
    }
    assert Base.metadata.tables["users"].primary_key.name == "pk_users"
    assert all(
        constraint.name is not None
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
    )


def test_statuses_are_strings_and_editable_records_are_versioned() -> None:
    """Statuses remain portable strings while user/project edits use optimistic locking."""
    for table_name in (
        "users",
        "refresh_tokens",
        "projects",
        "job_events",
        "scan_campaigns",
        "scan_targets",
        "crawl_pages",
        "page_scans",
        "scan_target_imports",
    ):
        status_type = Base.metadata.tables[table_name].c.status.type
        assert isinstance(status_type, String)
        assert not isinstance(status_type, Enum)
    assert User.__mapper__.version_id_col is User.__table__.c.version
    assert Project.__mapper__.version_id_col is Project.__table__.c.version
    for model in (
        ScanCampaign,
        ScanTarget,
        CrawlPolicyRecord,
        CrawlPage,
        PageScan,
        ScanFailure,
        ScanTargetImport,
    ):
        assert model.__mapper__.version_id_col is model.__table__.c.version


def test_crawl_page_fingerprint_grouping_indexes_are_declared() -> None:
    names = {index.name for index in cast(Table, CrawlPage.__table__).indexes}
    assert {
        "ix_crawl_pages_campaign_content_fingerprint",
        "ix_crawl_pages_campaign_semantic_simhash",
        "ix_crawl_pages_campaign_template_fingerprint",
        "ix_crawl_pages_exact_duplicate_of_id",
        "ix_crawl_pages_near_duplicate_of_id",
        "ix_crawl_pages_template_representative_id",
    } <= names


def test_timestamp_columns_are_timezone_aware() -> None:
    """All persisted timestamps use TIMESTAMP WITH TIME ZONE semantics."""
    for table in Base.metadata.tables.values():
        for column in table.c:
            if column.name.endswith("_at"):
                assert isinstance(column.type, DateTime)
                assert column.type.timezone is True


def test_safe_json_normalizes_approved_values() -> None:
    """JSONB conventions normalize identifiers and aware timestamps."""
    identifier = uuid4()
    instant = datetime(2026, 7, 27, 12, 30, tzinfo=UTC)
    assert normalize_json_value({"id": identifier, "at": instant, "items": (1, True)}) == {
        "id": str(identifier),
        "at": "2026-07-27T12:30:00Z",
        "items": [1, True],
    }


@pytest.mark.parametrize("value", [datetime(2026, 1, 1), math.inf, object()])
def test_safe_json_rejects_ambiguous_values(value: object) -> None:
    """Naive timestamps, non-finite numbers, and arbitrary objects never reach JSONB."""
    with pytest.raises((TypeError, ValueError)):
        normalize_json_value(value)


def test_pagination_validates_bounds_and_compiles_limit_offset() -> None:
    """Repository pagination has bounded, explicit SQL semantics."""
    statement = apply_pagination(select(User), limit=25, offset=50)
    assert statement._limit_clause is not None
    assert statement._offset_clause is not None
    with pytest.raises(ValueError, match="positive"):
        apply_pagination(select(User), limit=0, offset=0)
    with pytest.raises(ValueError, match="negative"):
        apply_pagination(select(User), limit=1, offset=-1)


@pytest.mark.anyio
async def test_database_health_check_uses_a_bounded_scalar_query() -> None:
    """The shared health boundary opens no ORM session or application transaction."""
    connection = MagicMock()
    connection.execute = AsyncMock()
    connection_context = MagicMock()
    connection_context.__aenter__ = AsyncMock(return_value=connection)
    connection_context.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.connect.return_value = connection_context
    manager = object.__new__(DatabaseManager)
    manager.engine = cast(AsyncEngine, engine)

    await manager.check_health()

    connection.execute.assert_awaited_once()


@pytest.mark.anyio
async def test_repository_stages_and_reads_without_committing() -> None:
    """Repositories use the supplied session and never own commits."""
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=None)
    repository = SqlAlchemyRepository(session, User)
    user = User(email="person@example.test", display_name="Person", status="active")

    repository.add(user)
    found = await repository.get(user.id)

    session.add.assert_called_once_with(user)
    session.get.assert_awaited_once_with(User, user.id)
    assert found is None
    assert session.commit.call_count == 0


@pytest.mark.anyio
async def test_repository_page_uses_supplied_session_and_returns_total() -> None:
    """Pagination performs bounded reads while retaining transaction ownership upstream."""
    session = MagicMock(spec=AsyncSession)
    users = (
        User(email="one@example.test", display_name="One", status="active"),
        User(email="two@example.test", display_name="Two", status="active"),
    )
    scalar_result = MagicMock()
    scalar_result.all.return_value = list(users)
    session.scalars = AsyncMock(return_value=scalar_result)
    session.scalar = AsyncMock(return_value=12)

    page = await SqlAlchemyRepository(session, User).page(limit=2, offset=4)

    assert page.items == users
    assert (page.total, page.limit, page.offset) == (12, 2, 4)
    session.scalars.assert_awaited_once()
    session.scalar.assert_awaited_once()
    assert session.commit.call_count == 0


@pytest.mark.anyio
async def test_project_repository_queries_are_owner_scoped() -> None:
    """Persistence authorization includes owner identity in item and collection SQL."""
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=None)
    scalar_result = MagicMock()
    scalar_result.all.return_value = []
    session.scalars = AsyncMock(return_value=scalar_result)
    repository = ProjectRepository(session)
    owner_id, project_id = uuid4(), uuid4()

    await repository.owned(project_id, owner_id)
    owned_statement = session.scalar.await_args.args[0]
    assert "projects.owner_id" in str(owned_statement)

    session.scalar.reset_mock()
    session.scalar.return_value = 0
    await repository.owned_page(
        owner_id=owner_id,
        limit=20,
        offset=0,
        search="site",
        status="draft",
        sort_by="updated_at",
        sort_order="desc",
    )
    item_statement = session.scalars.await_args.args[0]
    count_statement = session.scalar.await_args.args[0]
    assert "projects.owner_id" in str(item_statement)
    assert "projects.owner_id" in str(count_statement)


@pytest.mark.anyio
async def test_scan_repository_queries_join_project_ownership() -> None:
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=None)
    repository = ScanCampaignRepository(session)

    await repository.campaign_owned(uuid4(), uuid4(), uuid4())

    statement = session.scalar.await_args.args[0]
    compiled = str(statement)
    assert "JOIN projects" in compiled
    assert "projects.owner_id" in compiled


class RecordingAuditRepository:
    """Small repository fake that retains staged records."""

    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def add(self, entry: AuditLog) -> None:
        self.entries.append(entry)


def test_audit_service_normalizes_and_stages_an_append_only_entry() -> None:
    """Audit service validates details without controlling the transaction."""
    repository = RecordingAuditRepository()
    identifier = uuid4()
    entry = AuditLogService(repository).record(
        action="project.updated",
        resource_type="project",
        resource_id=identifier,
        details={"project_id": identifier},
    )

    assert repository.entries == [entry]
    assert entry.details == {"project_id": str(identifier)}
