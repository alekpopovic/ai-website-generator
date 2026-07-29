"""Owner-scoped normalized profile and section-pattern review endpoints."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from platform_api.analysis.dependencies import AnalysisProfileServiceDependency
from platform_api.analysis.repository import PatternFilters
from platform_api.analysis.schemas import (
    AnalysisRunResponse,
    BulkCurationRequest,
    CurationRequest,
    PageProfileResponse,
    SectionPatternDetailResponse,
    SectionPatternFacetsResponse,
    SectionPatternResponse,
    WebsiteProfileResponse,
)
from platform_api.auth.dependencies import CurrentUserDependency
from platform_api.embedding.dependencies import EmbeddingRunServiceDependency
from platform_api.embedding.schemas import (
    EmbeddingFailureResponse,
    EmbeddingRunCreateRequest,
    EmbeddingRunResponse,
)
from platform_api.errors import problem_responses, request_id_from
from platform_api.models.common import PageResponse, PaginationMeta, PaginationParams, ResponseMeta

router = APIRouter(prefix="/projects/{project_id}/analysis")


@router.get(
    "/page-profiles",
    response_model=PageResponse[PageProfileResponse],
    operation_id="listPageProfiles",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_page_profiles(
    project_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    current_only: bool = True,
) -> PageResponse[PageProfileResponse]:
    page = await service.list_pages(
        project_id, user.id, limit=limit, offset=offset, current_only=current_only
    )
    return _page(request, page.items, page.total, offset, limit)


@router.get(
    "/page-profiles/{profile_id}",
    response_model=PageProfileResponse,
    operation_id="getPageProfile",
    responses=problem_responses(401, 404, 503),
)
async def get_page_profile(
    project_id: UUID,
    profile_id: UUID,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
) -> PageProfileResponse:
    return await service.get_page(project_id, profile_id, user.id)


@router.patch(
    "/page-profiles/{profile_id}/curation",
    response_model=PageProfileResponse,
    operation_id="curatePageProfile",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def curate_page_profile(
    project_id: UUID,
    profile_id: UUID,
    payload: CurationRequest,
    request: Request,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
) -> PageProfileResponse:
    return await service.curate_page(
        project_id, profile_id, payload, owner_id=user.id, request_id=request_id_from(request)
    )


@router.get(
    "/website-profiles",
    response_model=PageResponse[WebsiteProfileResponse],
    operation_id="listWebsiteProfiles",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_website_profiles(
    project_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    current_only: bool = True,
) -> PageResponse[WebsiteProfileResponse]:
    page = await service.list_websites(
        project_id, user.id, limit=limit, offset=offset, current_only=current_only
    )
    return _page(request, page.items, page.total, offset, limit)


@router.get(
    "/website-profiles/{profile_id}",
    response_model=WebsiteProfileResponse,
    operation_id="getWebsiteProfile",
    responses=problem_responses(401, 404, 503),
)
async def get_website_profile(
    project_id: UUID,
    profile_id: UUID,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
) -> WebsiteProfileResponse:
    return await service.get_website(project_id, profile_id, user.id)


@router.patch(
    "/website-profiles/{profile_id}/curation",
    response_model=WebsiteProfileResponse,
    operation_id="curateWebsiteProfile",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def curate_website_profile(
    project_id: UUID,
    profile_id: UUID,
    payload: CurationRequest,
    request: Request,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
) -> WebsiteProfileResponse:
    return await service.curate_website(
        project_id, profile_id, payload, owner_id=user.id, request_id=request_id_from(request)
    )


@router.get(
    "/section-patterns",
    response_model=PageResponse[SectionPatternResponse],
    operation_id="listSectionPatterns",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_section_patterns(
    project_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    domain: Annotated[str | None, Query(min_length=1, max_length=253)] = None,
    category: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    page_type: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    section_type: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    layout: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    language: Annotated[str | None, Query(min_length=2, max_length=35)] = None,
    minimum_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    maximum_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    approval_state: Literal["needs_review", "approved", "rejected"] | None = None,
    provenance_state: Literal["authorized", "restricted", "removal_pending", "removed"]
    | None = None,
) -> PageResponse[SectionPatternResponse]:
    page = await service.list_patterns(
        project_id,
        user.id,
        limit=limit,
        offset=offset,
        filters=PatternFilters(
            domain=domain,
            category=category,
            page_type=page_type,
            section_type=section_type,
            layout=layout,
            language=language,
            minimum_confidence=minimum_confidence,
            maximum_confidence=maximum_confidence,
            approval_state=approval_state,
            provenance_state=provenance_state,
        ),
    )
    return _page(request, page.items, page.total, offset, limit)


@router.get(
    "/section-patterns/facets",
    response_model=SectionPatternFacetsResponse,
    operation_id="getSectionPatternFacets",
    responses=problem_responses(401, 404, 422, 503),
)
async def get_section_pattern_facets(
    project_id: UUID,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
    domain: Annotated[str | None, Query(min_length=1, max_length=253)] = None,
    category: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    page_type: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    section_type: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    layout: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    language: Annotated[str | None, Query(min_length=2, max_length=35)] = None,
    minimum_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    maximum_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    approval_state: Literal["needs_review", "approved", "rejected"] | None = None,
    provenance_state: Literal["authorized", "restricted", "removal_pending", "removed"]
    | None = None,
) -> SectionPatternFacetsResponse:
    return await service.pattern_facets(
        project_id,
        user.id,
        filters=PatternFilters(
            domain=domain,
            category=category,
            page_type=page_type,
            section_type=section_type,
            layout=layout,
            language=language,
            minimum_confidence=minimum_confidence,
            maximum_confidence=maximum_confidence,
            approval_state=approval_state,
            provenance_state=provenance_state,
        ),
    )


@router.patch(
    "/section-patterns/bulk-curation",
    response_model=list[SectionPatternResponse],
    operation_id="bulkCurateSectionPatterns",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def bulk_curate_section_patterns(
    project_id: UUID,
    payload: BulkCurationRequest,
    request: Request,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
) -> tuple[SectionPatternResponse, ...]:
    return await service.curate_patterns_bulk(
        project_id,
        payload,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.get(
    "/section-patterns/{pattern_id}",
    response_model=SectionPatternResponse,
    operation_id="getSectionPattern",
    responses=problem_responses(401, 404, 503),
)
async def get_section_pattern(
    project_id: UUID,
    pattern_id: UUID,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
) -> SectionPatternResponse:
    return await service.get_pattern(project_id, pattern_id, user.id)


@router.get(
    "/section-patterns/{pattern_id}/detail",
    response_model=SectionPatternDetailResponse,
    operation_id="getSectionPatternDetail",
    responses=problem_responses(401, 404, 503),
)
async def get_section_pattern_detail(
    project_id: UUID,
    pattern_id: UUID,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
) -> SectionPatternDetailResponse:
    return await service.get_pattern_detail(project_id, pattern_id, user.id)


@router.patch(
    "/section-patterns/{pattern_id}/curation",
    response_model=SectionPatternResponse,
    operation_id="curateSectionPattern",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def curate_section_pattern(
    project_id: UUID,
    pattern_id: UUID,
    payload: CurationRequest,
    request: Request,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
) -> SectionPatternResponse:
    return await service.curate_pattern(
        project_id, pattern_id, payload, owner_id=user.id, request_id=request_id_from(request)
    )


@router.get(
    "/runs",
    response_model=PageResponse[AnalysisRunResponse],
    operation_id="listAnalysisRuns",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_analysis_runs(
    project_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: AnalysisProfileServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageResponse[AnalysisRunResponse]:
    page = await service.list_runs(project_id, user.id, limit=limit, offset=offset)
    return _page(request, page.items, page.total, offset, limit)


def _page[ItemT](
    request: Request, items: tuple[ItemT, ...], total: int, offset: int, limit: int
) -> PageResponse[ItemT]:
    params = PaginationParams(offset=offset, limit=limit)
    return PageResponse(
        items=list(items),
        pagination=PaginationMeta.from_params(params, total),
        meta=ResponseMeta(request_id=request_id_from(request)),
    )


@router.post(
    "/embedding-runs",
    response_model=EmbeddingRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createEmbeddingRun",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def create_embedding_run(
    project_id: UUID,
    payload: EmbeddingRunCreateRequest,
    request: Request,
    user: CurrentUserDependency,
    service: EmbeddingRunServiceDependency,
) -> EmbeddingRunResponse:
    return await service.create(
        project_id,
        payload,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.get(
    "/embedding-runs",
    response_model=PageResponse[EmbeddingRunResponse],
    operation_id="listEmbeddingRuns",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_embedding_runs(
    project_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: EmbeddingRunServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageResponse[EmbeddingRunResponse]:
    page = await service.list(project_id, owner_id=user.id, limit=limit, offset=offset)
    return _page(request, page.items, page.total, offset, limit)


@router.get(
    "/embedding-runs/{run_id}",
    response_model=EmbeddingRunResponse,
    operation_id="getEmbeddingRun",
    responses=problem_responses(401, 404, 503),
)
async def get_embedding_run(
    project_id: UUID,
    run_id: UUID,
    user: CurrentUserDependency,
    service: EmbeddingRunServiceDependency,
) -> EmbeddingRunResponse:
    return await service.get(project_id, run_id, owner_id=user.id)


@router.get(
    "/embedding-runs/{run_id}/failures",
    response_model=PageResponse[EmbeddingFailureResponse],
    operation_id="listEmbeddingRunFailures",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_embedding_run_failures(
    project_id: UUID,
    run_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: EmbeddingRunServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageResponse[EmbeddingFailureResponse]:
    page = await service.failures(
        project_id,
        run_id,
        owner_id=user.id,
        limit=limit,
        offset=offset,
    )
    return _page(request, page.items, page.total, offset, limit)
