"""Request-scoped embedding run control-plane composition."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from platform_api.dependencies import (
    AfterCommitActionsDependency,
    DatabaseTransactionDependency,
    SettingsDependency,
    WorkflowDispatcherDependency,
)
from platform_api.embedding.repository import EmbeddingRunRepository
from platform_api.embedding.service import EmbeddingRunService
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.repositories import SqlAlchemyAuditLogRepository


async def embedding_run_service_dependency(
    session: DatabaseTransactionDependency,
    dispatcher: WorkflowDispatcherDependency,
    after_commit: AfterCommitActionsDependency,
    settings: SettingsDependency,
) -> EmbeddingRunService:
    return EmbeddingRunService(
        EmbeddingRunRepository(session),
        AuditLogService(SqlAlchemyAuditLogRepository(session)),
        dispatcher,
        after_commit,
        settings.qdrant,
    )


EmbeddingRunServiceDependency = Annotated[
    EmbeddingRunService, Depends(embedding_run_service_dependency)
]
