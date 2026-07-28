"""Project-owned scan campaign CRUD, projections, and workflow controls."""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from platform_api.artifacts.dependencies import ScanArtifactServiceDependency
from platform_api.artifacts.schemas import (
    ArtifactRemovalRequest,
    PresignedArtifactReadResponse,
    ScanArtifactResponse,
)
from platform_api.auth.dependencies import CurrentUserDependency
from platform_api.dependencies import ObjectStorageDependency, SettingsDependency
from platform_api.errors import ApiError, problem_responses, request_id_from
from platform_api.models.common import PageResponse, PaginationMeta, PaginationParams, ResponseMeta
from platform_api.scans.dependencies import (
    CampaignListParamsDependency,
    FailureListParamsDependency,
    PageListParamsDependency,
    ScanCampaignServiceDependency,
    ScanTargetImportServiceDependency,
    TargetListParamsDependency,
)
from platform_api.scans.schemas import (
    CampaignActionRequest,
    CampaignActivityResponse,
    CampaignVersionRequest,
    CrawlPageDetailResponse,
    CrawlPageResponse,
    CrawlPageWithScansResponse,
    DuplicateGroupResponse,
    RepresentativeDecisionResponse,
    RepresentativeOverrideRequest,
    ScanCampaignCreateRequest,
    ScanCampaignResponse,
    ScanCampaignSummaryResponse,
    ScanCampaignUpdateRequest,
    ScanFailureResponse,
    ScanTargetCreateRequest,
    ScanTargetImportCommitRequest,
    ScanTargetImportResponse,
    ScanTargetResponse,
    SelectedFailureRetryRequest,
    TargetImportSource,
    TargetSummaryResponse,
)

router = APIRouter(prefix="/projects/{project_id}/scan-campaigns")

_IMPORT_REQUEST_BODY = {
    "required": True,
    "content": {
        "text/plain": {"schema": {"type": "string", "format": "binary"}},
        "text/csv": {"schema": {"type": "string", "format": "binary"}},
        "application/csv": {"schema": {"type": "string", "format": "binary"}},
    },
}


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


