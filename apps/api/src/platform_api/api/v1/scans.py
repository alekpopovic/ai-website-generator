"""Project-owned scan campaign CRUD, projections, and workflow controls."""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from platform_api.auth.dependencies import CurrentUserDependency
from platform_api.dependencies import SettingsDependency
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
    CampaignVersionRequest,
    CrawlPageResponse,
    CrawlPageWithScansResponse,
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
    TargetImportSource,
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
