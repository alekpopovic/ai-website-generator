"""Opt-in dependency boundary for the full fixture scan workflow integration suite."""

from __future__ import annotations

import os

import httpx
import pytest
from platform_api.config import get_settings
from platform_api.database import DatabaseManager
from platform_clients.llm.fake import FakeLLMGateway
from platform_clients.llm.models import EmbeddingRequest
from platform_clients.object_storage import S3ObjectStorage, StorageConfig
from platform_clients.object_storage.models import StorageProvider
from platform_clients.vector_store.qdrant import QdrantConfig, QdrantVectorStore

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.mark.skipif(
    os.environ.get("SCAN_CAMPAIGN_E2E_TESTS") != "true",
    reason="set SCAN_CAMPAIGN_E2E_TESTS=true with the private development stack",
)
async def test_scan_campaign_fixture_dependencies_are_ready_for_temporal_pipeline() -> None:
    """Fail early when any real persistence boundary required by scan E2E is absent."""
    settings = get_settings()
    database = DatabaseManager(settings.database)
    minio = settings.minio
    storage = await S3ObjectStorage.create(
        StorageConfig(
            provider=StorageProvider(minio.provider),
            region=minio.region,
            endpoint_url=str(minio.endpoint) if minio.endpoint is not None else None,
            access_key=minio.access_key.get_secret_value() if minio.access_key else None,
            secret_key=minio.secret_key.get_secret_value() if minio.secret_key else None,
        )
    )
    qdrant = QdrantVectorStore.create(
        QdrantConfig(
            base_url=str(settings.qdrant.url),
            api_key=(
                settings.qdrant.api_key.get_secret_value() if settings.qdrant.api_key else None
            ),
        )
    )
    try:
        await database.check_health()
        assert all(item.ready for item in await storage.readiness())
        assert (await qdrant.health()).available
        fixture_url = os.environ.get("FIXTURE_WEBSITE_URL", "http://127.0.0.1:8088")
        async with httpx.AsyncClient(timeout=5) as client:
            assert (await client.get(f"{fixture_url}/healthz")).is_success
        fake_ollama = FakeLLMGateway()
        embedded = await fake_ollama.create_embeddings(
            EmbeddingRequest(inputs=("section=hero; purpose=value-proposition; layout=split",))
        )
        assert embedded.value and embedded.metadata.model_digest
    finally:
        await qdrant.close()
        await storage.close()
        await database.close()
