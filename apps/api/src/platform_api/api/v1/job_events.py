"""Authorized SSE and polling endpoints for all durable workflow types."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from platform_api.dependencies import ResourcesDependency, SettingsDependency
from platform_api.errors import problem_responses
from platform_api.job_events.schemas import JobEventPollResponse
from platform_api.job_events.service import JobEventService, decode_principal, parse_event_id

router = APIRouter(prefix="/projects/{project_id}/jobs/{job_id}")


@router.get(
    "/events",
    response_class=StreamingResponse,
    operation_id="streamJobEvents",
    responses=problem_responses(400, 401, 404, 429, 503),
)
async def stream_job_events(
    project_id: UUID,
    job_id: UUID,
    request: Request,
    resources: ResourcesDependency,
    settings: SettingsDependency,
    authorization: Annotated[str | None, Header()] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    principal = decode_principal(resources, authorization)
    service = JobEventService(resources, settings)
    after = parse_event_id(last_event_id)
    await service.authorize(principal, project_id, job_id)
    lease = await service.acquire_stream(principal.user_id)
    return StreamingResponse(
        service.stream(request, principal, project_id, job_id, after=after, lease=lease),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/events/poll",
    response_model=JobEventPollResponse,
    operation_id="pollJobEvents",
    responses=problem_responses(400, 401, 404, 422, 503),
)
async def poll_job_events(
    project_id: UUID,
    job_id: UUID,
    resources: ResourcesDependency,
    settings: SettingsDependency,
    authorization: Annotated[str | None, Header()] = None,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> JobEventPollResponse:
    principal = decode_principal(resources, authorization)
    return await JobEventService(resources, settings).poll(
        principal, project_id, job_id, after=after, limit=limit
    )
