"""Explicit dataset repository and service composition."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from platform_api.dependencies import DatabaseTransactionDependency
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.repositories import SqlAlchemyAuditLogRepository

from .repository import DatasetRepository
from .service import DatasetService


async def dataset_service_dependency(session: DatabaseTransactionDependency) -> DatasetService:
    return DatasetService(
        DatasetRepository(session), AuditLogService(SqlAlchemyAuditLogRepository(session))
    )


DatasetServiceDependency = Annotated[DatasetService, Depends(dataset_service_dependency)]
