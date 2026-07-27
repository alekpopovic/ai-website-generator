"""Unit tests for application composition and transport contracts."""

from __future__ import annotations

import uuid
from typing import Annotated

import httpx2
import pytest
from fastapi import FastAPI, Query
from platform_api.dependencies import probe_registry_dependency
from platform_api.probes import FunctionProbe, ProbeRegistry
from platform_api.testing import create_test_app

pytestmark = pytest.mark.anyio


async def test_liveness_is_process_only_and_correlated(client: httpx2.AsyncClient) -> None:
    """Liveness succeeds without contacting external dependencies."""
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "platform-api",
        "version": "0.0.0",
    }
    assert uuid.UUID(response.headers["X-Request-ID"])


async def test_valid_caller_request_id_is_propagated(client: httpx2.AsyncClient) -> None:
    """A safe caller-provided correlation ID is preserved."""
    response = await client.get("/api/v1/version", headers={"X-Request-ID": "request_01-test"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request_01-test"
    assert response.json()["meta"]["request_id"] == "request_01-test"


async def test_unsafe_caller_request_id_is_replaced(client: httpx2.AsyncClient) -> None:
    """Untrusted values cannot inject arbitrary content into correlation logs."""
    response = await client.get("/health/live", headers={"X-Request-ID": "bad id\nvalue"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad id\nvalue"
    assert uuid.UUID(response.headers["X-Request-ID"])


async def test_version_route_uses_versioned_envelope(client: httpx2.AsyncClient) -> None:
    """The only initial API route lives below the v1 prefix."""
    response = await client.get("/api/v1/version")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "api_version": "v1",
        "service_version": "0.0.0",
        "environment": "test",
    }


async def test_fake_dependencies_are_deterministically_healthy(
    client: httpx2.AsyncClient,
) -> None:
    """Default CI health checks require no live infrastructure."""
    response = await client.get("/health/dependencies")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert [item["name"] for item in response.json()["dependencies"]] == [
        "database",
        "redis",
        "temporal",
        "minio",
        "qdrant",
        "ollama",
    ]


async def test_readiness_uses_an_explicit_dependency_override() -> None:
    """Tests can replace infrastructure through standard FastAPI overrides."""

    async def unavailable() -> None:
        raise RuntimeError("synthetic failure")

    async def override_registry() -> ProbeRegistry:
        return registry

    registry = ProbeRegistry([FunctionProbe("database", True, unavailable)])
    app = create_test_app(dependency_overrides={probe_registry_dependency: override_registry})
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["dependencies"][0]["detail"] == "Health check failed."


async def test_framework_errors_use_problem_details(client: httpx2.AsyncClient) -> None:
    """Even routing failures use the central RFC-style contract."""
    response = await client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "http_error"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


async def test_validation_errors_use_sanitized_problem_details(app: FastAPI) -> None:
    """Request validation never echoes the rejected input value."""

    @app.get("/_test/validation")
    async def validate(limit: Annotated[int, Query(ge=1)]) -> dict[str, int]:
        return {"limit": limit}

    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        response = await client.get("/_test/validation", params={"limit": "secret-rejected"})

    assert response.status_code == 422
    assert response.json()["code"] == "request_validation_failed"
    assert response.json()["invalid_parameters"][0]["name"] == "limit"
    assert "secret-rejected" not in response.text


async def test_unhandled_errors_do_not_leak_details(app: FastAPI) -> None:
    """Unexpected exceptions expose only a stable public message."""

    @app.get("/_test/error")
    async def fail() -> None:
        raise RuntimeError("private implementation detail")

    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        response = await client.get("/_test/error")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_server_error"
    assert "private implementation detail" not in response.text


async def test_security_headers_are_applied(client: httpx2.AsyncClient) -> None:
    """API responses carry defensive browser headers by default."""
    response = await client.get("/health/live")

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


async def test_cors_accepts_only_the_explicit_test_origin(client: httpx2.AsyncClient) -> None:
    """CORS does not fall back to a wildcard."""
    allowed = await client.options(
        "/api/v1/version",
        headers={
            "Origin": "http://localhost:4200",
            "Access-Control-Request-Method": "GET",
        },
    )
    denied = await client.options(
        "/api/v1/version",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:4200"
    assert denied.status_code == 400
    assert "Access-Control-Allow-Origin" not in denied.headers


async def test_request_body_limit_returns_problem_details(client: httpx2.AsyncClient) -> None:
    """Oversized bodies are rejected before routing or parsing."""
    response = await client.post(
        "/api/v1/version",
        content=b"x" * 1_048_577,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "request_body_too_large"
