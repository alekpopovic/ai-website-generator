"""Shared deterministic API unit-test fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI
from platform_api.config import Settings
from platform_api.testing import create_test_app, test_settings


@pytest.fixture
def settings() -> Settings:
    """Return isolated fake-mode settings."""
    return test_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """Return an application that cannot contact real dependencies."""
    return create_test_app(settings=settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    """Run lifespan startup and shutdown around each client."""
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as test_client,
    ):
        yield test_client


@pytest.fixture
def anyio_backend() -> str:
    """Keep deterministic unit tests on the production asyncio backend."""
    return "asyncio"
