"""Versioned API identity endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict

from platform_api.dependencies import SettingsDependency
from platform_api.errors import problem_responses
from platform_api.models.common import ApiResponse, ResponseMeta

router = APIRouter()


class VersionInfo(BaseModel):
    """Public API and service version information."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_version: str
    service_version: str
    environment: str


@router.get(
    "/version",
    response_model=ApiResponse[VersionInfo],
    operation_id="getApiVersion",
    responses=problem_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    ),
)
async def version(request: Request, settings: SettingsDependency) -> ApiResponse[VersionInfo]:
    """Return the stable API contract version and current service build version."""
    return ApiResponse(
        data=VersionInfo(
            api_version="v1",
            service_version=settings.application.version,
            environment=settings.application.environment,
        ),
        meta=ResponseMeta(request_id=str(request.state.request_id)),
    )
