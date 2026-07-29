"""Transaction-scoped SQLAlchemy persistence for normalized analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.persistence.models import (
    AnalysisRun,
    CrawlPage,
    PageProfile,
    Project,
    ScanArtifact,
    ScanCampaign,
    ScanTarget,
    SectionPattern,
    SectionPatternEmbedding,
    WebsiteProfile,
)
from platform_api.persistence.pagination import Page

ProfileEntity = PageProfile | WebsiteProfile | SectionPattern
ProfileT = TypeVar("ProfileT", PageProfile, WebsiteProfile, SectionPattern, AnalysisRun)


@dataclass(frozen=True, slots=True)
class PatternFilters:
    domain: str | None = None
    category: str | None = None
    page_type: str | None = None
    section_type: str | None = None
    layout: str | None = None
    language: str | None = None
    minimum_confidence: float | None = None
    maximum_confidence: float | None = None
    approval_state: str | None = None
    provenance_state: str | None = None


@dataclass(frozen=True, slots=True)
class PatternContext:
    pattern: SectionPattern
    target: ScanTarget
    page: CrawlPage
    run: AnalysisRun
    website_profile: WebsiteProfile | None
    embedding: SectionPatternEmbedding | None
    screenshot: ScanArtifact | None


class AnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: object) -> None:
        self._session.add(entity)

    async def flush(self) -> None:
        await self._session.flush()

    async def run(self, run_id: UUID) -> AnalysisRun | None:
        return cast(AnalysisRun | None, await self._session.get(AnalysisRun, run_id))

    async def validate_page_context(
        self, *, project_id: UUID, campaign_id: UUID, website_id: UUID, page_id: UUID
    ) -> bool:
        found = await self._session.scalar(
            select(CrawlPage.id)
            .join(ScanCampaign, CrawlPage.campaign_id == ScanCampaign.id)
            .join(ScanTarget, CrawlPage.target_id == ScanTarget.id)
            .where(
                CrawlPage.id == page_id,
                CrawlPage.campaign_id == campaign_id,
                CrawlPage.target_id == website_id,
                ScanCampaign.project_id == project_id,
                ScanTarget.campaign_id == campaign_id,
            )
            .with_for_update(of=CrawlPage)
        )
        return found is not None

    async def validate_website_context(
        self, *, project_id: UUID, campaign_id: UUID, website_id: UUID
    ) -> bool:
        found = await self._session.scalar(
            select(ScanTarget.id)
            .join(ScanCampaign, ScanTarget.campaign_id == ScanCampaign.id)
            .where(
                ScanTarget.id == website_id,
                ScanTarget.campaign_id == campaign_id,
                ScanCampaign.project_id == project_id,
            )
            .with_for_update(of=ScanTarget)
        )
        return found is not None

    async def clear_current_page(self, page_id: UUID) -> None:
        await self._session.execute(
            update(PageProfile)
            .where(PageProfile.source_page_id == page_id, PageProfile.is_current.is_(True))
            .values(is_current=False)
        )

    async def clear_current_website(self, website_id: UUID) -> None:
        await self._session.execute(
            update(WebsiteProfile)
            .where(
                WebsiteProfile.source_website_id == website_id,
                WebsiteProfile.is_current.is_(True),
            )
            .values(is_current=False)
        )

    async def duplicate_pattern(
        self, *, project_id: UUID, website_id: UUID, page_id: UUID, digest: str
    ) -> SectionPattern | None:
        return cast(
            SectionPattern | None,
            await self._session.scalar(
                select(SectionPattern)
                .where(
                    SectionPattern.project_id == project_id,
                    SectionPattern.source_website_id == website_id,
                    SectionPattern.source_page_id != page_id,
                    SectionPattern.pattern_hash == digest,
                    SectionPattern.duplicate_of_id.is_(None),
                )
                .order_by(SectionPattern.created_at.asc(), SectionPattern.id.asc())
                .limit(1)
            ),
        )

    async def owned_page(
        self, profile_id: UUID, project_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> PageProfile | None:
        return await self._owned(PageProfile, profile_id, project_id, owner_id, for_update)

    async def owned_website(
        self, profile_id: UUID, project_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> WebsiteProfile | None:
        return await self._owned(WebsiteProfile, profile_id, project_id, owner_id, for_update)

    async def owned_pattern(
        self, pattern_id: UUID, project_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> SectionPattern | None:
        return await self._owned(SectionPattern, pattern_id, project_id, owner_id, for_update)

    async def list_pages(
        self, *, project_id: UUID, owner_id: UUID, limit: int, offset: int, current_only: bool
    ) -> Page[PageProfile] | None:
        statement = select(PageProfile).where(PageProfile.project_id == project_id)
        if current_only:
            statement = statement.where(PageProfile.is_current.is_(True))
        return await self._owned_list(statement, PageProfile, project_id, owner_id, limit, offset)

    async def list_websites(
        self, *, project_id: UUID, owner_id: UUID, limit: int, offset: int, current_only: bool
    ) -> Page[WebsiteProfile] | None:
        statement = select(WebsiteProfile).where(WebsiteProfile.project_id == project_id)
        if current_only:
            statement = statement.where(WebsiteProfile.is_current.is_(True))
        return await self._owned_list(
            statement, WebsiteProfile, project_id, owner_id, limit, offset
        )

    async def list_patterns(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
        filters: PatternFilters,
    ) -> Page[SectionPattern] | None:
        statement = _filtered_pattern_statement(project_id, filters)
        return await self._owned_list(
            statement, SectionPattern, project_id, owner_id, limit, offset
        )

    async def pattern_facets(
        self, *, project_id: UUID, owner_id: UUID, filters: PatternFilters
    ) -> dict[str, tuple[tuple[str, int], ...]] | None:
        owns = await self._session.scalar(
            select(Project.id).where(Project.id == project_id, Project.owner_id == owner_id)
        )
        if owns is None:
            return None
        base = _filtered_pattern_statement(project_id, filters).order_by(None).subquery()
        fields = {
            "domains": base.c.source_domain,
            "categories": base.c.category,
            "page_types": base.c.page_type,
            "section_types": base.c.section_type,
            "layouts": base.c.layout,
            "languages": base.c.language,
            "approvals": base.c.approval_state,
            "provenance": base.c.provenance_state,
        }
        result: dict[str, tuple[tuple[str, int], ...]] = {}
        for name, column in fields.items():
            rows = (
                await self._session.execute(
                    select(column, func.count())
                    .where(column.is_not(None))
                    .group_by(column)
                    .order_by(func.count().desc(), column.asc())
                )
            ).all()
            result[name] = tuple((str(value), int(count)) for value, count in rows)
        total = int(await self._session.scalar(select(func.count()).select_from(base)) or 0)
        result["total"] = (("total", total),)
        return result

    async def pattern_context(
        self, *, project_id: UUID, pattern_id: UUID, owner_id: UUID
    ) -> PatternContext | None:
        statement = (
            select(
                SectionPattern,
                ScanTarget,
                CrawlPage,
                AnalysisRun,
                WebsiteProfile,
                SectionPatternEmbedding,
                ScanArtifact,
            )
            .join(Project, Project.id == SectionPattern.project_id)
            .join(ScanTarget, ScanTarget.id == SectionPattern.source_website_id)
            .join(CrawlPage, CrawlPage.id == SectionPattern.source_page_id)
            .join(AnalysisRun, AnalysisRun.id == SectionPattern.analysis_run_id)
            .outerjoin(
                WebsiteProfile,
                (WebsiteProfile.source_website_id == SectionPattern.source_website_id)
                & WebsiteProfile.is_current.is_(True),
            )
            .outerjoin(
                SectionPatternEmbedding,
                SectionPatternEmbedding.section_pattern_id == SectionPattern.id,
            )
            .outerjoin(
                ScanArtifact,
                (ScanArtifact.crawl_page_id == SectionPattern.source_page_id)
                & ScanArtifact.artifact_type.in_(("desktop_screenshot", "viewport_screenshot"))
                & (ScanArtifact.retention_status == "active")
                & (ScanArtifact.provenance_status == "authorized"),
            )
            .where(
                SectionPattern.id == pattern_id,
                SectionPattern.project_id == project_id,
                Project.owner_id == owner_id,
            )
            .order_by(ScanArtifact.created_at.desc(), SectionPatternEmbedding.updated_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).one_or_none()
        return PatternContext(*row) if row is not None else None

    async def owned_patterns(
        self, pattern_ids: tuple[UUID, ...], project_id: UUID, owner_id: UUID
    ) -> tuple[SectionPattern, ...]:
        items = (
            await self._session.scalars(
                select(SectionPattern)
                .join(Project, Project.id == SectionPattern.project_id)
                .where(
                    SectionPattern.id.in_(pattern_ids),
                    SectionPattern.project_id == project_id,
                    Project.owner_id == owner_id,
                )
                .with_for_update(of=SectionPattern)
            )
        ).all()
        by_id = {item.id: item for item in items}
        return tuple(by_id[item_id] for item_id in pattern_ids if item_id in by_id)

    async def list_runs(
        self, *, project_id: UUID, owner_id: UUID, limit: int, offset: int
    ) -> Page[AnalysisRun] | None:
        return await self._owned_list(
            select(AnalysisRun).where(AnalysisRun.project_id == project_id),
            AnalysisRun,
            project_id,
            owner_id,
            limit,
            offset,
        )

    async def _owned(
        self,
        entity_type: type[ProfileT],
        entity_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        for_update: bool,
    ) -> ProfileT | None:
        statement = (
            select(entity_type)
            .join(Project, entity_type.project_id == Project.id)
            .where(
                entity_type.id == entity_id,
                entity_type.project_id == project_id,
                Project.owner_id == owner_id,
            )
        )
        if for_update:
            statement = statement.with_for_update(of=entity_type)
        return cast(ProfileT | None, await self._session.scalar(statement))

    async def _owned_list(
        self,
        statement: Select[tuple[ProfileT]],
        entity_type: type[ProfileT],
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
    ) -> Page[ProfileT] | None:
        owns = await self._session.scalar(
            select(Project.id).where(Project.id == project_id, Project.owner_id == owner_id)
        )
        if owns is None:
            return None
        count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
        total = int(await self._session.scalar(count_statement) or 0)
        items = tuple(
            (
                await self._session.scalars(
                    statement.order_by(entity_type.created_at.desc(), entity_type.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        return Page(items=items, total=total, limit=limit, offset=offset)


def _filtered_pattern_statement(
    project_id: UUID, filters: PatternFilters
) -> Select[tuple[SectionPattern]]:
    statement = (
        select(
            SectionPattern,
            ScanTarget.source_domain.label("source_domain"),
            CrawlPage.page_type.label("page_type"),
        )
        .join(ScanTarget, ScanTarget.id == SectionPattern.source_website_id)
        .join(CrawlPage, CrawlPage.id == SectionPattern.source_page_id)
        .where(SectionPattern.project_id == project_id)
    )
    conditions = (
        (ScanTarget.source_domain, filters.domain),
        (SectionPattern.category, filters.category),
        (CrawlPage.page_type, filters.page_type),
        (SectionPattern.section_type, filters.section_type),
        (SectionPattern.layout, filters.layout),
        (SectionPattern.language, filters.language),
        (SectionPattern.approval_state, filters.approval_state),
        (SectionPattern.provenance_state, filters.provenance_state),
    )
    for column, value in conditions:
        if value is not None:
            statement = statement.where(column == value)
    if filters.minimum_confidence is not None:
        statement = statement.where(SectionPattern.confidence >= filters.minimum_confidence)
    if filters.maximum_confidence is not None:
        statement = statement.where(SectionPattern.confidence <= filters.maximum_confidence)
    return cast(Select[tuple[SectionPattern]], statement)
