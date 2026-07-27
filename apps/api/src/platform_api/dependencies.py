"""Explicit FastAPI dependency providers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.config import Settings
from platform_api.errors import DependencyUnavailableError
from platform_api.probes import ProbeRegistry
from platform_api.resources import ApplicationResources


async def settings_dependency(request: Request) -> Settings:
    """Return immutable process settings from application state."""
    return cast(Settings, request.app.state.settings)


async def resources_dependency(request: Request) -> ApplicationResources:
    """Return lifespan-owned clients from application state."""
    resources = getattr(request.app.state, "resources", None)
    if resources is None:
        raise DependencyUnavailableError("application resources")
    return cast(ApplicationResources, resources)


async def probe_registry_dependency(
    resources: Annotated[ApplicationResources, Depends(resources_dependency)],
) -> ProbeRegistry:
    """Return the health probe registry through an overridable dependency."""
    return resources.probes


async def database_session_dependency(
    resources: Annotated[ApplicationResources, Depends(resources_dependency)],
) -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped SQLAlchemy session."""
    if resources.database is None:
        raise DependencyUnavailableError("database")
    async for session in resources.database.session():
        yield session


SettingsDependency = Annotated[Settings, Depends(settings_dependency)]
ResourcesDependency = Annotated[ApplicationResources, Depends(resources_dependency)]
ProbeRegistryDependency = Annotated[ProbeRegistry, Depends(probe_registry_dependency)]
DatabaseSessionDependency = Annotated[AsyncSession, Depends(database_session_dependency)]
