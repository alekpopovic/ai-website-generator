"""Owner-scoped SQLAlchemy repositories for scan campaign projections."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from platform_api.persistence.models import (
    CrawlPage,
    PageScan,
    Project,
    ScanCampaign,
    ScanFailure,
    ScanTarget,
)
from platform_api.persistence.pagination import Page, apply_pagination


class ScanCampaignRepository:
    """Scan persistence whose every read is constrained by project owner."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: ScanCampaign | ScanTarget) -> None:
        self._session.add(entity)

    async def delete(self, entity: ScanCampaign | ScanTarget) -> None:
        await self._session.delete(entity)

    async def flush(self) -> None:
        await self._session.flush()

    async def owned_project(self, project_id: UUID, owner_id: UUID) -> Project | None:
        return cast(
            Project | None,
            await self._session.scalar(
                select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
            ),
        )

    async def campaign_owned(
        self,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScanCampaign | None:
        statement = (
            select(ScanCampaign)
            .join(Project, ScanCampaign.project_id == Project.id)
            .where(
                ScanCampaign.id == campaign_id,
                ScanCampaign.project_id == project_id,
                Project.owner_id == owner_id,
            )
        )
        if for_update:
            statement = statement.with_for_update(of=ScanCampaign)
        return cast(ScanCampaign | None, await self._session.scalar(statement))

    async def campaign_name_exists(
        self, project_id: UUID, name: str, *, exclude_id: UUID | None = None
    ) -> bool:
        statement = select(ScanCampaign.id).where(
            ScanCampaign.project_id == project_id, ScanCampaign.name == name
        )
        if exclude_id is not None:
            statement = statement.where(ScanCampaign.id != exclude_id)
        return await self._session.scalar(statement) is not None

    async def campaign_page(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
        search: str | None,
        status: str | None,
        sort_by: str,
        sort_order: str,
    ) -> Page[ScanCampaign]:
        filters = [ScanCampaign.project_id == project_id, Project.owner_id == owner_id]
        if search:
            filters.append(ScanCampaign.name.icontains(search.strip(), autoescape=True))
        if status:
            filters.append(ScanCampaign.status == status)
        statement: Select[tuple[ScanCampaign]] = (
            select(ScanCampaign)
            .join(Project, ScanCampaign.project_id == Project.id)
            .where(*filters)
        )
        sort_column = {
            "created_at": ScanCampaign.created_at,
            "name": ScanCampaign.name,
            "updated_at": ScanCampaign.updated_at,
        }[sort_by]
        ordering = sort_column.asc() if sort_order == "asc" else sort_column.desc()
        statement = apply_pagination(
            statement.order_by(ordering, ScanCampaign.id.asc()), limit=limit, offset=offset
        )
        items = tuple((await self._session.scalars(statement)).all())
        total = await self._session.scalar(
            select(func.count())
            .select_from(ScanCampaign)
            .join(Project, ScanCampaign.project_id == Project.id)
            .where(*filters)
        )
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def target_owned(
        self,
        target_id: UUID,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScanTarget | None:
        statement = (
            select(ScanTarget)
            .join(ScanCampaign, ScanTarget.campaign_id == ScanCampaign.id)
            .join(Project, ScanCampaign.project_id == Project.id)
            .where(
                ScanTarget.id == target_id,
                ScanTarget.campaign_id == campaign_id,
                ScanCampaign.project_id == project_id,
                Project.owner_id == owner_id,
            )
        )
        if for_update:
            statement = statement.with_for_update(of=ScanTarget)
        return cast(ScanTarget | None, await self._session.scalar(statement))

    async def target_url_exists(self, campaign_id: UUID, normalized_url: str) -> bool:
        return (
            await self._session.scalar(
                select(ScanTarget.id).where(
                    ScanTarget.campaign_id == campaign_id,
                    ScanTarget.normalized_url == normalized_url,
                )
            )
            is not None
        )

    async def target_page(
        self,
        *,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
        status: str | None,
    ) -> Page[ScanTarget]:
        filters = [
            ScanTarget.campaign_id == campaign_id,
            ScanCampaign.project_id == project_id,
            Project.owner_id == owner_id,
        ]
        if status:
            filters.append(ScanTarget.status == status)
        base = (
            select(ScanTarget)
            .join(ScanCampaign, ScanTarget.campaign_id == ScanCampaign.id)
            .join(Project, ScanCampaign.project_id == Project.id)
            .where(*filters)
        )
        statement = apply_pagination(
            base.order_by(ScanTarget.created_at.asc(), ScanTarget.id.asc()),
            limit=limit,
            offset=offset,
        )
        items = tuple((await self._session.scalars(statement)).all())
        total = await self._session.scalar(
            select(func.count())
            .select_from(ScanTarget)
            .join(ScanCampaign, ScanTarget.campaign_id == ScanCampaign.id)
            .join(Project, ScanCampaign.project_id == Project.id)
            .where(*filters)
        )
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def crawl_page_page(
        self,
        *,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
        status: str | None,
    ) -> Page[CrawlPage]:
        filters = [
            CrawlPage.campaign_id == campaign_id,
            ScanCampaign.project_id == project_id,
            Project.owner_id == owner_id,
        ]
        if status:
            filters.append(CrawlPage.status == status)
        base = (
            select(CrawlPage)
            .join(ScanCampaign, CrawlPage.campaign_id == ScanCampaign.id)
            .join(Project, ScanCampaign.project_id == Project.id)
            .options(selectinload(CrawlPage.page_scans))
            .where(*filters)
        )
        statement = apply_pagination(
            base.order_by(CrawlPage.discovered_at.asc(), CrawlPage.id.asc()),
            limit=limit,
            offset=offset,
        )
        items = tuple((await self._session.scalars(statement)).all())
        total = await self._session.scalar(
            select(func.count())
            .select_from(CrawlPage)
            .join(ScanCampaign, CrawlPage.campaign_id == ScanCampaign.id)
            .join(Project, ScanCampaign.project_id == Project.id)
            .where(*filters)
        )
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def failure_page(
        self,
        *,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
        stage: str | None,
        retryable: bool | None,
        unresolved_only: bool,
    ) -> Page[ScanFailure]:
        filters = [
            ScanFailure.campaign_id == campaign_id,
            ScanCampaign.project_id == project_id,
            Project.owner_id == owner_id,
        ]
        if stage:
            filters.append(ScanFailure.stage == stage)
        if retryable is not None:
            filters.append(ScanFailure.retryable.is_(retryable))
        if unresolved_only:
            filters.append(ScanFailure.resolved_at.is_(None))
        base = (
            select(ScanFailure)
            .join(ScanCampaign, ScanFailure.campaign_id == ScanCampaign.id)
            .join(Project, ScanCampaign.project_id == Project.id)
            .where(*filters)
        )
        statement = apply_pagination(
            base.order_by(ScanFailure.created_at.desc(), ScanFailure.id.asc()),
            limit=limit,
            offset=offset,
        )
        items = tuple((await self._session.scalars(statement)).all())
        total = await self._session.scalar(
            select(func.count())
            .select_from(ScanFailure)
            .join(ScanCampaign, ScanFailure.campaign_id == ScanCampaign.id)
            .join(Project, ScanCampaign.project_id == Project.id)
            .where(*filters)
        )
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def summary_counts(
        self, campaign_id: UUID
    ) -> tuple[dict[str, int], dict[str, int], dict[str, int], int, int, int]:
        targets = await self._status_counts(ScanTarget, campaign_id)
        pages = await self._status_counts(CrawlPage, campaign_id)
        page_scans = await self._status_counts(PageScan, campaign_id)
        failure_count = await self._session.scalar(
            select(func.count())
            .select_from(ScanFailure)
            .where(ScanFailure.campaign_id == campaign_id)
        )
        retryable = await self._session.scalar(
            select(func.count())
            .select_from(ScanFailure)
            .where(ScanFailure.campaign_id == campaign_id, ScanFailure.retryable.is_(True))
        )
        unresolved = await self._session.scalar(
            select(func.count())
            .select_from(ScanFailure)
            .where(ScanFailure.campaign_id == campaign_id, ScanFailure.resolved_at.is_(None))
        )
        return (
            targets,
            pages,
            page_scans,
            failure_count or 0,
            retryable or 0,
            unresolved or 0,
        )

    async def _status_counts(
        self, model: type[ScanTarget] | type[CrawlPage] | type[PageScan], campaign_id: UUID
    ) -> dict[str, int]:
        rows = await self._session.execute(
            select(model.status, func.count())
            .where(model.campaign_id == campaign_id)
            .group_by(model.status)
        )
        return {str(status): int(count) for status, count in rows.all()}

    async def has_retryable_failures(self, campaign_id: UUID) -> bool:
        return (
            await self._session.scalar(
                select(ScanFailure.id).where(
                    ScanFailure.campaign_id == campaign_id,
                    ScanFailure.retryable.is_(True),
                    ScanFailure.resolved_at.is_(None),
                )
            )
            is not None
        )
