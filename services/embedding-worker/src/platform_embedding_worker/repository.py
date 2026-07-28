"""PostgreSQL authority for embedding eligibility, idempotency, and progress."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from platform_api.database import DatabaseManager
from platform_api.persistence.models import (
    EmbeddingIndexFailure,
    EmbeddingRun,
    ScanTarget,
    SectionPattern,
    SectionPatternEmbedding,
)
from platform_clients.vector_store.models import CollectionIdentity
from platform_schemas import SectionPattern as SectionPatternSchema
from platform_schemas import StyleTag
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from platform_embedding_worker.models import (
    EmbeddingRunRecord,
    PatternForEmbedding,
    RemovalRecord,
)


class SqlAlchemyEmbeddingRepository:
    def __init__(self, database: DatabaseManager) -> None:
        self._database = database

    async def claim_run(self, run_id: UUID) -> EmbeddingRunRecord:
        async with self._database.transaction() as session:
            run = await session.scalar(
                select(EmbeddingRun).where(EmbeddingRun.id == run_id).with_for_update()
            )
            if run is None:
                raise LookupError("embedding run was not found")
            if run.status not in {"queued", "running", "failed", "succeeded"}:
                raise RuntimeError("embedding run cannot be started from its current state")
            previous = run.status
            if run.status != "succeeded":
                run.status = "running"
                run.started_at = run.started_at or datetime.now(UTC)
                run.completed_at = None
                run.failure_code = None
                if previous == "failed":
                    run.processed_patterns = 0
                    run.indexed_patterns = 0
                    run.deleted_patterns = 0
                    run.failed_patterns = 0
            await session.flush()
            return _run_record(run)

    async def configure_run(
        self, run_id: UUID, identity: CollectionIdentity, dimensions: int, total: int
    ) -> None:
        async with self._database.transaction() as session:
            run = await _required_run(session, run_id)
            run.embedding_provider = identity.embedding_provider
            run.embedding_model = identity.embedding_model
            run.embedding_model_digest = identity.embedding_model_digest
            run.serialization_schema_version = identity.serialization_schema_version
            run.vector_name = identity.vector_name
            run.physical_collection = identity.physical_name(run.collection_alias)
            run.dimensions = dimensions
            run.total_patterns = total

    async def eligible_count(self, run: EmbeddingRunRecord) -> int:
        async with self._database.session() as session:
            value = await session.scalar(
                select(func.count(SectionPattern.id)).where(
                    SectionPattern.project_id == run.project_id,
                    *_eligible_conditions(),
                )
            )
        return int(value or 0)

    async def pattern_batch(
        self,
        run: EmbeddingRunRecord,
        identity: CollectionIdentity,
        *,
        after_id: UUID | None,
        limit: int,
    ) -> tuple[PatternForEmbedding, ...]:
        collection = identity.physical_name(run.collection_alias)
        join = and_(
            SectionPatternEmbedding.section_pattern_id == SectionPattern.id,
            SectionPatternEmbedding.physical_collection == collection,
        )
        statement = (
            select(SectionPattern, ScanTarget, SectionPatternEmbedding)
            .join(ScanTarget, ScanTarget.id == SectionPattern.source_website_id)
            .outerjoin(SectionPatternEmbedding, join)
            .where(SectionPattern.project_id == run.project_id, *_eligible_conditions())
            .order_by(SectionPattern.id.asc())
            .limit(limit)
        )
        if after_id is not None:
            statement = statement.where(SectionPattern.id > after_id)
        async with self._database.session() as session:
            rows = (await session.execute(statement)).all()
        return tuple(
            _pattern_record(pattern, target, embedding) for pattern, target, embedding in rows
        )

    async def removal_batch(self, project_id: UUID, *, limit: int) -> tuple[RemovalRecord, ...]:
        now = datetime.now(UTC)
        async with self._database.transaction() as session:
            statement = (
                select(SectionPatternEmbedding, SectionPattern)
                .join(
                    SectionPattern, SectionPattern.id == SectionPatternEmbedding.section_pattern_id
                )
                .where(
                    SectionPatternEmbedding.project_id == project_id,
                    SectionPatternEmbedding.status.in_(("indexed", "failed", "deleting")),
                    or_(
                        SectionPattern.approval_state != "approved",
                        SectionPattern.provenance_state != "authorized",
                        SectionPattern.retrieval_removed_at.is_not(None),
                        SectionPattern.legally_suppressed_at.is_not(None),
                        SectionPattern.retrieval_expires_at <= now,
                    ),
                )
                .order_by(SectionPatternEmbedding.id.asc())
                .limit(limit)
                .with_for_update(of=SectionPatternEmbedding, skip_locked=True)
            )
            rows = (await session.execute(statement)).all()
            records: list[RemovalRecord] = []
            for embedding, _ in rows:
                embedding.status = "deleting"
                records.append(
                    RemovalRecord(
                        embedding.section_pattern_id,
                        CollectionIdentity(
                            embedding_provider=embedding.embedding_provider,
                            embedding_model=embedding.embedding_model,
                            embedding_model_digest=embedding.embedding_model_digest,
                            serialization_schema_version=embedding.serialization_schema_version,
                            vector_name=embedding.vector_name,
                        ),
                        embedding.physical_collection,
                    )
                )
            return tuple(records)

    async def mark_indexing(
        self,
        run_id: UUID,
        patterns: tuple[tuple[UUID, str], ...],
        identity: CollectionIdentity,
    ) -> None:
        run = await self._read_run(run_id)
        collection = identity.physical_name(run.collection_alias)
        async with self._database.transaction() as session:
            for pattern_id, document_sha256 in patterns:
                state = await session.scalar(
                    select(SectionPatternEmbedding)
                    .where(
                        SectionPatternEmbedding.section_pattern_id == pattern_id,
                        SectionPatternEmbedding.physical_collection == collection,
                    )
                    .with_for_update()
                )
                if state is None:
                    state = SectionPatternEmbedding(
                        id=uuid4(),
                        project_id=run.project_id,
                        section_pattern_id=pattern_id,
                        embedding_run_id=run_id,
                        physical_collection=collection,
                        embedding_provider=identity.embedding_provider,
                        embedding_model=identity.embedding_model,
                        embedding_model_digest=identity.embedding_model_digest,
                        serialization_schema_version=identity.serialization_schema_version,
                        vector_name=identity.vector_name,
                        document_sha256=document_sha256,
                        status="indexing",
                        attempts=1,
                    )
                    session.add(state)
                else:
                    state.embedding_run_id = run_id
                    state.document_sha256 = document_sha256
                    state.status = "indexing"
                    state.attempts += 1
                    state.error_code = None
                    state.deleted_at = None

    async def mark_indexed(
        self,
        run_id: UUID,
        patterns: tuple[tuple[UUID, str], ...],
        identity: CollectionIdentity,
    ) -> None:
        run = await self._read_run(run_id)
        collection = identity.physical_name(run.collection_alias)
        identifiers = tuple(pattern_id for pattern_id, _ in patterns)
        now = datetime.now(UTC)
        async with self._database.transaction() as session:
            await session.execute(
                update(SectionPatternEmbedding)
                .where(
                    SectionPatternEmbedding.section_pattern_id.in_(identifiers),
                    SectionPatternEmbedding.physical_collection == collection,
                )
                .values(
                    status="indexed",
                    indexed_at=now,
                    error_code=None,
                    updated_at=now,
                    version=SectionPatternEmbedding.version + 1,
                )
            )

    async def mark_deleted(self, records: tuple[RemovalRecord, ...]) -> None:
        now = datetime.now(UTC)
        async with self._database.transaction() as session:
            for record in records:
                await session.execute(
                    update(SectionPatternEmbedding)
                    .where(
                        SectionPatternEmbedding.section_pattern_id == record.section_pattern_id,
                        SectionPatternEmbedding.physical_collection == record.physical_collection,
                    )
                    .values(
                        status="deleted",
                        deleted_at=now,
                        error_code=None,
                        updated_at=now,
                        version=SectionPatternEmbedding.version + 1,
                    )
                )

    async def record_batch_failure(
        self, run_id: UUID, pattern_ids: tuple[UUID, ...], error_code: str
    ) -> None:
        async with self._database.transaction() as session:
            run = await _required_run(session, run_id)
            states = (
                await session.scalars(
                    select(SectionPatternEmbedding).where(
                        SectionPatternEmbedding.embedding_run_id == run_id,
                        SectionPatternEmbedding.section_pattern_id.in_(pattern_ids),
                    )
                )
            ).all()
            attempts = {state.section_pattern_id: state.attempts for state in states}
            for state in states:
                state.status = "failed"
                state.error_code = error_code
            for pattern_id in pattern_ids:
                session.add(
                    EmbeddingIndexFailure(
                        project_id=run.project_id,
                        embedding_run_id=run_id,
                        section_pattern_id=pattern_id,
                        error_code=error_code,
                        attempt=max(1, attempts.get(pattern_id, 1)),
                        retryable=True,
                    )
                )
            run.failed_patterns += len(pattern_ids)

    async def advance(
        self,
        run_id: UUID,
        *,
        processed: int = 0,
        indexed: int = 0,
        deleted: int = 0,
    ) -> None:
        now = datetime.now(UTC)
        async with self._database.transaction() as session:
            await session.execute(
                update(EmbeddingRun)
                .where(EmbeddingRun.id == run_id)
                .values(
                    processed_patterns=EmbeddingRun.processed_patterns + processed,
                    indexed_patterns=EmbeddingRun.indexed_patterns + indexed,
                    deleted_patterns=EmbeddingRun.deleted_patterns + deleted,
                    updated_at=now,
                    version=EmbeddingRun.version + 1,
                )
            )

    async def complete_run(self, run_id: UUID, *, alias_switched: bool) -> None:
        async with self._database.transaction() as session:
            run = await _required_run(session, run_id)
            run.status = "succeeded"
            run.completed_at = datetime.now(UTC)
            if alias_switched:
                run.alias_switched_at = run.completed_at

    async def fail_run(self, run_id: UUID, error_code: str) -> None:
        await self._finish(run_id, "failed", error_code)

    async def cancel_run(self, run_id: UUID) -> None:
        await self._finish(run_id, "cancelled", None)

    async def _finish(self, run_id: UUID, status: str, error_code: str | None) -> None:
        async with self._database.transaction() as session:
            run = await _required_run(session, run_id)
            run.status = status
            run.failure_code = error_code
            run.completed_at = datetime.now(UTC)

    async def _read_run(self, run_id: UUID) -> EmbeddingRunRecord:
        async with self._database.session() as session:
            run = await session.get(EmbeddingRun, run_id)
        if run is None:
            raise LookupError("embedding run was not found")
        return _run_record(run)


def _eligible_conditions() -> tuple[ColumnElement[bool], ...]:
    now = datetime.now(UTC)
    return (
        SectionPattern.approval_state == "approved",
        SectionPattern.provenance_state == "authorized",
        SectionPattern.retrieval_removed_at.is_(None),
        SectionPattern.legally_suppressed_at.is_(None),
        or_(
            SectionPattern.retrieval_expires_at.is_(None), SectionPattern.retrieval_expires_at > now
        ),
    )


def _run_record(run: EmbeddingRun) -> EmbeddingRunRecord:
    return EmbeddingRunRecord(
        run.id,
        run.project_id,
        run.kind,
        run.status,
        run.batch_size,
        run.promote_alias,
        run.collection_alias,
        run.serialization_schema_version,
        run.vector_name,
    )


def _pattern_record(
    pattern: SectionPattern,
    target: ScanTarget,
    embedding: SectionPatternEmbedding | None,
) -> PatternForEmbedding:
    tags = pattern.style_tags
    if not isinstance(tags, list) or not all(isinstance(value, str) for value in tags):
        raise ValueError("stored section pattern style tags are invalid")
    return PatternForEmbedding(
        id=pattern.id,
        project_id=pattern.project_id,
        source_website_id=pattern.source_website_id,
        source_page_id=pattern.source_page_id,
        source_domain=target.source_domain,
        category=pattern.category,
        page_type=pattern.category,
        section_type=pattern.section_type,
        layout=pattern.layout,
        style_tags=tuple(StyleTag(cast(str, value)) for value in tags),
        language=pattern.language,
        confidence=pattern.confidence,
        pattern=SectionPatternSchema.model_validate(pattern.pattern_json),
        retrieval_document=pattern.retrieval_document,
        retrieval_expires_at=pattern.retrieval_expires_at,
        retrieval_removed_at=pattern.retrieval_removed_at,
        legally_suppressed_at=pattern.legally_suppressed_at,
        approval_state=pattern.approval_state,
        provenance_state=pattern.provenance_state,
        current_document_sha256=embedding.document_sha256 if embedding else None,
        current_status=embedding.status if embedding else None,
    )


async def _required_run(session: AsyncSession, run_id: UUID) -> EmbeddingRun:
    run = await session.scalar(
        select(EmbeddingRun).where(EmbeddingRun.id == run_id).with_for_update()
    )
    if run is None:
        raise LookupError("embedding run was not found")
    return run
