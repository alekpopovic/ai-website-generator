"""Dataset ownership, draft lifecycle, deterministic sealing, and statistics."""

from __future__ import annotations

from http import HTTPStatus
from typing import cast
from uuid import UUID

from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.json import JsonValue
from platform_api.persistence.models import (
    Dataset,
    DatasetQualityReport,
    DatasetVersion,
)
from platform_api.persistence.pagination import Page

from .repository import DatasetRepository
from .schemas import (
    DatasetCreateRequest,
    DatasetItemResponse,
    DatasetQualityReportResponse,
    DatasetResponse,
    DatasetUpdateRequest,
    DatasetVersionCreateRequest,
    DatasetVersionDetailResponse,
    DatasetVersionResponse,
    DatasetVersionUpdateRequest,
    SelectionPolicy,
)


class DatasetService:
    def __init__(self, repository: DatasetRepository, audit: AuditLogService) -> None:
        self._repository = repository
        self._audit = audit

    async def create(
        self,
        project_id: UUID,
        payload: DatasetCreateRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> DatasetResponse:
        await self._project(project_id, owner_id)
        if await self._repository.name_exists(project_id, payload.name):
            raise self._conflict(
                "dataset_name_conflict", "A dataset with this name already exists."
            )
        policy = SelectionPolicy.model_validate(
            {field: getattr(payload, field) for field in SelectionPolicy.model_fields}
        )
        entity = Dataset(
            project_id=project_id,
            name=payload.name,
            description=payload.description,
            purpose=payload.purpose,
            status="active",
            created_by_user_id=owner_id,
            **_policy_columns(policy),
        )
        self._repository.add(entity)
        await self._repository.flush()
        self._record("created", entity.id, owner_id, request_id)
        return _dataset_response(entity)

    async def list(
        self, project_id: UUID, *, owner_id: UUID, limit: int, offset: int
    ) -> Page[DatasetResponse]:
        await self._project(project_id, owner_id)
        page = await self._repository.dataset_page(project_id, owner_id, limit=limit, offset=offset)
        return Page(
            items=tuple(_dataset_response(entity) for entity in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def get(self, project_id: UUID, dataset_id: UUID, owner_id: UUID) -> DatasetResponse:
        return _dataset_response(await self._dataset(project_id, dataset_id, owner_id))

    async def update(
        self,
        project_id: UUID,
        dataset_id: UUID,
        payload: DatasetUpdateRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> DatasetResponse:
        entity = await self._dataset(project_id, dataset_id, owner_id, for_update=True)
        self._version(entity.version, payload.version)
        changes = payload.model_dump(exclude={"version"}, exclude_none=True)
        if "name" in changes and await self._repository.name_exists(
            project_id, cast(str, changes["name"]), exclude_id=dataset_id
        ):
            raise self._conflict(
                "dataset_name_conflict", "A dataset with this name already exists."
            )
        policy_data = _dataset_policy(entity).model_dump()
        for field in SelectionPolicy.model_fields:
            if field in changes:
                policy_data[field] = changes.pop(field)
        policy = SelectionPolicy.model_validate(policy_data)
        for field, value in _policy_columns(policy).items():
            setattr(entity, field, value)
        for field, value in changes.items():
            setattr(entity, field, value)
        await self._repository.flush()
        self._record("updated", entity.id, owner_id, request_id)
        return _dataset_response(entity)

    async def delete(
        self,
        project_id: UUID,
        dataset_id: UUID,
        *,
        version: int,
        owner_id: UUID,
        request_id: str,
    ) -> None:
        entity = await self._dataset(project_id, dataset_id, owner_id, for_update=True)
        self._version(entity.version, version)
        if await self._repository.has_sealed_version(dataset_id):
            raise self._conflict(
                "dataset_has_sealed_versions",
                "Datasets with sealed versions must be archived rather than deleted.",
            )
        self._record("deleted", entity.id, owner_id, request_id)
        await self._repository.delete(entity)

    async def create_version(
        self,
        project_id: UUID,
        dataset_id: UUID,
        payload: DatasetVersionCreateRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> DatasetVersionResponse:
        dataset = await self._dataset(project_id, dataset_id, owner_id, for_update=True)
        if dataset.status != "active":
            raise self._conflict("dataset_archived", "Archived datasets cannot create versions.")
        policy = payload.selection_policy or _dataset_policy(dataset)
        entity = DatasetVersion(
            dataset_id=dataset.id,
            status="draft",
            version_number=await self._repository.next_version_number(dataset.id),
            selection_config=policy.model_dump(mode="json"),
            selection_manifest={},
            schema_version=payload.schema_version,
            embedding_version=payload.embedding_version,
            analyzer_versions=[],
            statistics={},
            created_by_user_id=owner_id,
        )
        self._repository.add(entity)
        await self._repository.flush()
        self._record("version_created", entity.id, owner_id, request_id)
        return _version_response(entity)

    async def list_versions(
        self,
        project_id: UUID,
        dataset_id: UUID,
        *,
        owner_id: UUID,
        limit: int,
        offset: int,
    ) -> Page[DatasetVersionResponse]:
        await self._dataset(project_id, dataset_id, owner_id)
        page = await self._repository.version_page(dataset_id, limit=limit, offset=offset)
        return Page(
            items=tuple(_version_response(entity) for entity in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def update_version(
        self,
        project_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        payload: DatasetVersionUpdateRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> DatasetVersionResponse:
        entity = await self._version_entity(
            project_id, dataset_id, version_id, owner_id, for_update=True
        )
        self._draft(entity)
        self._version(entity.version, payload.version)
        if payload.selection_policy is not None:
            entity.selection_config = payload.selection_policy.model_dump(mode="json")
        if payload.schema_version is not None:
            entity.schema_version = payload.schema_version
        if payload.embedding_version is not None:
            entity.embedding_version = payload.embedding_version
        await self._repository.flush()
        self._record("version_updated", entity.id, owner_id, request_id)
        return _version_response(entity)

    async def detail(
        self, project_id: UUID, dataset_id: UUID, version_id: UUID, owner_id: UUID
    ) -> DatasetVersionDetailResponse:
        dataset = await self._dataset(project_id, dataset_id, owner_id)
        entity = await self._version_entity(project_id, dataset_id, version_id, owner_id)
        report = await self._repository.latest_quality_report(version_id)
        return DatasetVersionDetailResponse(
            dataset=_dataset_response(dataset),
            version=_version_response(entity),
            quality_report=None if report is None else _report_response(report),
        )

    async def items(
        self,
        project_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        *,
        owner_id: UUID,
        limit: int,
        offset: int,
    ) -> Page[DatasetItemResponse]:
        await self._version_entity(project_id, dataset_id, version_id, owner_id)
        page = await self._repository.item_page(version_id, limit=limit, offset=offset)
        return Page(
            items=tuple(
                DatasetItemResponse.model_validate(item, from_attributes=True)
                for item in page.items
            ),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def _project(self, project_id: UUID, owner_id: UUID) -> None:
        if await self._repository.owned_project(project_id, owner_id) is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "project_not_found", "The project was not found.")

    async def _dataset(
        self, project_id: UUID, dataset_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> Dataset:
        entity = await self._repository.dataset(
            project_id, dataset_id, owner_id, for_update=for_update
        )
        if entity is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "dataset_not_found", "The dataset was not found.")
        return entity

    async def _version_entity(
        self,
        project_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> DatasetVersion:
        entity = await self._repository.version(
            project_id, dataset_id, version_id, owner_id, for_update=for_update
        )
        if entity is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "dataset_version_not_found",
                "The dataset version was not found.",
            )
        return entity

    @staticmethod
    def _version(actual: int, expected: int) -> None:
        if actual != expected:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "optimistic_concurrency_conflict",
                "The record changed since it was loaded.",
            )

    @staticmethod
    def _draft(entity: DatasetVersion) -> None:
        if entity.status != "draft":
            raise DatasetService._conflict(
                "dataset_version_sealed", "Sealed dataset versions are immutable."
            )

    @staticmethod
    def _conflict(code: str, detail: str) -> ApiError:
        return ApiError(HTTPStatus.CONFLICT, code, detail)

    def _record(
        self,
        action: str,
        resource_id: UUID,
        owner_id: UUID,
        request_id: str,
        *,
        details: object | None = None,
    ) -> None:
        self._audit.record(
            action=f"dataset.{action}",
            resource_type="dataset",
            resource_id=resource_id,
            actor_user_id=owner_id,
            request_id=request_id,
            details=details,
        )


def _policy_columns(policy: SelectionPolicy) -> dict[str, JsonValue | float | bool]:
    return {
        "source_campaign_filters": [str(value) for value in policy.source_campaign_filters],
        "category_filters": list(policy.category_filters),
        "language_filters": list(policy.language_filters),
        "item_types": list(policy.item_types),
        "minimum_confidence": policy.minimum_confidence,
        "require_approved": policy.require_approved,
        "provenance_requirements": list(policy.provenance_requirements),
    }


def _dataset_policy(entity: Dataset) -> SelectionPolicy:
    return SelectionPolicy.model_validate(
        {field: getattr(entity, field) for field in SelectionPolicy.model_fields}
    )


def _dataset_response(entity: Dataset) -> DatasetResponse:
    return DatasetResponse.model_validate(entity, from_attributes=True)


def _version_response(entity: DatasetVersion) -> DatasetVersionResponse:
    return DatasetVersionResponse.model_validate(entity, from_attributes=True)


def _report_response(entity: DatasetQualityReport) -> DatasetQualityReportResponse:
    return DatasetQualityReportResponse.model_validate(entity, from_attributes=True)
