"""Opt-in integration coverage against the local Qdrant container."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import httpx2
import pytest
from platform_clients.vector_store.models import (
    CollectionIdentity,
    DesignPatternPayload,
    PayloadFilter,
    ProvenanceStatus,
    VectorPoint,
    VectorQuery,
)
from platform_clients.vector_store.qdrant import QdrantConfig, QdrantVectorStore


@pytest.mark.integration
@pytest.mark.anyio
async def test_qdrant_collection_lifecycle_and_retrieval() -> None:
    if os.environ.get("QDRANT_INTEGRATION_TESTS") != "true":
        pytest.skip("set QDRANT_INTEGRATION_TESTS=true to run Qdrant integration tests")
    alias = f"aiwg-test-{uuid4().hex}"
    api_key = os.environ.get("QDRANT_API_KEY") or None
    headers = {"api-key": api_key} if api_key else None
    async with httpx2.AsyncClient(
        base_url=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"),
        headers=headers,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        store = QdrantVectorStore(
            QdrantConfig(base_url=str(client.base_url), api_key=api_key, collection_alias=alias),
            client,
        )
        identity = CollectionIdentity(
            embedding_provider="integration-test",
            embedding_model="deterministic:3d",
            embedding_model_digest="f" * 64,
        )
        physical = identity.physical_name(alias)
        project_id = UUID("20000000-0000-4000-8000-000000000001")
        section_id = UUID("20000000-0000-4000-8000-000000000006")
        try:
            await store.prepare_collection(identity, 3)
            await store.promote_collection(identity)
            await store.upsert_points(
                identity,
                (
                    VectorPoint(
                        abstract_pattern_text="Compact comparison rows with emphasized decisions",
                        payload=DesignPatternPayload(
                            project_id=project_id,
                            dataset_id=UUID("20000000-0000-4000-8000-000000000002"),
                            dataset_version_id=UUID("20000000-0000-4000-8000-000000000003"),
                            source_website_id=UUID("20000000-0000-4000-8000-000000000004"),
                            source_page_id=UUID("20000000-0000-4000-8000-000000000005"),
                            section_pattern_id=section_id,
                            source_domain="integration.example",
                            category="comparison",
                            page_type="pricing",
                            section_type="plans",
                            layout="comparison-rows",
                            style_tags=("compact",),
                            language="en",
                            confidence=1.0,
                            approved=True,
                            provenance_status=ProvenanceStatus.VERIFIED,
                        ),
                        vector=(1.0, 0.0, 0.0),
                    ),
                ),
            )
            matches = await store.query(
                VectorQuery(
                    vector=(1.0, 0.0, 0.0),
                    filters=PayloadFilter(
                        project_id=project_id,
                        source_domains=("integration.example",),
                    ),
                )
            )
            assert matches[0].point_id == section_id
            assert (await store.readiness(identity, 3)).ready
            await store.delete_points((section_id,))
            assert (await store.statistics()).points_count == 0
        finally:
            await client.post(
                "/collections/aliases",
                json={"actions": [{"delete_alias": {"alias_name": alias}}]},
            )
            await client.delete(f"/collections/{physical}")
