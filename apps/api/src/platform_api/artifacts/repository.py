"""Owner-scoped typed scan-artifact queries."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.persistence.models import CrawlPage, Project, ScanArtifact, ScanCampaign


class ScanArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def owned(
        self,
        artifact_id: UUID,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScanArtifact | None:
        statement = (
            select(ScanArtifact)
            .join(ScanCampaign, ScanArtifact.campaign_id == ScanCampaign.id)
            .join(Project, ScanArtifact.project_id == Project.id)
            .where(
                ScanArtifact.id == artifact_id,
                ScanArtifact.campaign_id == campaign_id,
                ScanArtifact.project_id == project_id,
                Project.owner_id == owner_id,
            )
        )
        if for_update:
            statement = statement.with_for_update(of=ScanArtifact)
        return cast(ScanArtifact | None, await self._session.scalar(statement))

    async def list_for_page(
        self,
        page_id: UUID,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
    ) -> tuple[ScanArtifact, ...] | None:
        page_exists = await self._session.scalar(
            select(CrawlPage.id)
            .join(ScanCampaign, CrawlPage.campaign_id == ScanCampaign.id)
            .join(Project, ScanCampaign.project_id == Project.id)
            .where(
                CrawlPage.id == page_id,
                CrawlPage.campaign_id == campaign_id,
                ScanCampaign.project_id == project_id,
                Project.owner_id == owner_id,
            )
        )
        if page_exists is None:
            return None
        return tuple(
            (
                await self._session.scalars(
                    select(ScanArtifact)
                    .where(ScanArtifact.crawl_page_id == page_id)
                    .order_by(
                        ScanArtifact.viewport.asc().nullsfirst(),
                        ScanArtifact.artifact_type.asc(),
                        ScanArtifact.id.asc(),
                    )
                )
            ).all()
        )

    async def flush(self) -> None:
        await self._session.flush()
