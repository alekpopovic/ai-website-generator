"""Owner-scoped, batch-oriented persistence for target imports."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.persistence.models import (
    Project,
    ScanCampaign,
    ScanTarget,
    ScanTargetImport,
    ScanTargetImportRow,
)


class ScanTargetImportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: ScanTarget | ScanTargetImport | ScanTargetImportRow) -> None:
        self._session.add(entity)

    def add_all(self, entities: Sequence[ScanTarget | ScanTargetImportRow]) -> None:
        self._session.add_all(entities)

    async def flush(self) -> None:
        await self._session.flush()

    async def campaign_owned_for_update(
        self, campaign_id: UUID, project_id: UUID, owner_id: UUID
    ) -> ScanCampaign | None:
        return cast(
            ScanCampaign | None,
            await self._session.scalar(
                select(ScanCampaign)
                .join(Project, ScanCampaign.project_id == Project.id)
                .where(
                    ScanCampaign.id == campaign_id,
                    ScanCampaign.project_id == project_id,
                    Project.owner_id == owner_id,
                )
                .with_for_update(of=ScanCampaign)
            ),
        )

    async def import_owned(
        self, import_id: UUID, campaign_id: UUID, project_id: UUID, owner_id: UUID
    ) -> ScanTargetImport | None:
        return cast(
            ScanTargetImport | None,
            await self._session.scalar(
                select(ScanTargetImport)
                .join(ScanCampaign, ScanTargetImport.campaign_id == ScanCampaign.id)
                .join(Project, ScanCampaign.project_id == Project.id)
                .where(
                    ScanTargetImport.id == import_id,
                    ScanTargetImport.campaign_id == campaign_id,
                    ScanCampaign.project_id == project_id,
                    Project.owner_id == owner_id,
                )
            ),
        )

    async def existing_domains(self, campaign_id: UUID) -> set[str]:
        return set(
            (
                await self._session.scalars(
                    select(ScanTarget.source_domain).where(ScanTarget.campaign_id == campaign_id)
                )
            ).all()
        )

    async def accepted_rows(
        self, import_id: UUID, *, after_row: int, limit: int
    ) -> tuple[ScanTargetImportRow, ...]:
        return tuple(
            (
                await self._session.scalars(
                    select(ScanTargetImportRow)
                    .where(
                        ScanTargetImportRow.import_id == import_id,
                        ScanTargetImportRow.outcome == "accepted",
                        ScanTargetImportRow.target_id.is_(None),
                        ScanTargetImportRow.row_number > after_row,
                    )
                    .order_by(ScanTargetImportRow.row_number)
                    .limit(limit)
                )
            ).all()
        )

    async def error_rows(self, import_id: UUID) -> AsyncIterator[ScanTargetImportRow]:
        stream = await self._session.stream_scalars(
            select(ScanTargetImportRow)
            .where(
                ScanTargetImportRow.import_id == import_id,
                ScanTargetImportRow.outcome != "accepted",
            )
            .order_by(ScanTargetImportRow.row_number)
            .execution_options(yield_per=500)
        )
        async for row in stream:
            yield row
