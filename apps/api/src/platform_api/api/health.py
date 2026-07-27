"""Process and dependency health endpoints."""

from __future__ import annotations

from enum import StrEnum

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict

from platform_api.constants import SERVICE_NAME
from platform_api.dependencies import ProbeRegistryDependency, SettingsDependency
from platform_api.probes import DependencyCheck, DependencyState

router = APIRouter()


class HealthState(StrEnum):
    """Aggregate health vocabulary."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"


class LivenessResponse(BaseModel):
    """Process liveness response without external I/O."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: HealthState
    service: str
    version: str


class DependencyHealthResponse(BaseModel):
    """Aggregate dependency health response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: HealthState
    dependencies: tuple[DependencyCheck, ...]


def _aggregate(checks: tuple[DependencyCheck, ...]) -> HealthState:
    """Classify critical failures separately from optional degradation."""
    if any(check.critical and check.state is DependencyState.UNAVAILABLE for check in checks):
        return HealthState.NOT_READY
    if any(check.state is DependencyState.UNAVAILABLE for check in checks):
        return HealthState.DEGRADED
    return HealthState.HEALTHY


@router.get("/live", response_model=LivenessResponse)
async def live(settings: SettingsDependency) -> LivenessResponse:
    """Report whether the request process can serve HTTP."""
    return LivenessResponse(
        status=HealthState.HEALTHY,
        service=SERVICE_NAME,
        version=settings.application.version,
    )


@router.get(
    "/ready",
    response_model=DependencyHealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": DependencyHealthResponse}},
)
async def ready(
    response: Response,
    probes: ProbeRegistryDependency,
) -> DependencyHealthResponse:
    """Report readiness of dependencies required by the control plane."""
    checks = await probes.check(critical_only=True)
    health_state = _aggregate(checks)
    if health_state is HealthState.NOT_READY:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return DependencyHealthResponse(status=health_state, dependencies=checks)


@router.get(
    "/dependencies",
    response_model=DependencyHealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": DependencyHealthResponse}},
)
async def dependencies(
    response: Response,
    probes: ProbeRegistryDependency,
) -> DependencyHealthResponse:
    """Report all direct and worker-facing infrastructure dependency checks."""
    checks = await probes.check()
    health_state = _aggregate(checks)
    if health_state is HealthState.NOT_READY:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return DependencyHealthResponse(status=health_state, dependencies=checks)
