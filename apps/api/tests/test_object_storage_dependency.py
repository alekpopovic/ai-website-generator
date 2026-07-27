"""FastAPI object-storage dependency tests."""

import httpx2
import pytest
from fastapi import FastAPI
from platform_api.dependencies import ObjectStorageDependency
from platform_api.testing import create_test_app
from platform_clients.object_storage.fake import InMemoryObjectStorage


@pytest.mark.anyio
async def test_fake_mode_injects_in_memory_private_storage() -> None:
    app: FastAPI = create_test_app()

    @app.get("/_test/object-storage")
    async def storage_probe(storage: ObjectStorageDependency) -> dict[str, str]:
        return {"type": type(storage).__name__}

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        assert isinstance(app.state.resources.object_storage, InMemoryObjectStorage)
        response = await client.get("/_test/object-storage")

    assert response.json() == {"type": "InMemoryObjectStorage"}
