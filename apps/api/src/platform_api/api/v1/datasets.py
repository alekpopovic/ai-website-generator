"""Project-owned dataset CRUD, versioning, sealing, and statistics APIs."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from platform_api.auth.dependencies import CurrentUserDependency
from platform_api.datasets.dependencies import DatasetServiceDependency
from platform_api.datasets.schemas import (
    DatasetCreateRequest,
    DatasetItemResponse,
    DatasetResponse,
    DatasetUpdateRequest,
    DatasetVersionCreateRequest,
    DatasetVersionDetailResponse,
    DatasetVersionResponse,
    DatasetVersionUpdateRequest,
    SealDatasetVersionRequest,
)
from platform_api.errors import problem_responses, request_id_from
from platform_api.models.common import PageResponse, PaginationMeta, PaginationParams, ResponseMeta

router = APIRouter(prefix="/projects/{project_id}/datasets")


@router.post(
    "",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createDataset",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def create_dataset(
    project_id: UUID,
    payload: DatasetCreateRequest,
    request: Request,
    user: CurrentUserDependency,
    service: DatasetServiceDependency,
) -> DatasetResponse:
    return await service.create(
        project_id, payload, owner_id=user.id, request_id=request_id_from(request)
    )


@router.get(
    "",
    response_model=PageResponse[DatasetResponse],
    operation_id="listDatasets",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_datasets(
    project_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: DatasetServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageResponse[DatasetResponse]:
    page = await service.list(project_id, owner_id=user.id, limit=limit, offset=offset)
    return _page(request, page.items, page.total, offset, limit)


@router.get(
    "/{dataset_id}",
    response_model=DatasetResponse,
    operation_id="getDataset",
    responses=problem_responses(401, 404, 503),
)
async def get_dataset(
    project_id: UUID,
    dataset_id: UUID,
    user: CurrentUserDependency,
    service: DatasetServiceDependency,
) -> DatasetResponse:
    return await service.get(project_id, dataset_id, user.id)


@router.patch(
    "/{dataset_id}",
    response_model=DatasetResponse,
    operation_id="updateDataset",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def update_dataset(
    project_id: UUID,
    dataset_id: UUID,
    payload: DatasetUpdateRequest,
    request: Request,
    user: CurrentUserDependency,
    service: DatasetServiceDependency,
) -> DatasetResponse:
    return await service.update(
        project_id,
        dataset_id,
        payload,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.delete(
    "/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteDataset",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def delete_dataset(
    project_id: UUID,
    dataset_id: UUID,
    version: Annotated[int, Query(ge=1)],
    request: Request,
    user: CurrentUserDependency,
    service: DatasetServiceDependency,
) -> Response:
    await service.delete(
        project_id,
        dataset_id,
        version=version,
        owner_id=user.id,
        request_id=request_id_from(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{dataset_id}/versions",
    response_model=DatasetVersionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createDatasetVersion",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def create_dataset_version(
    project_id: UUID,
    dataset_id: UUID,
    payload: DatasetVersionCreateRequest,
    request: Request,
    user: CurrentUserDependency,
    service: DatasetServiceDependency,
) -> DatasetVersionResponse:
    return await service.create_version(
        project_id,
        dataset_id,
        payload,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.get(
    "/{dataset_id}/versions",
    response_model=PageResponse[DatasetVersionResponse],
    operation_id="listDatasetVersions",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_dataset_versions(
    project_id: UUID,
    dataset_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: DatasetServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageResponse[DatasetVersionResponse]:
    page = await service.list_versions(
        project_id, dataset_id, owner_id=user.id, limit=limit, offset=offset
    )
    return _page(request, page.items, page.total, offset, limit)


@router.get(
    "/{dataset_id}/versions/{version_id}",
    response_model=DatasetVersionDetailResponse,
    operation_id="getDatasetVersion",
    responses=problem_responses(401, 404, 503),
)
async def get_dataset_version(
    project_id: UUID,
    dataset_id: UUID,
    version_id: UUID,
    user: CurrentUserDependency,
    service: DatasetServiceDependency,
) -> DatasetVersionDetailResponse:
    return await service.detail(project_id, dataset_id, version_id, user.id)


@router.patch(
    "/{dataset_id}/versions/{version_id}",
    response_model=DatasetVersionResponse,
    operation_id="updateDatasetVersion",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def update_dataset_version(
    project_id: UUID,
    dataset_id: UUID,
    version_id: UUID,
    payload: DatasetVersionUpdateRequest,
    request: Request,
    user: CurrentUserDependency,
    service: DatasetServiceDependency,
) -> DatasetVersionResponse:
    return await service.update_version(
        project_id,
        dataset_id,
        version_id,
        payload,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.post(
    "/{dataset_id}/versions/{version_id}/seal",
    response_model=DatasetVersionDetailResponse,
    operation_id="sealDatasetVersion",
    responses=problem_responses(401, 404, 409, 422, 503),
)
async def seal_dataset_version(
    project_id: UUID,
    dataset_id: UUID,
    version_id: UUID,
    payload: SealDatasetVersionRequest,
    request: Request,
    user: CurrentUserDependency,
    service: DatasetServiceDependency,
) -> DatasetVersionDetailResponse:
    return await service.seal(
        project_id,
        dataset_id,
        version_id,
        payload,
        owner_id=user.id,
        request_id=request_id_from(request),
    )


@router.get(
    "/{dataset_id}/versions/{version_id}/items",
    response_model=PageResponse[DatasetItemResponse],
    operation_id="listDatasetItems",
    responses=problem_responses(401, 404, 422, 503),
)
async def list_dataset_items(
    project_id: UUID,
    dataset_id: UUID,
    version_id: UUID,
    request: Request,
    user: CurrentUserDependency,
    service: DatasetServiceDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageResponse[DatasetItemResponse]:
    page = await service.items(
        project_id,
        dataset_id,
        version_id,
        owner_id=user.id,
        limit=limit,
        offset=offset,
    )
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
