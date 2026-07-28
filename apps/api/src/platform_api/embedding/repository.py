"""Owner-scoped embedding run persistence."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.persistence.models import EmbeddingIndexFailure, EmbeddingRun, Project
from platform_api.persistence.pagination import Page


class EmbeddingRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, run: EmbeddingRun) -> None:
        self._session.add(run)

    async def flush(self) -> None:
        await self._session.flush()

    async def owns_project(
        self, project_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> bool:
        statement = select(Project.id).where(Project.id == project_id, Project.owner_id == owner_id)
        if for_update:
            statement = statement.with_for_update()
        value = await self._session.scalar(statement)
        return value is not None

    async def by_idempotency(self, project_id: UUID, key: str) -> EmbeddingRun | None:
        return cast(
            EmbeddingRun | None,
            await self._session.scalar(
                select(EmbeddingRun).where(
                    EmbeddingRun.project_id == project_id,
                    EmbeddingRun.idempotency_key == key,
                )
            ),
        )

    async def owned(self, run_id: UUID, project_id: UUID, owner_id: UUID) -> EmbeddingRun | None:
        return cast(
            EmbeddingRun | None,
            await self._session.scalar(
                select(EmbeddingRun)
                .join(Project, Project.id == EmbeddingRun.project_id)
                .where(
                    EmbeddingRun.id == run_id,
                    EmbeddingRun.project_id == project_id,
                    Project.owner_id == owner_id,
                )
            ),
        )

    async def page(
        self, *, project_id: UUID, owner_id: UUID, limit: int, offset: int
    ) -> Page[EmbeddingRun] | None:
        if not await self.owns_project(project_id, owner_id):
            return None
        total = int(
            await self._session.scalar(
                select(func.count(EmbeddingRun.id)).where(EmbeddingRun.project_id == project_id)
            )
            or 0
        )
        items = tuple(
            (
                await self._session.scalars(
                    select(EmbeddingRun)
                    .where(EmbeddingRun.project_id == project_id)
                    .order_by(EmbeddingRun.created_at.desc(), EmbeddingRun.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        return Page(items, total, limit, offset)

    async def failure_page(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
    ) -> Page[EmbeddingIndexFailure] | None:
        if await self.owned(run_id, project_id, owner_id) is None:
            return None
        total = int(
            await self._session.scalar(
                select(func.count(EmbeddingIndexFailure.id)).where(
                    EmbeddingIndexFailure.embedding_run_id == run_id
                )
            )
            or 0
        )
        items = tuple(
            (
                await self._session.scalars(
                    select(EmbeddingIndexFailure)
                    .where(EmbeddingIndexFailure.embedding_run_id == run_id)
                    .order_by(
                        EmbeddingIndexFailure.created_at.desc(),
                        EmbeddingIndexFailure.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        return Page(items, total, limit, offset)
