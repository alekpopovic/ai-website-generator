"""User-owned project CRUD and lifecycle routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from platform_api.auth.dependencies import CurrentUserDependency
from platform_api.errors import problem_responses, request_id_from
from platform_api.models.common import PageResponse, PaginationMeta, ResponseMeta
from platform_api.projects.dependencies import ProjectListParamsDependency, ProjectServiceDependency
from platform_api.projects.schemas import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    ProjectVersionRequest,
)

router = APIRouter(prefix="/projects")


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createProject",
    responses=problem_responses(401, 409, 422, 503),
)
async def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ProjectServiceDependency,
) -> ProjectResponse:
    return await service.create(payload, owner_id=user.id, request_id=request_id_from(request))


@router.get(
    "",
    response_model=PageResponse[ProjectResponse],
    operation_id="listProjects",
    responses=problem_responses(401, 422, 503),
)
async def list_projects(
    request: Request,
    user: CurrentUserDependency,
    service: ProjectServiceDependency,
    params: ProjectListParamsDependency,
) -> PageResponse[ProjectResponse]:
    page = await service.list(owner_id=user.id, params=params)
    return PageResponse(
        items=list(page.items),
        pagination=PaginationMeta.from_params(params, page.total),
        meta=ResponseMeta(request_id=request_id_from(request)),
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    operation_id="getProject",
    responses=problem_responses(401, 404, 503),
)
async def get_project(
    project_id: UUID,
    user: CurrentUserDependency,
    service: ProjectServiceDependency,
) -> ProjectResponse:
    return await service.get(project_id, owner_id=user.id)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    operation_id="updateProject",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ProjectServiceDependency,
) -> ProjectResponse:
    return await service.update(
        project_id, payload, owner_id=user.id, request_id=request_id_from(request)
    )


@router.post(
    "/{project_id}/archive",
    response_model=ProjectResponse,
    operation_id="archiveProject",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def archive_project(
    project_id: UUID,
    payload: ProjectVersionRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ProjectServiceDependency,
) -> ProjectResponse:
    return await service.archive(
        project_id,
        version=payload.version,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.post(
    "/{project_id}/restore",
    response_model=ProjectResponse,
    operation_id="restoreProject",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def restore_project(
    project_id: UUID,
    payload: ProjectVersionRequest,
    request: Request,
    user: CurrentUserDependency,
    service: ProjectServiceDependency,
) -> ProjectResponse:
    return await service.restore(
        project_id,
        version=payload.version,
        owner_id=user.id,
        request_id=request_id_from(request),
    )
