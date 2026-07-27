"""Explicit FastAPI dependency providers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.config import Settings
from platform_api.errors import ApiError, DependencyUnavailableError
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


async def database_transaction_dependency(
    resources: Annotated[ApplicationResources, Depends(resources_dependency)],
) -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped transaction that commits or rolls back atomically."""
    if resources.database is None:
        raise DependencyUnavailableError("database")
    pending_error: ApiError | None = None
    async with resources.database.transaction() as session:
        try:
            yield session
        except ApiError as error:
            if not error.commit_transaction:
                raise
            pending_error = error
    if pending_error is not None:
        raise pending_error


SettingsDependency = Annotated[Settings, Depends(settings_dependency)]
ResourcesDependency = Annotated[ApplicationResources, Depends(resources_dependency)]
ProbeRegistryDependency = Annotated[ProbeRegistry, Depends(probe_registry_dependency)]
DatabaseTransactionDependency = Annotated[AsyncSession, Depends(database_transaction_dependency)]

# Compatibility name for routes created before the transaction boundary was explicit.
database_session_dependency = database_transaction_dependency
DatabaseSessionDependency = DatabaseTransactionDependency
