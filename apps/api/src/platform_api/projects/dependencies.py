"""Explicit project-domain dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query

from platform_api.dependencies import DatabaseTransactionDependency
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.repositories import ProjectRepository, SqlAlchemyAuditLogRepository
from platform_api.projects.schemas import ProjectListParams, ProjectSort, ProjectStatus, SortOrder
from platform_api.projects.service import ProjectService


async def project_service_dependency(session: DatabaseTransactionDependency) -> ProjectService:
    """Compose a project service inside the request transaction."""
    return ProjectService(
        ProjectRepository(session), AuditLogService(SqlAlchemyAuditLogRepository(session))
    )


ProjectServiceDependency = Annotated[ProjectService, Depends(project_service_dependency)]


async def project_list_params_dependency(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    status: Annotated[ProjectStatus | None, Query()] = None,
    sort_by: Annotated[ProjectSort, Query()] = "updated_at",
    sort_order: Annotated[SortOrder, Query()] = "desc",
) -> ProjectListParams:
    """Build project query parameters without a synchronous dependency hop."""
    return ProjectListParams(
        offset=offset,
        limit=limit,
        search=search,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )


ProjectListParamsDependency = Annotated[ProjectListParams, Depends(project_list_params_dependency)]
