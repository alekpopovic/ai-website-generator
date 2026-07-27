"""FastAPI Temporal dependency and fake-dispatcher tests."""

import httpx2
import pytest
from fastapi import Depends
from platform_api.dependencies import (
    WorkflowDispatcherDependency,
    temporal_client_dependency,
)
from platform_api.testing import create_test_app
from platform_workflows.dispatcher import FakeWorkflowDispatcher


@pytest.mark.anyio
async def test_fake_mode_owns_a_no_io_workflow_dispatcher() -> None:
    app = create_test_app()

    async with app.router.lifespan_context(app):
        assert isinstance(app.state.resources.workflow_dispatcher, FakeWorkflowDispatcher)
        assert app.state.resources.temporal_clients is None


@pytest.mark.anyio
async def test_temporal_client_dependency_is_unavailable_in_fake_mode() -> None:
    app = create_test_app()

    @app.get("/_test/temporal")
    async def temporal_dependency_probe(
        _client: object = Depends(temporal_client_dependency),
    ) -> dict[str, bool]:
        return {"connected": True}

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.get("/_test/temporal")

    assert response.status_code == 503


@pytest.mark.anyio
async def test_workflow_dispatcher_dependency_returns_test_fake() -> None:
    app = create_test_app()

    @app.get("/_test/dispatcher")
    async def dispatcher_probe(
        dispatcher: WorkflowDispatcherDependency,
    ) -> dict[str, str]:
        return {"type": type(dispatcher).__name__}

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.get("/_test/dispatcher")

    assert response.json() == {"type": "FakeWorkflowDispatcher"}
