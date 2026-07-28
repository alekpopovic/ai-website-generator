"""Explicit scan-artifact service composition."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from platform_api.artifacts.repository import ScanArtifactRepository
from platform_api.artifacts.service import ScanArtifactService
from platform_api.dependencies import (
    AfterCommitActionsDependency,
    DatabaseTransactionDependency,
    ObjectStorageDependency,
    WorkflowDispatcherDependency,
)
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.repositories import SqlAlchemyAuditLogRepository


async def scan_artifact_service_dependency(
    session: DatabaseTransactionDependency,
    storage: ObjectStorageDependency,
    dispatcher: WorkflowDispatcherDependency,
    after_commit: AfterCommitActionsDependency,
) -> ScanArtifactService:
    return ScanArtifactService(
        ScanArtifactRepository(session),
        storage,
        AuditLogService(SqlAlchemyAuditLogRepository(session)),
        dispatcher,
        after_commit,
    )


ScanArtifactServiceDependency = Annotated[
    ScanArtifactService, Depends(scan_artifact_service_dependency)
]
