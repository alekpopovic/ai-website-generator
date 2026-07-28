"""Opt-in private Ollama embedding and Qdrant collection integration coverage."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from platform_clients.llm.models import EmbeddingRequest, ModelRole
from platform_clients.llm.ollama import OllamaConfig, OllamaGateway
from platform_clients.vector_store.models import (
    CollectionIdentity,
    DesignPatternPayload,
    ProvenanceStatus,
    VectorPoint,
)
from platform_clients.vector_store.qdrant import QdrantConfig, QdrantVectorStore

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.mark.skipif(
    os.environ.get("EMBEDDING_WORKER_INTEGRATION_TESTS") != "true",
    reason="set EMBEDDING_WORKER_INTEGRATION_TESTS=true for private provider integration",
)
async def test_private_ollama_embedding_upserts_versioned_qdrant_point() -> None:
    ollama = OllamaGateway.create(
        OllamaConfig(
            base_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
            embedding_model=os.environ.get("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:0.6b"),
        )
    )
    vectors = QdrantVectorStore.create(
        QdrantConfig(
            base_url=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"),
            api_key=os.environ.get("QDRANT_API_KEY") or None,
            collection_alias="embedding-worker-integration",
            max_batch_size=8,
        )
    )
    try:
        metadata = await ollama.model_metadata(ModelRole.EMBEDDING)
        result = await ollama.create_embeddings(
            EmbeddingRequest(inputs=("section=hero; purpose=value-proposition; layout=split",))
        )
        dimensions = len(result.value[0])
        identity = CollectionIdentity(
            embedding_provider=metadata.provider,
            embedding_model=metadata.name,
            embedding_model_digest=metadata.digest,
        )
        await vectors.prepare_collection(identity, dimensions)
        pattern_id = uuid4()
        await vectors.upsert_points(
            identity,
            (
                VectorPoint(
                    abstract_pattern_text="section=hero; purpose=value-proposition; layout=split",
                    payload=DesignPatternPayload(
                        project_id=uuid4(),
                        source_website_id=uuid4(),
                        source_page_id=uuid4(),
                        section_pattern_id=pattern_id,
                        source_domain="fixture.example",
                        category="homepage",
                        page_type="homepage",
                        section_type="hero",
                        layout="split",
                        language="en",
                        confidence=0.8,
                        approved=True,
                        provenance_status=ProvenanceStatus.VERIFIED,
                    ),
                    vector=result.value[0],
                ),
            ),
        )
        statistics = await vectors.statistics(identity)
        assert statistics.dimensions == dimensions
        assert statistics.points_count >= 1
        assert result.metadata.model_digest == identity.embedding_model_digest
    finally:
        await vectors.close()
        await ollama.close()
