"""Versioned API identity endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from platform_api.dependencies import SettingsDependency
from platform_api.models.common import ApiResponse, ResponseMeta

router = APIRouter()


class VersionInfo(BaseModel):
    """Public API and service version information."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_version: str
    service_version: str
    environment: str


@router.get("/version", response_model=ApiResponse[VersionInfo])
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
