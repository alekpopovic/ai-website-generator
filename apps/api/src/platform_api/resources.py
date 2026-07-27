"""Application-owned resource lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

import httpx2

from platform_api.config import Settings
from platform_api.database import DatabaseManager
from platform_api.probes import ProbeRegistry, fake_probe_registry, real_probe_registry
from platform_api.telemetry import Telemetry


@dataclass(slots=True)
class ApplicationResources:
    """Resources initialized and released by the FastAPI lifespan."""

    database: DatabaseManager | None
    http_client: httpx2.AsyncClient
    probes: ProbeRegistry
    telemetry: Telemetry

    @classmethod
    async def create(cls, settings: Settings, telemetry: Telemetry) -> ApplicationResources:
        """Initialize clients without checking external dependency availability."""
        await telemetry.startup()
        http_client = httpx2.AsyncClient(
            follow_redirects=False,
            trust_env=False,
            limits=httpx2.Limits(max_connections=20, max_keepalive_connections=10),
        )
        database = None
        if not settings.application.fake_dependencies and settings.database.url is not None:
            database = DatabaseManager(settings.database)
        probes = (
            fake_probe_registry()
            if settings.application.fake_dependencies
            else real_probe_registry(settings, database, http_client)
        )
        return cls(
            database=database,
            http_client=http_client,
            probes=probes,
            telemetry=telemetry,
        )

    async def close(self) -> None:
        """Close resources in reverse ownership order."""
        if self.database is not None:
            await self.database.close()
        await self.http_client.aclose()
        await self.telemetry.shutdown()
