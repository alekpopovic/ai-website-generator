"""Project business rules and ownership authorization."""

from __future__ import annotations

import re
import unicodedata
from http import HTTPStatus
from typing import Protocol
from uuid import UUID

from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.json import JsonValue, normalize_json_value
from platform_api.persistence.models import Project
from platform_api.persistence.pagination import Page
from platform_api.projects.schemas import (
    ProjectCreateRequest,
    ProjectListParams,
    ProjectResponse,
    ProjectUpdateRequest,
)


class ProjectRepositoryContract(Protocol):
    """Transaction-scoped project persistence contract."""

    def add(self, entity: Project) -> None: ...

    async def flush(self) -> None: ...

    async def owned(
        self, project_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> Project | None: ...

    async def slug_exists(
        self, owner_id: UUID, slug: str, *, exclude_id: UUID | None = None
    ) -> bool: ...

    async def owned_page(
        self,
        *,
        owner_id: UUID,
        limit: int,
        offset: int,
        search: str | None,
        status: str | None,
        sort_by: str,
        sort_order: str,
    ) -> Page[Project]: ...


class ProjectService:
    """Manage projects without ever accepting an owner from request data."""

    def __init__(self, repository: ProjectRepositoryContract, audit: AuditLogService) -> None:
        self._repository = repository
        self._audit = audit

    async def create(
        self, payload: ProjectCreateRequest, *, owner_id: UUID, request_id: str
    ) -> ProjectResponse:
        slug = await self._available_slug(owner_id, payload.slug or slugify(payload.name))
        project = Project(
            owner_id=owner_id,
            name=payload.name,
            slug=slug,
            description=payload.description,
            default_language=payload.default_language,
            default_industry=payload.default_industry,
            status="draft",
            settings=normalize_settings(payload.settings),
        )
        self._repository.add(project)
        await self._repository.flush()
        self._audit.record(
            action="project.created",
            resource_type="project",
            actor_user_id=owner_id,
            resource_id=project.id,
            request_id=request_id,
        )
        return ProjectResponse.model_validate(project)

    async def list(self, *, owner_id: UUID, params: ProjectListParams) -> Page[ProjectResponse]:
        page = await self._repository.owned_page(
            owner_id=owner_id,
            limit=params.limit,
            offset=params.offset,
            search=params.search,
            status=params.status,
            sort_by=params.sort_by,
            sort_order=params.sort_order,
        )
        return Page(
            items=tuple(ProjectResponse.model_validate(project) for project in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def get(self, project_id: UUID, *, owner_id: UUID) -> ProjectResponse:
        return ProjectResponse.model_validate(await self._owned(project_id, owner_id))

    async def update(
        self,
        project_id: UUID,
        payload: ProjectUpdateRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> ProjectResponse:
        project = await self._owned(project_id, owner_id, for_update=True)
        self._check_version(project, payload.version)
        if project.status == "archived":
            raise ApiError(HTTPStatus.CONFLICT, "project_archived", "Restore the project first.")
        changed: list[str] = []
        values = payload.model_dump(exclude={"version"}, exclude_unset=True)
        if "slug" in values:
            slug = values["slug"]
            if not isinstance(slug, str):
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_slug", "Slug is required.")
            if await self._repository.slug_exists(owner_id, slug, exclude_id=project.id):
                raise ApiError(
                    HTTPStatus.CONFLICT, "project_slug_conflict", "Slug is already used."
                )
        for field, value in values.items():
            if field == "settings":
                value = normalize_settings(value)
            setattr(project, field, value)
            changed.append(field)
        await self._repository.flush()
        self._audit.record(
            action="project.updated",
            resource_type="project",
            actor_user_id=owner_id,
            resource_id=project.id,
            request_id=request_id,
            details={"changed_fields": sorted(changed)},
        )
        return ProjectResponse.model_validate(project)

    async def archive(
        self, project_id: UUID, *, version: int, owner_id: UUID, request_id: str
    ) -> ProjectResponse:
        project = await self._owned(project_id, owner_id, for_update=True)
        self._check_version(project, version)
        if project.status == "archived":
            raise ApiError(HTTPStatus.CONFLICT, "project_already_archived", "Project is archived.")
        previous = project.status
        project.status = "archived"
        await self._repository.flush()
        self._record_lifecycle(project, owner_id, request_id, "archived", previous)
        return ProjectResponse.model_validate(project)

    async def restore(
        self, project_id: UUID, *, version: int, owner_id: UUID, request_id: str
    ) -> ProjectResponse:
        project = await self._owned(project_id, owner_id, for_update=True)
        self._check_version(project, version)
        if project.status != "archived":
            raise ApiError(HTTPStatus.CONFLICT, "project_not_archived", "Project is not archived.")
        project.status = "draft"
        await self._repository.flush()
        self._record_lifecycle(project, owner_id, request_id, "restored", "archived")
        return ProjectResponse.model_validate(project)

    async def _owned(
        self, project_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> Project:
        project = await self._repository.owned(project_id, owner_id, for_update=for_update)
        if project is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "project_not_found", "Project was not found.")
        return project

    @staticmethod
    def _check_version(project: Project, expected: int) -> None:
        if project.version != expected:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "project_version_conflict",
                "The project changed since it was loaded. Reload and try again.",
            )

    async def _available_slug(self, owner_id: UUID, base: str) -> str:
        candidate = base[:100]
        suffix = 1
        while await self._repository.slug_exists(owner_id, candidate):
            suffix += 1
            ending = f"-{suffix}"
            candidate = f"{base[: 100 - len(ending)]}{ending}"
        return candidate

    def _record_lifecycle(
        self, project: Project, owner_id: UUID, request_id: str, action: str, previous: str
    ) -> None:
        self._audit.record(
            action=f"project.{action}",
            resource_type="project",
            actor_user_id=owner_id,
            resource_id=project.id,
            request_id=request_id,
            details={"from_status": previous, "to_status": project.status},
        )


def slugify(value: str) -> str:
    """Create a deterministic lowercase ASCII project slug."""
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug[:100] or "project"


def normalize_settings(value: object) -> dict[str, JsonValue]:
    """Ensure project settings remain a JSON object rather than arbitrary JSON."""
    normalized = normalize_json_value(value)
    if not isinstance(normalized, dict):
        raise ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "invalid_project_settings",
            "Project settings must be a JSON object.",
        )
    return normalized
