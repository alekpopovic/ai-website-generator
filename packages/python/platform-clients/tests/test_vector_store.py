"""Provider-neutral vector contracts and deterministic fake-store tests."""

from __future__ import annotations

from uuid import UUID

import pytest
from platform_clients.llm.fake import FakeLLMGateway
from platform_clients.llm.models import ModelRole
from platform_clients.vector_store.fake import InMemoryVectorStore
from platform_clients.vector_store.models import (
    CollectionIdentity,
    DesignPatternPayload,
    DiversityPolicy,
    PayloadFilter,
    ProvenanceStatus,
    VectorPoint,
    VectorQuery,
)
from platform_clients.vector_store.reindex import reindex_active_records
from pydantic import ValidationError

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
DATASET_ID = UUID("00000000-0000-4000-8000-000000000002")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000003")


def identity(*, digest: str = "a" * 64, schema_version: int = 1) -> CollectionIdentity:
    return CollectionIdentity(
        embedding_provider="ollama",
        embedding_model="qwen3-embedding:0.6b",
        embedding_model_digest=digest,
        serialization_schema_version=schema_version,
    )


def point(index: int, domain: str, vector: tuple[float, ...]) -> VectorPoint:
    return VectorPoint(
        abstract_pattern_text=f"Asymmetric feature grid pattern number {index}",
        payload=DesignPatternPayload(
            project_id=PROJECT_ID,
            dataset_id=DATASET_ID,
            dataset_version_id=VERSION_ID,
            source_website_id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
            source_page_id=UUID(f"00000000-0000-4001-8000-{index:012d}"),
            section_pattern_id=UUID(f"00000000-0000-4002-8000-{index:012d}"),
            source_domain=domain,
            category="marketing",
            page_type="home",
            section_type="features",
            layout="asymmetric-grid",
            style_tags=("editorial", "spacious"),
            language="en",
            confidence=0.9,
            approved=True,
            provenance_status=ProvenanceStatus.VERIFIED,
        ),
        vector=vector,
    )


def test_collection_name_changes_for_every_embedding_version_dimension() -> None:
    base = identity().physical_name("design-patterns")
    variants = {
        identity(digest="b" * 64).physical_name("design-patterns"),
        identity(schema_version=2).physical_name("design-patterns"),
        identity()
        .model_copy(update={"embedding_provider": "future"})
        .physical_name("design-patterns"),
        identity()
        .model_copy(update={"embedding_model": "other:1b"})
        .physical_name("design-patterns"),
    }
    assert base not in variants
    assert len(variants) == 4


def test_payload_rejects_raw_content_escape_hatches_and_non_abstract_text() -> None:
    payload = point(1, "one.example", (1.0, 0.0, 0.0)).payload.model_dump()
    payload["raw_html"] = "<main>copied page</main>"
    with pytest.raises(ValidationError):
        DesignPatternPayload.model_validate(payload)
    with pytest.raises(ValidationError, match="abstract pattern"):
        VectorPoint(
            abstract_pattern_text="Copied from https://source.example/page",
            payload=point(1, "one.example", (1.0, 0.0, 0.0)).payload,
            vector=(1.0, 0.0, 0.0),
        )


@pytest.mark.anyio
async def test_fake_store_supports_idempotent_batches_filters_and_source_diversity() -> None:
    store = InMemoryVectorStore()
    version = identity()
    first = point(1, "one.example", (1.0, 0.0, 0.0))
    second_same_source = point(2, "one.example", (0.99, 0.01, 0.0))
    third = point(3, "two.example", (0.9, 0.1, 0.0))

    await store.prepare_collection(version, 3)
    await store.promote_collection(version)
    await store.upsert_points(version, (first, second_same_source, third))
    await store.upsert_points(version, (first,))

    statistics = await store.statistics()
    matches = await store.query(
        VectorQuery(
            vector=(1.0, 0.0, 0.0),
            filters=PayloadFilter(
                project_id=PROJECT_ID,
                dataset_version_ids=(VERSION_ID,),
                source_domains=("one.example", "two.example"),
            ),
            limit=2,
            diversity=DiversityPolicy(maximum_per_source=1),
        )
    )

    assert statistics.points_count == 3
    assert [match.payload.source_domain for match in matches] == [
        "one.example",
        "two.example",
    ]
    await store.delete_points((first.point_id, third.point_id))
    assert (await store.statistics()).points_count == 1


@pytest.mark.anyio
async def test_fake_store_alias_promotion_is_atomic_and_readiness_is_versioned() -> None:
    store = InMemoryVectorStore()
    old = identity(digest="a" * 64)
    new = identity(digest="b" * 64)
    await store.prepare_collection(old, 3)
    await store.promote_collection(old)
    assert (await store.readiness(old, 3)).ready

    await store.prepare_collection(new, 3)
    assert not (await store.readiness(new, 3)).ready
    await store.promote_collection(new)

    assert (await store.readiness(new, 3)).ready
    assert not (await store.readiness(old, 3)).ready


@pytest.mark.anyio
async def test_reindex_copies_only_validated_abstract_records_to_new_identity() -> None:
    store = InMemoryVectorStore()
    gateway = FakeLLMGateway()
    old = identity(digest="a" * 64)
    metadata = await gateway.model_metadata(ModelRole.EMBEDDING)
    new = identity(digest=metadata.digest)
    await store.prepare_collection(old, 3)
    await store.promote_collection(old)
    await store.upsert_points(old, (point(1, "one.example", (1.0, 0.0, 0.0)),))
    await store.prepare_collection(new, 3)

    copied = await reindex_active_records(gateway, store, identity=new, dimensions=3, batch_size=1)
    await store.promote_collection(new)

    assert copied == 1
    assert (await store.statistics()).points_count == 1
    assert gateway.calls == [("embedding", ModelRole.EMBEDDING)]
