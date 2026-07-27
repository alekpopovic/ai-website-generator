"""Control-plane model readiness and worker-dispatched warm-up tests."""

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
from platform_clients.llm.fake import FakeLLMGateway
from platform_workflows.dispatcher import FakeWorkflowDispatcher


def user(email: str) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        email=email,
        display_name="Operator",
        status="active",
        created_at=now,
        updated_at=now,
        version=1,
    )


def administrator_app(operator: User) -> FastAPI:
    base = make_test_settings()
    settings = base.model_copy(
        update={
            "security": SecuritySettings(
                trusted_hosts=("testserver",),
                force_https=False,
                enable_docs=True,
                administrator_emails=(operator.email,),
            )
        }
    )
    app = create_test_app(settings=settings)

    async def override_user() -> User:
        return operator

    app.dependency_overrides[current_user_dependency] = override_user
    return app


@pytest.mark.anyio
async def test_authenticated_readiness_returns_configured_fake_models() -> None:
    operator = user("operator@example.com")
    app = administrator_app(operator)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.get("/api/v1/models/readiness")

    assert response.status_code == 200
    assert response.json()["data"]["ready"] is True
    assert {item["role"] for item in response.json()["data"]["models"]} == {
        "generation",
        "vision",
        "embedding",
    }


@pytest.mark.anyio
async def test_admin_warmup_dispatches_temporal_and_never_calls_gateway() -> None:
    administrator = user("admin@example.com")
    app = administrator_app(administrator)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            "/api/v1/admin/models/vision/warm-up",
            json={"idempotency_key": "admin-request-1"},
        )
        duplicate = await client.post(
            "/api/v1/admin/models/vision/warm-up",
            json={"idempotency_key": "admin-request-1"},
        )
        resources = app.state.resources
        dispatcher = resources.workflow_dispatcher
        gateway = resources.llm_gateway

    assert response.status_code == 202
    assert duplicate.status_code == 409
    assert isinstance(dispatcher, FakeWorkflowDispatcher)
    assert dispatcher.warmups[0].model_role.value == "vision"
    assert len(dispatcher.warmups) == 1
    assert isinstance(gateway, FakeLLMGateway)
    assert gateway.calls == []


@pytest.mark.anyio
async def test_warmup_is_forbidden_when_user_is_not_allowlisted() -> None:
    administrator = user("admin@example.com")
    intruder = user("person@example.com")
    app = administrator_app(administrator)

    async def override_user() -> User:
        return intruder

    app.dependency_overrides[current_user_dependency] = override_user
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            "/api/v1/admin/models/generation/warm-up",
            json={"idempotency_key": "blocked-request"},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "administrator_required"
