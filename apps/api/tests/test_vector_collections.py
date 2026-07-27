"""Administrator vector collection statistics tests."""

from datetime import UTC, datetime
from uuid import uuid4

import httpx2
import pytest
from fastapi import FastAPI
from platform_api.auth.dependencies import current_user_dependency
from platform_api.config import SecuritySettings
from platform_api.persistence.models import User
from platform_api.testing import create_test_app
from platform_api.testing import test_settings as make_test_settings
from platform_clients.llm.models import ModelRole
from platform_clients.vector_store.models import CollectionIdentity


def _user(email: str) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        email=email,
        display_name="Vector Operator",
        status="active",
        created_at=now,
        updated_at=now,
        version=1,
    )


def _administrator_app(administrator: User, current: User | None = None) -> FastAPI:
    base = make_test_settings()
    settings = base.model_copy(
        update={
            "security": SecuritySettings(
                trusted_hosts=("testserver",),
                force_https=False,
                enable_docs=True,
                administrator_emails=(administrator.email,),
            )
        }
    )
    app = create_test_app(settings=settings)

    async def override_user() -> User:
        return current or administrator

    app.dependency_overrides[current_user_dependency] = override_user
    return app


@pytest.mark.anyio
async def test_administrator_can_inspect_versioned_collection_statistics() -> None:
    app = _administrator_app(_user("admin@example.com"))
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        metadata = await app.state.resources.llm_gateway.model_metadata(ModelRole.EMBEDDING)
        identity = CollectionIdentity(
            embedding_provider=metadata.provider,
            embedding_model=metadata.name,
            embedding_model_digest=metadata.digest,
            serialization_schema_version=app.state.settings.qdrant.serialization_schema_version,
            vector_name=app.state.settings.qdrant.vector_name,
        )
        assert metadata.embedding_dimensions is not None
        await app.state.resources.vector_store.prepare_collection(
            identity, metadata.embedding_dimensions
        )
        await app.state.resources.vector_store.promote_collection(identity)
        response = await client.get("/api/v1/admin/vector-collections/statistics")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ready"] is True
    assert data["expected_dimensions"] == 3
    assert data["version"]["embedding_provider"] == "fake"
    assert data["active_collection"] == data["expected_collection"]


@pytest.mark.anyio
async def test_collection_statistics_are_forbidden_to_non_administrators() -> None:
    administrator = _user("admin@example.com")
    app = _administrator_app(administrator, _user("member@example.com"))
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.get("/api/v1/admin/vector-collections/statistics")

    assert response.status_code == 403
    assert response.json()["code"] == "administrator_required"
