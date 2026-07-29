"""Structured-analysis persistence, source safety, and curation tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from platform_api.analysis.patterns import pattern_hash, retrieval_document
from platform_api.analysis.repository import AnalysisRepository
from platform_api.analysis.schemas import (
    AnalysisRunInput,
    BulkCurationItem,
    BulkCurationRequest,
    CurationRequest,
    PageAnalysisPersistenceInput,
)
from platform_api.analysis.service import AnalysisProfileService
from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import (
    AnalysisRun,
    AuditLog,
)
from platform_api.persistence.models import (
    PageProfile as PageProfileRecord,
)
from platform_api.persistence.models import (
    SectionPattern as SectionPatternRecord,
)
from platform_schemas import (
    AnalysisConfidence,
    ColorTokens,
    CopyPurpose,
    DesignTokens,
    PageProfile,
    PageType,
    SectionPattern,
    SectionType,
    SpacingTokens,
    StyleTag,
    TypographyTokens,
)
from sqlalchemy import Table

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def analyzed_profile(page_id: UUID) -> tuple[PageProfile, DesignTokens]:
    confidence = AnalysisConfidence(
        overall=0.7,
        structure=0.8,
        design_tokens=0.7,
        responsive_behavior=0.6,
        accessibility=0.6,
    )
    profile = PageProfile(
        source_page_id=page_id,
        page_type=PageType.HOMEPAGE,
        sections=(
            SectionPattern(
                section_type=SectionType.HERO,
                order=0,
                copy_purpose=CopyPurpose.VALUE_PROPOSITION,
                layout="split",
            ),
        ),
        confidence=confidence,
    )
    tokens = DesignTokens(
        colors=ColorTokens(),
        typography=TypographyTokens(),
        spacing=SpacingTokens(),
        style_tags=(StyleTag.MINIMALIST, StyleTag.SPACIOUS),
    )
    return profile, tokens


class FakeAnalysisRepository:
    def __init__(self) -> None:
        self.entities: list[object] = []
        self.runs: dict[UUID, AnalysisRun] = {}
        self.pages: dict[UUID, PageProfileRecord] = {}
        self.patterns: list[SectionPatternRecord] = []
        self.cleared_pages: list[UUID] = []

    def add(self, entity: AnalysisRun | PageProfileRecord | SectionPatternRecord) -> None:
        if not isinstance(entity, AnalysisRun):
            entity.id = uuid4()
        entity.created_at = NOW
        entity.updated_at = NOW
        if isinstance(entity, (PageProfileRecord, SectionPatternRecord)):
            entity.version = 1
        self.entities.append(entity)
        if isinstance(entity, AnalysisRun):
            self.runs[entity.id] = entity
        elif isinstance(entity, PageProfileRecord):
            self.pages[entity.id] = entity
        elif isinstance(entity, SectionPatternRecord):
            self.patterns.append(entity)

    async def flush(self) -> None:
        return None

    async def run(self, run_id: UUID) -> AnalysisRun | None:
        return self.runs.get(run_id)

    async def validate_page_context(self, **_: UUID) -> bool:
        return True

    async def clear_current_page(self, page_id: UUID) -> None:
        self.cleared_pages.append(page_id)
        for profile in self.pages.values():
            if profile.source_page_id == page_id:
                profile.is_current = False

    async def duplicate_pattern(
        self, *, project_id: UUID, website_id: UUID, page_id: UUID, digest: str
    ) -> SectionPatternRecord | None:
        return next(
            (
                item
                for item in self.patterns
                if item.project_id == project_id
                and item.source_website_id == website_id
                and item.source_page_id != page_id
                and item.pattern_hash == digest
                and item.duplicate_of_id is None
            ),
            None,
        )

    async def owned_page(
        self,
        profile_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> PageProfileRecord | None:
        del owner_id, for_update
        profile = self.pages.get(profile_id)
        return profile if profile is not None and profile.project_id == project_id else None

    async def owned_patterns(
        self, pattern_ids: tuple[UUID, ...], project_id: UUID, owner_id: UUID
    ) -> tuple[SectionPatternRecord, ...]:
        del owner_id
        by_id = {item.id: item for item in self.patterns if item.project_id == project_id}
        return tuple(by_id[item_id] for item_id in pattern_ids if item_id in by_id)


class RecordingAuditRepository:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def add(self, entry: AuditLog) -> None:
        self.entries.append(entry)


def command(
    *, page_id: UUID, run_id: UUID, website_id: UUID, project_id: UUID
) -> PageAnalysisPersistenceInput:
    profile, tokens = analyzed_profile(page_id)
    return PageAnalysisPersistenceInput(
        project_id=project_id,
        campaign_id=uuid4(),
        source_website_id=website_id,
        source_page_id=page_id,
        run=AnalysisRunInput(
            id=run_id,
            prompt_version="page-analysis-v1",
            analyzer_version="dspy-page-analyzer-v1",
            strategy="dspy",
            model_name="vision-model",
            model_digest="a" * 64,
            schema_version=1,
            latency_ms=42,
            attempts=1,
        ),
        profile=profile,
        design_tokens=tokens,
        language="en",
    )


@pytest.mark.anyio
async def test_each_run_is_preserved_and_only_latest_page_profile_is_current() -> None:
    repository = FakeAnalysisRepository()
    service = AnalysisProfileService(repository, AuditLogService(RecordingAuditRepository()))  # type: ignore[arg-type]
    page_id, website_id, project_id = uuid4(), uuid4(), uuid4()

    first = await service.persist_page(
        command(page_id=page_id, run_id=uuid4(), website_id=website_id, project_id=project_id)
    )
    second = await service.persist_page(
        command(page_id=page_id, run_id=uuid4(), website_id=website_id, project_id=project_id)
    )

    assert len(repository.runs) == 2
    assert repository.pages[first.id].is_current is False
    assert repository.pages[second.id].is_current is True
    assert len(repository.patterns) == 2

    await service.persist_page(
        command(page_id=uuid4(), run_id=uuid4(), website_id=website_id, project_id=project_id)
    )
    assert repository.patterns[2].duplicate_of_id == repository.patterns[0].id


@pytest.mark.anyio
async def test_analysis_run_id_is_append_only_idempotency_boundary() -> None:
    repository = FakeAnalysisRepository()
    service = AnalysisProfileService(repository, AuditLogService(RecordingAuditRepository()))  # type: ignore[arg-type]
    run_id = uuid4()
    value = command(page_id=uuid4(), run_id=run_id, website_id=uuid4(), project_id=uuid4())
    await service.persist_page(value)

    with pytest.raises(ApiError) as duplicate:
        await service.persist_page(value)

    assert duplicate.value.code == "analysis_run_exists"


def test_retrieval_document_and_hash_contain_only_controlled_values() -> None:
    profile, tokens = analyzed_profile(uuid4())
    section = profile.sections[0]
    document = retrieval_document(
        section, category="homepage", language="en", style_tags=tokens.style_tags
    )

    assert "section=hero" in document
    assert "purpose=value-proposition" in document
    assert "Acme" not in document
    assert len(pattern_hash(section, tokens.style_tags)) == 64
    assert pattern_hash(section, tokens.style_tags) == pattern_hash(section, tokens.style_tags)


@pytest.mark.anyio
async def test_curation_is_version_checked_and_audited_without_profile_content() -> None:
    repository = FakeAnalysisRepository()
    audits = RecordingAuditRepository()
    service = AnalysisProfileService(repository, AuditLogService(audits))  # type: ignore[arg-type]
    value = command(page_id=uuid4(), run_id=uuid4(), website_id=uuid4(), project_id=uuid4())
    profile = await service.persist_page(value)
    owner_id = uuid4()

    updated = await service.curate_page(
        value.project_id,
        profile.id,
        CurationRequest(approval_state="approved", version=profile.version, note="Reviewed"),
        owner_id=owner_id,
        request_id="request-1",
    )

    assert updated.approval_state == "approved"
    assert audits.entries[0].action == "analysis.page_profile.approved"
    assert "profile" not in str(audits.entries[0].details).casefold()


@pytest.mark.anyio
async def test_bulk_pattern_curation_is_version_checked_and_audited() -> None:
    repository = FakeAnalysisRepository()
    audits = RecordingAuditRepository()
    service = AnalysisProfileService(repository, AuditLogService(audits))  # type: ignore[arg-type]
    value = command(page_id=uuid4(), run_id=uuid4(), website_id=uuid4(), project_id=uuid4())
    await service.persist_page(value)
    patterns = tuple(repository.patterns)

    updated = await service.curate_patterns_bulk(
        value.project_id,
        BulkCurationRequest(
            items=tuple(BulkCurationItem(id=item.id, version=item.version) for item in patterns),
            approval_state="approved",
            note="Dataset review",
        ),
        owner_id=uuid4(),
        request_id="bulk-request",
    )

    assert {item.approval_state for item in updated} == {"approved"}
    assert len(audits.entries) == len(patterns)
    assert all(entry.request_id == "bulk-request" for entry in audits.entries)


def test_analysis_tables_expose_repository_grouping_indexes() -> None:
    page_indexes = {index.name for index in cast(Table, PageProfileRecord.__table__).indexes}
    pattern_indexes = {index.name for index in cast(Table, SectionPatternRecord.__table__).indexes}
    assert "uq_page_profiles_current_source_page" in page_indexes
    assert "ix_section_patterns_hash" in pattern_indexes
    assert "ix_section_patterns_project_type" in pattern_indexes


@pytest.mark.anyio
async def test_repository_owner_query_is_scoped_through_project_owner() -> None:
    class CapturingSession:
        statement: object | None = None

        async def scalar(self, statement: object) -> None:
            self.statement = statement

    session = CapturingSession()
    repository = AnalysisRepository(session)  # type: ignore[arg-type]
    await repository.owned_page(uuid4(), uuid4(), uuid4())

    sql = str(session.statement)
    assert "JOIN projects" in sql
    assert "projects.owner_id" in sql
    assert "page_profiles.project_id" in sql
