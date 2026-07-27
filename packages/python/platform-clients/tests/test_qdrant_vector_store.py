"""Qdrant adapter tests against a deterministic in-process REST fixture."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx2
import pytest
from fastapi import FastAPI, Request, Response
from platform_clients.vector_store.models import (
    CollectionIdentity,
    DesignPatternPayload,
    PayloadFilter,
    ProvenanceStatus,
    VectorPoint,
    VectorQuery,
)
from platform_clients.vector_store.qdrant import QdrantConfig, QdrantVectorStore

PROJECT_ID = UUID("10000000-0000-4000-8000-000000000001")


class FakeQdrant:
    def __init__(self) -> None:
        self.app = FastAPI()
        self.collections: dict[str, dict[str, Any]] = {}
        self.alias: str | None = None
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self._routes()

    def _routes(self) -> None:
        @self.app.get("/healthz")
        async def health() -> dict[str, str]:
            return {"status": "ok"}

        @self.app.get("/collections")
        async def collections() -> dict[str, object]:
            return {"result": {"collections": []}}

        @self.app.get("/collections/{name}")
        async def collection(name: str) -> Any:
            found = self.collections.get(name)
            if found is None:
                return Response(status_code=404, content='{"status":"not found"}')
            vector_name, vector_config = next(iter(found["vectors"].items()))
            return {
                "result": {
                    "status": "green",
                    "points_count": len(found["points"]),
                    "indexed_vectors_count": len(found["points"]),
                    "config": {"params": {"vectors": {vector_name: vector_config}}},
                }
            }

        @self.app.put("/collections/{name}")
        async def create_collection(name: str, request: Request) -> dict[str, object]:
            payload = await request.json()
            self.requests.append(("create", payload))
            self.collections[name] = {"vectors": payload["vectors"], "points": {}}
            return {"result": True}

        @self.app.put("/collections/{name}/index")
        async def create_index(name: str, request: Request) -> dict[str, object]:
            del name
            self.requests.append(("index", await request.json()))
            return {"result": {"status": "completed"}}

        @self.app.get("/aliases/{alias}")
        async def get_alias(alias: str) -> Any:
            if self.alias is None:
                return Response(status_code=404, content='{"status":"not found"}')
            return {"result": {"aliases": [{"alias_name": alias, "collection_name": self.alias}]}}

        @self.app.post("/collections/aliases")
        async def aliases(request: Request) -> dict[str, object]:
            payload = await request.json()
            self.requests.append(("aliases", payload))
            for action in payload["actions"]:
                if "delete_alias" in action:
                    self.alias = None
                if "create_alias" in action:
                    self.alias = action["create_alias"]["collection_name"]
            return {"result": True}

        @self.app.put("/collections/{name}/points")
        async def upsert(name: str, request: Request) -> dict[str, object]:
            payload = await request.json()
            self.requests.append(("upsert", payload))
            for item in payload["points"]:
                self.collections[name]["points"][item["id"]] = item
            return {"result": {"status": "completed"}}

        @self.app.post("/collections/{name}/points/query")
        async def query(name: str, request: Request) -> dict[str, object]:
            payload = await request.json()
            self.requests.append(("query", payload))
            assert self.alias is not None
            collection = self.collections[self.alias if name == "design-patterns" else name]
            return {
                "result": {
                    "points": [
                        {"id": item["id"], "score": 0.95, "payload": item["payload"]}
                        for item in collection["points"].values()
                    ]
                }
            }

        @self.app.post("/collections/{name}/points/delete")
        async def delete(name: str, request: Request) -> dict[str, object]:
            payload = await request.json()
            assert self.alias is not None
            collection = self.collections[self.alias if name == "design-patterns" else name]
            for point_id in payload["points"]:
                collection["points"].pop(point_id, None)
            return {"result": {"status": "completed"}}


def identity() -> CollectionIdentity:
    return CollectionIdentity(
        embedding_provider="ollama",
        embedding_model="qwen3-embedding:0.6b",
        embedding_model_digest="d" * 64,
    )


def point() -> VectorPoint:
    section_id = UUID("10000000-0000-4000-8000-000000000006")
    return VectorPoint(
        abstract_pattern_text="Alternating proof cards with restrained visual hierarchy",
        payload=DesignPatternPayload(
            project_id=PROJECT_ID,
            dataset_id=UUID("10000000-0000-4000-8000-000000000002"),
            dataset_version_id=UUID("10000000-0000-4000-8000-000000000003"),
            source_website_id=UUID("10000000-0000-4000-8000-000000000004"),
            source_page_id=UUID("10000000-0000-4000-8000-000000000005"),
            section_pattern_id=section_id,
            source_domain="patterns.example",
            category="services",
            page_type="home",
            section_type="proof",
            layout="alternating-cards",
            style_tags=("restrained",),
            language="en",
            confidence=0.8,
            approved=True,
            provenance_status=ProvenanceStatus.VERIFIED,
        ),
        vector=(1.0, 0.0, 0.0),
    )


@pytest.mark.anyio
async def test_qdrant_uses_named_vectors_aliases_and_typed_filters() -> None:
    server = FakeQdrant()
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=server.app), base_url="http://qdrant.internal"
    ) as client:
        store = QdrantVectorStore(QdrantConfig(base_url="http://qdrant.internal"), client)
        version = identity()
        assert (await store.health()).available
        await store.prepare_collection(version, 3)
        await store.promote_collection(version)
        await store.upsert_points(version, (point(),))
        matches = await store.query(
            VectorQuery(
                vector=(1.0, 0.0, 0.0),
                filters=PayloadFilter(
                    project_id=PROJECT_ID,
                    source_domains=("patterns.example",),
                ),
            )
        )
        readiness = await store.readiness(version, 3)
        await store.delete_points((point().point_id,))

    create_payload = next(payload for kind, payload in server.requests if kind == "create")
    upsert_payload = next(payload for kind, payload in server.requests if kind == "upsert")
    query_payload = next(payload for kind, payload in server.requests if kind == "query")
    assert create_payload["vectors"] == {"design-pattern": {"size": 3, "distance": "Cosine"}}
    assert set(upsert_payload["points"][0]["vector"]) == {"design-pattern"}
    assert query_payload["using"] == "design-pattern"
    assert {item["key"] for item in query_payload["filter"]["must"]} >= {
        "project_id",
        "source_domain",
        "approved",
        "provenance_status",
    }
    assert matches[0].payload.source_domain == "patterns.example"
    assert readiness.ready
