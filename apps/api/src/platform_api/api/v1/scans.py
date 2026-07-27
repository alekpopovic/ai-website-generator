"""Project-owned scan campaign CRUD, projections, and workflow controls."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from platform_api.auth.dependencies import CurrentUserDependency
from platform_api.errors import problem_responses, request_id_from
from platform_api.models.common import PageResponse, PaginationMeta, PaginationParams, ResponseMeta
from platform_api.scans.dependencies import (
    CampaignListParamsDependency,
    FailureListParamsDependency,
    PageListParamsDependency,
    ScanCampaignServiceDependency,
    TargetListParamsDependency,
)
from platform_api.scans.schemas import (
    CampaignActionRequest,
    CampaignVersionRequest,
    CrawlPageWithScansResponse,
    ScanCampaignCreateRequest,
    ScanCampaignResponse,
    ScanCampaignSummaryResponse,
    ScanCampaignUpdateRequest,
    ScanFailureResponse,
    ScanTargetCreateRequest,
    ScanTargetResponse,
)

router = APIRouter(prefix="/projects/{project_id}/scan-campaigns")


@router.post(
    "",
    response_model=ScanCampaignResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createScanCampaign",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def create_scan_campaign(
    project_id: UUID,
    payload: ScanCampaignCreateRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> ScanCampaignResponse:
    return await service.create(
        project_id, payload, owner_id=user.id, request_id=request_id_from(request)
    )


@router.get(
    "",
    response_model=PageResponse[ScanCampaignResponse],
    operation_id="listScanCampaigns",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_scan_campaigns(
    project_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
    params: CampaignListParamsDependency,
) -> PageResponse[ScanCampaignResponse]:
    page = await service.list(project_id, owner_id=user.id, params=params)
    return _page_response(request, page.items, page.total, params)


@router.get(
    "/{campaign_id}",
    response_model=ScanCampaignResponse,
    operation_id="getScanCampaign",
    responses=problem_responses(401, 404, 503),
)
async def get_scan_campaign(
    project_id: UUID,
    campaign_id: UUID,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> ScanCampaignResponse:
    return await service.get(project_id, campaign_id, owner_id=user.id)


@router.patch(
    "/{campaign_id}",
    response_model=ScanCampaignResponse,
    operation_id="updateScanCampaign",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def update_scan_campaign(
    project_id: UUID,
    campaign_id: UUID,
    payload: ScanCampaignUpdateRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> ScanCampaignResponse:
    return await service.update(
        project_id,
        campaign_id,
        payload,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.delete(
    "/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteDraftScanCampaign",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def delete_scan_campaign(
    project_id: UUID,
    campaign_id: UUID,
    payload: CampaignVersionRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> Response:
    await service.delete(
        project_id,
        campaign_id,
        version=payload.version,
        owner_id=user.id,
        request_id=request_id_from(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{campaign_id}/start",
    response_model=ScanCampaignResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="startScanCampaign",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def start_scan_campaign(
    project_id: UUID,
    campaign_id: UUID,
    payload: CampaignActionRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> ScanCampaignResponse:
    return await service.start(
        project_id,
        campaign_id,
        version=payload.version,
        idempotency_key=payload.idempotency_key,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.post(
    "/{campaign_id}/pause",
    response_model=ScanCampaignResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="pauseScanCampaign",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def pause_scan_campaign(
    project_id: UUID,
    campaign_id: UUID,
    payload: CampaignVersionRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> ScanCampaignResponse:
    return await service.pause(
        project_id,
        campaign_id,
        version=payload.version,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.post(
    "/{campaign_id}/resume",
    response_model=ScanCampaignResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="resumeScanCampaign",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def resume_scan_campaign(
    project_id: UUID,
    campaign_id: UUID,
    payload: CampaignVersionRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> ScanCampaignResponse:
    return await service.resume(
        project_id,
        campaign_id,
        version=payload.version,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.post(
    "/{campaign_id}/cancel",
    response_model=ScanCampaignResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="cancelScanCampaign",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def cancel_scan_campaign(
    project_id: UUID,
    campaign_id: UUID,
    payload: CampaignVersionRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> ScanCampaignResponse:
    return await service.cancel(
        project_id,
        campaign_id,
        version=payload.version,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.post(
    "/{campaign_id}/retry-failures",
    response_model=ScanCampaignResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="retryScanCampaignFailures",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def retry_scan_campaign_failures(
    project_id: UUID,
    campaign_id: UUID,
    payload: CampaignActionRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> ScanCampaignResponse:
    return await service.retry_failures(
        project_id,
        campaign_id,
        version=payload.version,
        idempotency_key=payload.idempotency_key,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.get(
    "/{campaign_id}/summary",
    response_model=ScanCampaignSummaryResponse,
    operation_id="getScanCampaignSummary",
    responses=problem_responses(401, 404, 503),
)
async def get_scan_campaign_summary(
    project_id: UUID,
    campaign_id: UUID,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> ScanCampaignSummaryResponse:
    return await service.summary(project_id, campaign_id, owner_id=user.id)


@router.post(
    "/{campaign_id}/targets",
    response_model=ScanTargetResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="addScanCampaignTarget",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def add_scan_campaign_target(
    project_id: UUID,
    campaign_id: UUID,
    payload: ScanTargetCreateRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> ScanTargetResponse:
    return await service.add_target(
        project_id,
        campaign_id,
        payload,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.get(
    "/{campaign_id}/targets",
    response_model=PageResponse[ScanTargetResponse],
    operation_id="listScanCampaignTargets",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_scan_campaign_targets(
    project_id: UUID,
    campaign_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
    params: TargetListParamsDependency,
) -> PageResponse[ScanTargetResponse]:
    page = await service.list_targets(project_id, campaign_id, owner_id=user.id, params=params)
    return _page_response(request, page.items, page.total, params)


@router.delete(
    "/{campaign_id}/targets/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteDraftScanCampaignTarget",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def delete_scan_campaign_target(
    project_id: UUID,
    campaign_id: UUID,
    target_id: UUID,
    payload: CampaignVersionRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> Response:
    await service.delete_target(
        project_id,
        campaign_id,
        target_id,
        version=payload.version,
        owner_id=user.id,
        request_id=request_id_from(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{campaign_id}/pages",
    response_model=PageResponse[CrawlPageWithScansResponse],
    operation_id="listScanCampaignPages",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_scan_campaign_pages(
    project_id: UUID,
    campaign_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
    params: PageListParamsDependency,
) -> PageResponse[CrawlPageWithScansResponse]:
    page = await service.list_pages(project_id, campaign_id, owner_id=user.id, params=params)
    return _page_response(request, page.items, page.total, params)


@router.get(
    "/{campaign_id}/failures",
    response_model=PageResponse[ScanFailureResponse],
    operation_id="listScanCampaignFailures",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_scan_campaign_failures(
    project_id: UUID,
    campaign_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
    params: FailureListParamsDependency,
) -> PageResponse[ScanFailureResponse]:
    page = await service.list_failures(project_id, campaign_id, owner_id=user.id, params=params)
    return _page_response(request, page.items, page.total, params)


def _page_response[ItemT, ParamsT: PaginationParams](
    request: Request,
    items: tuple[ItemT, ...],
    total: int,
    params: ParamsT,
) -> PageResponse[ItemT]:
    return PageResponse(
        items=list(items),
        pagination=PaginationMeta.from_params(params, total),
        meta=ResponseMeta(request_id=request_id_from(request)),
    )
