"""Idempotent source-safe embedding and Qdrant indexing orchestration."""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from platform_api.analysis.patterns import retrieval_document
from platform_clients.llm.models import EmbeddingRequest, ModelRole
from platform_clients.llm.protocols import LLMGateway
from platform_clients.vector_store.models import CollectionIdentity, VectorPoint
from platform_clients.vector_store.protocols import VectorStore

from platform_embedding_worker.models import (
    EmbeddingRunRecord,
    IndexOutcome,
    PatternForEmbedding,
    RemovalRecord,
)

ProgressCallback = Callable[[str, int], Awaitable[None]]
_DIMENSION_PROBE = "abstract layout pattern with balanced spacing and clear hierarchy"


class EmbeddingRepository(Protocol):
    async def claim_run(self, run_id: UUID) -> EmbeddingRunRecord: ...

    async def configure_run(
        self, run_id: UUID, identity: CollectionIdentity, dimensions: int, total: int
    ) -> None: ...

    async def eligible_count(self, run: EmbeddingRunRecord) -> int: ...

    async def pattern_batch(
        self,
        run: EmbeddingRunRecord,
        identity: CollectionIdentity,
        *,
        after_id: UUID | None,
        limit: int,
    ) -> tuple[PatternForEmbedding, ...]: ...

    async def removal_batch(self, project_id: UUID, *, limit: int) -> tuple[RemovalRecord, ...]: ...

    async def mark_indexing(
        self,
        run_id: UUID,
        patterns: tuple[tuple[UUID, str], ...],
        identity: CollectionIdentity,
    ) -> None: ...

    async def mark_indexed(
        self,
        run_id: UUID,
        patterns: tuple[tuple[UUID, str], ...],
        identity: CollectionIdentity,
    ) -> None: ...

    async def mark_deleted(self, records: tuple[RemovalRecord, ...]) -> None: ...

    async def record_batch_failure(
        self, run_id: UUID, pattern_ids: tuple[UUID, ...], error_code: str
    ) -> None: ...

    async def advance(
        self, run_id: UUID, *, processed: int = 0, indexed: int = 0, deleted: int = 0
    ) -> None: ...

    async def complete_run(self, run_id: UUID, *, alias_switched: bool) -> None: ...

    async def fail_run(self, run_id: UUID, error_code: str) -> None: ...

    async def cancel_run(self, run_id: UUID) -> None: ...