@router.post(
    "/{campaign_id}/retry-selected-failures",
    response_model=ScanCampaignResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="retrySelectedScanCampaignFailures",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def retry_selected_scan_campaign_failures(
    project_id: UUID,
    campaign_id: UUID,
    payload: SelectedFailureRetryRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> ScanCampaignResponse:
    return await service.retry_selected_failures(
        project_id,
        campaign_id,
        version=payload.version,
        idempotency_key=payload.idempotency_key,
        failure_ids=payload.failure_ids,
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
    "/{campaign_id}/target-imports",
    response_model=ScanTargetImportResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="importScanCampaignTargets",
    responses=problem_responses(401, 403, 404, 409, 413, 422, 503),
    openapi_extra={"requestBody": _IMPORT_REQUEST_BODY},
)
async def import_scan_campaign_targets(
    project_id: UUID,
    campaign_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    settings: SettingsDependency,
    service: ScanTargetImportServiceDependency,
    source_type: Annotated[TargetImportSource, Query()],
    authorization_attested: Annotated[bool, Query()],
    dry_run: Annotated[bool, Query()] = True,
    filename: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    allow_ip_literals: Annotated[bool, Query()] = False,
) -> ScanTargetImportResponse:
    administrators = {str(email).casefold() for email in settings.security.administrator_emails}
    if allow_ip_literals and user.email.casefold() not in administrators:
        raise ApiError(
            403,
            "administrator_required",
            "Administrator access is required to import public IP literals.",
        )
    media_type = (request.headers.get("content-type") or "text/plain").split(";", 1)[0]
    allowed_media_types = (
        {"text/csv", "application/csv", "application/octet-stream"}
        if source_type == "csv"
        else {"text/plain", "application/octet-stream"}
    )
    if media_type not in allowed_media_types:
        raise ApiError(
            422,
            "scan_target_import_media_type_invalid",
            "The request content type does not match the selected import source.",
        )
    return await service.import_stream(
        project_id,
        campaign_id,
        request.stream(),
        source_type=source_type,
        filename=filename,
        media_type=media_type,
        dry_run=dry_run,
        authorization_attested=authorization_attested,
        allow_ip_literals=allow_ip_literals,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.get(
    "/{campaign_id}/target-imports/{import_id}",
    response_model=ScanTargetImportResponse,
    operation_id="getScanTargetImport",
    responses=problem_responses(401, 404, 503),
)
async def get_scan_target_import(
    project_id: UUID,
    campaign_id: UUID,
    import_id: UUID,
    user: CurrentUserDependency,
    service: ScanTargetImportServiceDependency,
) -> ScanTargetImportResponse:
    return await service.get(project_id, campaign_id, import_id, owner_id=user.id)


@router.post(
    "/{campaign_id}/target-imports/{import_id}/commit",
    response_model=ScanTargetImportResponse,
    operation_id="commitScanTargetImport",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def commit_scan_target_import(
    project_id: UUID,
    campaign_id: UUID,
    import_id: UUID,
    payload: ScanTargetImportCommitRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanTargetImportServiceDependency,
) -> ScanTargetImportResponse:
    return await service.commit(
        project_id,
        campaign_id,
        import_id,
        expected_version=payload.version,
        authorization_attested=payload.authorization_attested,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.get(
    "/{campaign_id}/target-imports/{import_id}/errors.csv",
    operation_id="exportScanTargetImportErrors",
    responses=problem_responses(401, 404, 503),
)
async def export_scan_target_import_errors(
    project_id: UUID,
    campaign_id: UUID,
    import_id: UUID,
    user: CurrentUserDependency,
    service: ScanTargetImportServiceDependency,
) -> StreamingResponse:
    async def content() -> AsyncIterator[str]:
        yield _csv_line(["row_number", "target", "outcome", "reason_code", "reason_message"])
        async for row in service.error_rows(project_id, campaign_id, import_id, owner_id=user.id):
            yield _csv_line(
                [
                    str(row.row_number),
                    _spreadsheet_safe(row.raw_value),
                    row.outcome,
                    row.reason_code or "",
                    row.reason_message or "",
                ]
            )

    return StreamingResponse(
        content(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="scan-target-import-{import_id}-errors.csv"',
            "X-Content-Type-Options": "nosniff",
        },
    )


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


@router.get(
    "/{campaign_id}/targets/{target_id}/summary",
    response_model=TargetSummaryResponse,
    operation_id="getScanCampaignTargetSummary",
    responses=problem_responses(401, 404, 503),
)
async def get_scan_campaign_target_summary(
    project_id: UUID,
    campaign_id: UUID,
    target_id: UUID,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> TargetSummaryResponse:
    return await service.target_summary(project_id, campaign_id, target_id, owner_id=user.id)


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
    "/{campaign_id}/pages/{page_id}",
    response_model=CrawlPageDetailResponse,
    operation_id="getScanCampaignPage",
    responses=problem_responses(401, 404, 503),
)
async def get_scan_campaign_page(
    project_id: UUID,
    campaign_id: UUID,
    page_id: UUID,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
    artifacts: ScanArtifactServiceDependency,
) -> CrawlPageDetailResponse:
    page, page_scans, failures = await service.page_detail(
        project_id, campaign_id, page_id, owner_id=user.id
    )
    manifest = await artifacts.list_for_page(project_id, campaign_id, page_id, owner_id=user.id)
    return CrawlPageDetailResponse(
        page=page, page_scans=page_scans, failures=failures, artifacts=manifest
    )


@router.get(
    "/{campaign_id}/duplicate-groups",
    response_model=PageResponse[DuplicateGroupResponse],
    operation_id="listScanCampaignDuplicateGroups",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_scan_campaign_duplicate_groups(
    project_id: UUID,
    campaign_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
    group_type: Annotated[Literal["exact", "near", "template"], Query()] = "exact",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageResponse[DuplicateGroupResponse]:
    page = await service.duplicate_groups(
        project_id,
        campaign_id,
        owner_id=user.id,
        group_type=group_type,
        limit=limit,
        offset=offset,
    )
    return _page_response(
        request, page.items, page.total, PaginationParams(offset=offset, limit=limit)
    )


@router.get(
    "/{campaign_id}/representative-decisions",
    response_model=PageResponse[RepresentativeDecisionResponse],
    operation_id="listScanCampaignRepresentativeDecisions",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_scan_campaign_representative_decisions(
    project_id: UUID,
    campaign_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageResponse[RepresentativeDecisionResponse]:
    page = await service.representative_decisions(
        project_id, campaign_id, owner_id=user.id, limit=limit, offset=offset
    )
    return _page_response(
        request, page.items, page.total, PaginationParams(offset=offset, limit=limit)
    )


@router.get(
    "/{campaign_id}/activity",
    response_model=PageResponse[CampaignActivityResponse],
    operation_id="listScanCampaignActivity",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_scan_campaign_activity(
    project_id: UUID,
    campaign_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageResponse[CampaignActivityResponse]:
    page = await service.activity(
        project_id, campaign_id, owner_id=user.id, limit=limit, offset=offset
    )
    return _page_response(
        request, page.items, page.total, PaginationParams(offset=offset, limit=limit)
    )


@router.get(
    "/{campaign_id}/pages/{page_id}/artifacts",
    response_model=list[ScanArtifactResponse],
    operation_id="listScanPageArtifacts",
    responses=problem_responses(401, 404, 503),
)
async def list_scan_page_artifacts(
    project_id: UUID,
    campaign_id: UUID,
    page_id: UUID,
    user: CurrentUserDependency,
    service: ScanArtifactServiceDependency,
) -> tuple[ScanArtifactResponse, ...]:
    return await service.list_for_page(project_id, campaign_id, page_id, owner_id=user.id)


@router.get(
    "/{campaign_id}/artifacts/{artifact_id}/read-url",
    response_model=PresignedArtifactReadResponse,
    operation_id="createScanArtifactReadUrl",
    responses=problem_responses(401, 403, 404, 410, 422, 503),
)
async def create_scan_artifact_read_url(
    project_id: UUID,
    campaign_id: UUID,
    artifact_id: UUID,
    user: CurrentUserDependency,
    settings: SettingsDependency,
    service: ScanArtifactServiceDependency,
    expires_seconds: Annotated[int, Query(ge=60, le=900)] = 300,
) -> PresignedArtifactReadResponse:
    administrators = {str(email).casefold() for email in settings.security.administrator_emails}
    return await service.presign_read(
        project_id,
        campaign_id,
        artifact_id,
        owner_id=user.id,
        administrator=user.email.casefold() in administrators,
        expires_seconds=expires_seconds,
    )


@router.get(
    "/{campaign_id}/artifacts/{artifact_id}/screenshot",
    operation_id="viewScanArtifactScreenshot",
    responses=problem_responses(401, 404, 410, 503),
)
async def view_scan_artifact_screenshot(
    project_id: UUID,
    campaign_id: UUID,
    artifact_id: UUID,
    user: CurrentUserDependency,
    service: ScanArtifactServiceDependency,
    storage: ObjectStorageDependency,
) -> StreamingResponse:
    screenshot = await service.authorize_screenshot(
        project_id, campaign_id, artifact_id, owner_id=user.id
    )
    return StreamingResponse(
        storage.stream_download(
            screenshot.location,
            expected_sha256=screenshot.artifact.sha256,
        ),
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="scan-{artifact_id}.png"',
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cross-Origin-Resource-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{campaign_id}/artifacts/{artifact_id}/removal-request",
    response_model=ScanArtifactResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="requestScanArtifactRemoval",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def request_scan_artifact_removal(
    project_id: UUID,
    campaign_id: UUID,
    artifact_id: UUID,
    payload: ArtifactRemovalRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanArtifactServiceDependency,
) -> ScanArtifactResponse:
    return await service.request_removal(
        project_id,
        campaign_id,
        artifact_id,
        payload,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.put(
    "/{campaign_id}/pages/{page_id}/representative",
    response_model=CrawlPageResponse,
    operation_id="overrideScanCampaignPageRepresentative",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def override_scan_campaign_page_representative(
    project_id: UUID,
    campaign_id: UUID,
    page_id: UUID,
    payload: RepresentativeOverrideRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ScanCampaignServiceDependency,
) -> CrawlPageResponse:
    return await service.override_representative(
        project_id,
        campaign_id,
        page_id,
        payload,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


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


def _csv_line(values: list[str]) -> str:
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\r\n").writerow(values)
    return output.getvalue()


def _spreadsheet_safe(value: str) -> str:
    return f"'{value}" if value.lstrip().startswith(("=", "+", "-", "@")) else value
