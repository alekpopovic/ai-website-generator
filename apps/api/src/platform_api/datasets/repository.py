"""Owner-scoped SQLAlchemy persistence for governed datasets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.persistence.json import JsonValue
from platform_api.persistence.models import (
    Dataset,
    DatasetItem,
    DatasetQualityReport,
    DatasetVersion,
    Project,
    ScanTarget,
    SectionPattern,
    WebsiteProfile,
)
from platform_api.persistence.pagination import Page, apply_pagination

from .schemas import SelectionPolicy


@dataclass(frozen=True, slots=True)
class DatasetCandidate:
    item_type: Literal["section_pattern", "full_site_spec"]
    source_record_id: UUID
    campaign_id: UUID
    website_id: UUID
    page_id: UUID | None
    source_domain: str
    category: str
    language: str
    confidence: float
    schema_version: int
    analyzer_version: str
    content: JsonValue


class DatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: object) -> None:
        self._session.add(entity)

    def add_all(self, entities: list[object]) -> None:
        self._session.add_all(entities)

    async def flush(self) -> None:
        await self._session.flush()

    async def delete(self, entity: Dataset | DatasetVersion) -> None:
        await self._session.delete(entity)

    async def owned_project(self, project_id: UUID, owner_id: UUID) -> Project | None:
        return cast(
            Project | None,
            await self._session.scalar(
                select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
            ),
        )

    async def dataset(
        self, project_id: UUID, dataset_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> Dataset | None:
        statement = (
            select(Dataset)
            .join(Project, Project.id == Dataset.project_id)
            .where(
                Dataset.id == dataset_id,
                Dataset.project_id == project_id,
                Project.owner_id == owner_id,
            )
        )
        if for_update:
            statement = statement.with_for_update(of=Dataset)
        return cast(Dataset | None, await self._session.scalar(statement))

    async def name_exists(
        self, project_id: UUID, name: str, *, exclude_id: UUID | None = None
    ) -> bool:
        statement = select(Dataset.id).where(Dataset.project_id == project_id, Dataset.name == name)
        if exclude_id is not None:
            statement = statement.where(Dataset.id != exclude_id)
        return await self._session.scalar(statement) is not None

    async def dataset_page(
        self, project_id: UUID, owner_id: UUID, *, limit: int, offset: int
    ) -> Page[Dataset]:
        owned = (
            select(Dataset)
            .join(Project, Project.id == Dataset.project_id)
            .where(Dataset.project_id == project_id, Project.owner_id == owner_id)
        )
        items = tuple(
            (
                await self._session.scalars(
                    apply_pagination(
                        owned.order_by(Dataset.updated_at.desc(), Dataset.id),
                        limit=limit,
                        offset=offset,
                    )
                )
            ).all()
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(owned.subquery())) or 0
        )
        return Page(items=items, total=total, limit=limit, offset=offset)

    async def version(
        self,
        project_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> DatasetVersion | None:
        statement = (
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .join(Project, Project.id == Dataset.project_id)
            .where(
                DatasetVersion.id == version_id,
                DatasetVersion.dataset_id == dataset_id,
                Dataset.project_id == project_id,
                Project.owner_id == owner_id,
            )
        )
        if for_update:
            statement = statement.with_for_update(of=DatasetVersion)
        return cast(DatasetVersion | None, await self._session.scalar(statement))

    async def next_version_number(self, dataset_id: UUID) -> int:
        current = await self._session.scalar(
            select(func.max(DatasetVersion.version_number)).where(
                DatasetVersion.dataset_id == dataset_id
            )
        )
        return int(current or 0) + 1

    async def version_page(
        self, dataset_id: UUID, *, limit: int, offset: int
    ) -> Page[DatasetVersion]:
        statement = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)
        items = tuple(
            (
                await self._session.scalars(
                    apply_pagination(
                        statement.order_by(DatasetVersion.version_number.desc()),
                        limit=limit,
                        offset=offset,
                    )
                )
            ).all()
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        return Page(items=items, total=total, limit=limit, offset=offset)

    async def has_sealed_version(self, dataset_id: UUID) -> bool:
        return (
            await self._session.scalar(
                select(DatasetVersion.id)
                .where(DatasetVersion.dataset_id == dataset_id, DatasetVersion.status == "sealed")
                .limit(1)
            )
            is not None
        )

    async def clear_items(self, version_id: UUID) -> None:
        await self._session.execute(
            delete(DatasetItem).where(DatasetItem.dataset_version_id == version_id)
        )

    async def candidates(
        self, project_id: UUID, config: SelectionPolicy
    ) -> tuple[DatasetCandidate, ...]:
        result: list[DatasetCandidate] = []
        item_types = config.item_types
        campaigns = config.source_campaign_filters
        categories = config.category_filters
        languages = config.language_filters
        provenance = config.provenance_requirements
        confidence = config.minimum_confidence
        approved = config.require_approved
        if "section_pattern" in item_types:
            section_statement = (
                select(SectionPattern, ScanTarget.source_domain)
                .join(ScanTarget, ScanTarget.id == SectionPattern.source_website_id)
                .where(
                    SectionPattern.project_id == project_id,
                    SectionPattern.confidence >= confidence,
                    SectionPattern.provenance_state.in_(provenance),
                    SectionPattern.duplicate_of_id.is_(None),
                    SectionPattern.retrieval_removed_at.is_(None),
                    SectionPattern.legally_suppressed_at.is_(None),
                )
            )
            if approved:
                section_statement = section_statement.where(
                    SectionPattern.approval_state == "approved"
                )
            if campaigns:
                section_statement = section_statement.where(
                    SectionPattern.campaign_id.in_(campaigns)
                )
            if categories:
                section_statement = section_statement.where(SectionPattern.category.in_(categories))
            if languages:
                section_statement = section_statement.where(SectionPattern.language.in_(languages))
            for pattern, domain in (
                await self._session.execute(section_statement.order_by(SectionPattern.id))
            ).all():
                result.append(
                    DatasetCandidate(
                        "section_pattern",
                        pattern.id,
                        pattern.campaign_id,
                        pattern.source_website_id,
                        pattern.source_page_id,
                        domain,
                        pattern.category,
                        pattern.language,
                        pattern.confidence,
                        pattern.schema_version,
                        pattern.analyzer_version,
                        {
                            "pattern": pattern.pattern_json,
                            "retrieval_document": pattern.retrieval_document,
                        },
                    )
                )
        if "full_site_spec" in item_types:
            website_statement = (
                select(WebsiteProfile, ScanTarget.source_domain)
                .join(ScanTarget, ScanTarget.id == WebsiteProfile.source_website_id)
                .where(
                    WebsiteProfile.project_id == project_id,
                    WebsiteProfile.is_current.is_(True),
                    WebsiteProfile.confidence >= confidence,
                    WebsiteProfile.provenance_state.in_(provenance),
                )
            )
            if approved:
                website_statement = website_statement.where(
                    WebsiteProfile.approval_state == "approved"
                )
            if campaigns:
                website_statement = website_statement.where(
                    WebsiteProfile.campaign_id.in_(campaigns)
                )
            if categories:
                website_statement = website_statement.where(WebsiteProfile.category.in_(categories))
            if languages:
                website_statement = website_statement.where(WebsiteProfile.language.in_(languages))
            for profile, domain in (
                await self._session.execute(website_statement.order_by(WebsiteProfile.id))
            ).all():
                result.append(
                    DatasetCandidate(
                        "full_site_spec",
                        profile.id,
                        profile.campaign_id,
                        profile.source_website_id,
                        None,
                        domain,
                        profile.category,
                        profile.language,
                        profile.confidence,
                        profile.schema_version,
                        profile.analyzer_version,
                        {"site_profile": profile.profile_json},
                    )
                )
        return tuple(sorted(result, key=lambda item: (item.item_type, str(item.source_record_id))))

    async def item_page(self, version_id: UUID, *, limit: int, offset: int) -> Page[DatasetItem]:
        statement = select(DatasetItem).where(DatasetItem.dataset_version_id == version_id)
        items = tuple(
            (
                await self._session.scalars(
                    apply_pagination(
                        statement.order_by(
                            DatasetItem.split, DatasetItem.source_domain, DatasetItem.id
                        ),
                        limit=limit,
                        offset=offset,
                    )
                )
            ).all()
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        return Page(items=items, total=total, limit=limit, offset=offset)

    async def latest_quality_report(self, version_id: UUID) -> DatasetQualityReport | None:
        return cast(
            DatasetQualityReport | None,
            await self._session.scalar(
                select(DatasetQualityReport)
                .where(DatasetQualityReport.dataset_version_id == version_id)
                .order_by(DatasetQualityReport.created_at.desc(), DatasetQualityReport.id.desc())
                .limit(1)
            ),
        )