class EmbeddingIndexer:
    def __init__(
        self, repository: EmbeddingRepository, embeddings: LLMGateway, vector_store: VectorStore
    ) -> None:
        self._repository = repository
        self._embeddings = embeddings
        self._vector_store = vector_store

    async def run(self, run_id: UUID, progress: ProgressCallback) -> IndexOutcome:
        run = await self._repository.claim_run(run_id)
        if run.status == "succeeded":
            return IndexOutcome(run_id, 0, 0, 0, False)
        try:
            # Legal suppression and curation removals must not depend on the
            # configured embedding model still being installed or unchanged.
            deleted = await self._remove_ineligible(run, progress)
            total = await self._repository.eligible_count(run)
            if total == 0:
                await self._repository.complete_run(run.id, alias_switched=False)
                await progress("complete", deleted)
                return IndexOutcome(run.id, 0, deleted, 0, False)
            metadata = await self._embeddings.model_metadata(ModelRole.EMBEDDING)
            dimensions = metadata.embedding_dimensions
            if dimensions is None:
                probe = await self._embeddings.create_embeddings(
                    EmbeddingRequest(inputs=(_DIMENSION_PROBE,))
                )
                dimensions = len(probe.value[0])
                if probe.metadata.model_digest != metadata.digest:
                    raise EmbeddingIndexError("embedding_model_changed")
            identity = CollectionIdentity(
                embedding_provider=metadata.provider,
                embedding_model=metadata.name,
                embedding_model_digest=metadata.digest,
                serialization_schema_version=run.serialization_schema_version,
                vector_name=run.vector_name,
            )
            await self._vector_store.prepare_collection(identity, dimensions)
            if run.kind == "incremental":
                readiness = await self._vector_store.readiness(identity, dimensions)
                if not readiness.ready:
                    raise EmbeddingIndexError("embedding_reindex_required")
            await self._repository.configure_run(run.id, identity, dimensions, total)
            indexed, skipped = await self._index_patterns(
                run, identity, dimensions, metadata.digest, progress
            )
            promoted = False
            if run.kind == "reindex" and run.promote_alias:
                await self._vector_store.promote_collection(identity)
                promoted = True
            await self._repository.complete_run(run.id, alias_switched=promoted)
            await progress("complete", indexed + deleted + skipped)
            return IndexOutcome(run.id, indexed, deleted, skipped, promoted)
        except asyncio.CancelledError:
            await self._repository.cancel_run(run.id)
            raise
        except EmbeddingIndexError as error:
            await self._repository.fail_run(run.id, error.code)
            raise
        except Exception as error:
            await self._repository.fail_run(run.id, _safe_error_code(error))
            raise

    async def _index_patterns(
        self,
        run: EmbeddingRunRecord,
        identity: CollectionIdentity,
        dimensions: int,
        model_digest: str,
        progress: ProgressCallback,
    ) -> tuple[int, int]:
        indexed = 0
        skipped = 0
        after_id: UUID | None = None
        while True:
            batch = await self._repository.pattern_batch(
                run, identity, after_id=after_id, limit=run.batch_size
            )
            if not batch:
                return indexed, skipped
            after_id = batch[-1].id
            prepared: list[tuple[PatternForEmbedding, str, str]] = []
            now = datetime.now(UTC)
            for pattern in batch:
                if not pattern.eligible(now):
                    skipped += 1
                    continue
                document = retrieval_document(
                    pattern.pattern,
                    category=pattern.category,
                    language=pattern.language,
                    style_tags=pattern.style_tags,
                )
                if document != pattern.retrieval_document:
                    await self._repository.record_batch_failure(
                        run.id, (pattern.id,), "retrieval_document_mismatch"
                    )
                    raise EmbeddingIndexError("retrieval_document_mismatch")
                digest = hashlib.sha256(document.encode()).hexdigest()
                if (
                    run.kind == "incremental"
                    and pattern.current_status == "indexed"
                    and pattern.current_document_sha256 == digest
                    and (
                        run.dataset_version_id is None
                        or (
                            pattern.current_dataset_id == run.dataset_id
                            and pattern.current_dataset_version_id == run.dataset_version_id
                        )
                    )
                ):
                    skipped += 1
                    await self._repository.advance(run.id, processed=1)
                    continue
                prepared.append((pattern, document, digest))
            if prepared:
                identifiers = tuple((item.id, digest) for item, _, digest in prepared)
                await self._repository.mark_indexing(run.id, identifiers, identity)
                try:
                    result = await self._embeddings.create_embeddings(
                        EmbeddingRequest(
                            inputs=tuple(document for _, document, _ in prepared),
                            dimensions=dimensions,
                        )
                    )
                    if result.metadata.model_digest != model_digest:
                        raise EmbeddingIndexError("embedding_model_changed")
                    points = tuple(
                        VectorPoint(
                            abstract_pattern_text=document,
                            payload=pattern.payload(),
                            vector=vector,
                        )
                        for (pattern, document, _), vector in zip(
                            prepared, result.value, strict=True
                        )
                    )
                    await self._vector_store.upsert_points(identity, points)
                    await self._repository.mark_indexed(run.id, identifiers, identity)
                except Exception as error:
                    code = (
                        error.code
                        if isinstance(error, EmbeddingIndexError)
                        else _safe_error_code(error)
                    )
                    await self._repository.record_batch_failure(
                        run.id, tuple(item.id for item, _, _ in prepared), code
                    )
                    raise
                indexed += len(prepared)
                await self._repository.advance(
                    run.id, processed=len(prepared), indexed=len(prepared)
                )
            await progress("indexing", indexed + skipped)

    async def _remove_ineligible(self, run: EmbeddingRunRecord, progress: ProgressCallback) -> int:
        deleted = 0
        while True:
            records = await self._repository.removal_batch(run.project_id, limit=run.batch_size)
            if not records:
                return deleted
            grouped: dict[tuple[CollectionIdentity, str], list[RemovalRecord]] = defaultdict(list)
            for record in records:
                grouped[(record.identity, record.physical_collection)].append(record)
            for (identity, physical_collection), items in grouped.items():
                await self._vector_store.delete_points(
                    tuple(item.section_pattern_id for item in items),
                    identity,
                    physical_collection,
                )
            await self._repository.mark_deleted(records)
            deleted += len(records)
            await self._repository.advance(run.id, deleted=len(records))
            await progress("deleting", deleted)


class EmbeddingIndexError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _safe_error_code(error: Exception) -> str:
    name = type(error).__name__
    normalized = "".join(character.casefold() if character.isalnum() else "_" for character in name)
    return f"embedding_{normalized[:80]}"
