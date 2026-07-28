"""Offline embedding batching, idempotency, safety, reindex, and removal tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from platform_api.analysis.patterns import retrieval_document
from platform_clients.llm.fake import FakeLLMGateway
from platform_clients.llm.models import ModelRole
from platform_clients.vector_store.fake import InMemoryVectorStore
from platform_clients.vector_store.models import CollectionIdentity
from platform_embedding_worker.activities import EmbeddingActivities
from platform_embedding_worker.models import (
    EmbeddingRunRecord,
    PatternForEmbedding,
    RemovalRecord,
)
from platform_embedding_worker.runner import EmbeddingIndexer, EmbeddingIndexError
from platform_schemas import CopyPurpose, SectionPattern, SectionType, StyleTag
from platform_workflows.commands import EmbeddingIndexInput
from temporalio.testing import ActivityEnvironment


def pattern(project_id: UUID, *, document_override: str | None = None) -> PatternForEmbedding:
    schema = SectionPattern(
        section_type=SectionType.HERO,
        order=0,
        copy_purpose=CopyPurpose.VALUE_PROPOSITION,
        layout="split",
    )
    tags = (StyleTag.MINIMALIST, StyleTag.SPACIOUS)
    document = retrieval_document(schema, category="homepage", language="en", style_tags=tags)
    return PatternForEmbedding(
        id=uuid4(),
        project_id=project_id,
        source_website_id=uuid4(),
        source_page_id=uuid4(),
        source_domain="fixture.example",
        category="homepage",
        page_type="homepage",
        section_type="hero",
        layout="split",
        style_tags=tags,
        language="en",
        confidence=0.8,
        pattern=schema,
        retrieval_document=document_override or document,
        retrieval_expires_at=None,
        retrieval_removed_at=None,
        legally_suppressed_at=None,
        approval_state="approved",
        provenance_state="authorized",
        current_document_sha256=None,
        current_status=None,
    )


class FakeRepository:
    def __init__(self, run: EmbeddingRunRecord, patterns: tuple[PatternForEmbedding, ...]) -> None:
        self.run = run
        self.patterns = patterns
        self.removals: list[RemovalRecord] = []
        self.indexed: list[UUID] = []
        self.deleted: list[UUID] = []
        self.failures: list[tuple[UUID, ...]] = []
        self.completed = False
        self.alias_switched = False
        self.failed_code: str | None = None
        self.cancelled = False

    async def claim_run(self, run_id: UUID) -> EmbeddingRunRecord:
        assert run_id == self.run.id
        return self.run

    async def configure_run(
        self, run_id: UUID, identity: CollectionIdentity, dimensions: int, total: int
    ) -> None:
        assert run_id == self.run.id
        assert dimensions == 3
        assert total == len(self.patterns)

    async def eligible_count(self, run: EmbeddingRunRecord) -> int:
        return len(self.patterns)

    async def pattern_batch(
        self,
        run: EmbeddingRunRecord,
        identity: CollectionIdentity,
        *,
        after_id: UUID | None,
        limit: int,
    ) -> tuple[PatternForEmbedding, ...]:
        ordered = tuple(sorted(self.patterns, key=lambda item: item.id))
        remaining = (
            ordered if after_id is None else tuple(item for item in ordered if item.id > after_id)
        )
        return remaining[:limit]

    async def removal_batch(self, project_id: UUID, *, limit: int) -> tuple[RemovalRecord, ...]:
        result = tuple(self.removals[:limit])
        self.removals = self.removals[len(result) :]
        return result

    async def mark_indexing(
        self,
        run_id: UUID,
        patterns: tuple[tuple[UUID, str], ...],
        identity: CollectionIdentity,
    ) -> None:
        return None

    async def mark_indexed(
        self,
        run_id: UUID,
        patterns: tuple[tuple[UUID, str], ...],
        identity: CollectionIdentity,
    ) -> None:
        self.indexed.extend(pattern_id for pattern_id, _ in patterns)

    async def mark_deleted(self, records: tuple[RemovalRecord, ...]) -> None:
        self.deleted.extend(record.section_pattern_id for record in records)

    async def record_batch_failure(
        self, run_id: UUID, pattern_ids: tuple[UUID, ...], error_code: str
    ) -> None:
        self.failures.append(pattern_ids)

    async def advance(
        self,
        run_id: UUID,
        *,
        processed: int = 0,
        indexed: int = 0,
        deleted: int = 0,
    ) -> None:
        return None

    async def complete_run(self, run_id: UUID, *, alias_switched: bool) -> None:
        self.completed = True
        self.alias_switched = alias_switched

    async def fail_run(self, run_id: UUID, error_code: str) -> None:
        self.failed_code = error_code

    async def cancel_run(self, run_id: UUID) -> None:
        self.cancelled = True


def run_record(
    project_id: UUID, *, batch_size: int = 2, status: str = "queued"
) -> EmbeddingRunRecord:
    return EmbeddingRunRecord(
        id=uuid4(),
        project_id=project_id,
        kind="reindex",
        status=status,
        batch_size=batch_size,
        promote_alias=True,
        collection_alias="design-patterns",
        serialization_schema_version=1,
        vector_name="design-pattern",
    )


async def no_progress(stage: str, completed: int) -> None:
    return None


@pytest.mark.anyio
async def test_reindex_batches_fake_embeddings_and_promotes_only_after_success() -> None:
    project_id = uuid4()
    patterns = tuple(pattern(project_id) for _ in range(5))
    repository = FakeRepository(run_record(project_id), patterns)
    gateway = FakeLLMGateway()
    vectors = InMemoryVectorStore()

    outcome = await EmbeddingIndexer(repository, gateway, vectors).run(
        repository.run.id, no_progress
    )

    assert outcome.indexed == 5
    assert repository.indexed == [item.id for item in sorted(patterns, key=lambda item: item.id)]
    assert repository.completed is True
    assert repository.alias_switched is True
    assert gateway.calls.count(("embedding", ModelRole.EMBEDDING)) == 3
    statistics = await vectors.statistics()
    assert statistics.points_count == 5


@pytest.mark.anyio
async def test_document_is_recomputed_and_rejects_raw_url_or_copy_tampering() -> None:
    project_id = uuid4()
    unsafe = pattern(
        project_id,
        document_override="https://source.example proprietary source sentence",
    )
    repository = FakeRepository(run_record(project_id), (unsafe,))

    with pytest.raises(EmbeddingIndexError) as error:
        await EmbeddingIndexer(repository, FakeLLMGateway(), InMemoryVectorStore()).run(
            repository.run.id, no_progress
        )

    assert error.value.code == "retrieval_document_mismatch"
    assert repository.failed_code == "retrieval_document_mismatch"


@pytest.mark.anyio
async def test_succeeded_run_is_idempotent_and_does_not_call_providers() -> None:
    project_id = uuid4()
    repository = FakeRepository(run_record(project_id, status="succeeded"), (pattern(project_id),))
    gateway = FakeLLMGateway()

    outcome = await EmbeddingIndexer(repository, gateway, InMemoryVectorStore()).run(
        repository.run.id, no_progress
    )

    assert outcome.indexed == 0
    assert gateway.calls == []


@pytest.mark.anyio
async def test_ineligible_vector_is_removed_from_recorded_physical_collection() -> None:
    project_id = uuid4()
    repository = FakeRepository(run_record(project_id), ())
    identity = CollectionIdentity(
        embedding_provider="fake",
        embedding_model="qwen3-embedding:0.6b",
        embedding_model_digest="3" * 64,
    )
    vectors = InMemoryVectorStore()
    await vectors.prepare_collection(identity, 3)
    repository.removals.append(
        RemovalRecord(uuid4(), identity, identity.physical_name("design-patterns"))
    )

    outcome = await EmbeddingIndexer(repository, FakeLLMGateway(), vectors).run(
        repository.run.id, no_progress
    )

    assert outcome.deleted == 1
    assert repository.deleted


@pytest.mark.anyio
async def test_legal_removal_does_not_depend_on_embedding_model_readiness() -> None:
    class UnavailableGateway(FakeLLMGateway):
        async def model_metadata(self, role: ModelRole):  # type: ignore[no-untyped-def]
            raise RuntimeError("model is unavailable")

    project_id = uuid4()
    repository = FakeRepository(run_record(project_id), ())
    identity = CollectionIdentity(
        embedding_provider="fake",
        embedding_model="retired-model",
        embedding_model_digest="4" * 64,
    )
    vectors = InMemoryVectorStore()
    await vectors.prepare_collection(identity, 3)
    record = RemovalRecord(uuid4(), identity, identity.physical_name("design-patterns"))
    repository.removals.append(record)

    outcome = await EmbeddingIndexer(repository, UnavailableGateway(), vectors).run(
        repository.run.id, no_progress
    )

    assert repository.deleted == [record.section_pattern_id]
    assert outcome.deleted == 1
    assert repository.completed


def test_removed_expired_and_legally_suppressed_patterns_are_not_eligible() -> None:
    value = pattern(uuid4())
    now = datetime.now(UTC)
    assert value.eligible(now)
    removed = replace(value, retrieval_removed_at=now)
    expired = replace(value, retrieval_expires_at=now)
    suppressed = replace(value, legally_suppressed_at=now)
    assert not removed.eligible(now)
    assert not expired.eligible(now)
    assert not suppressed.eligible(now)


@pytest.mark.anyio
async def test_temporal_activity_heartbeats_counts_without_documents() -> None:
    project_id = uuid4()
    repository = FakeRepository(run_record(project_id), (pattern(project_id),))
    activity = EmbeddingActivities(
        EmbeddingIndexer(repository, FakeLLMGateway(), InMemoryVectorStore())
    )
    heartbeats: list[tuple[object, ...]] = []
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *details: heartbeats.append(details)

    result = await environment.run(
        activity.index_section_patterns,
        EmbeddingIndexInput(str(repository.run.id)),
    )

    assert result.record_id == str(repository.run.id)
    assert heartbeats
    assert all("section=" not in str(details) for details in heartbeats)
