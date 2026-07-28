"""Request-scoped structured-analysis composition."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from platform_api.analysis.repository import AnalysisRepository
from platform_api.analysis.service import AnalysisProfileService
from platform_api.dependencies import DatabaseTransactionDependency
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.repositories import SqlAlchemyAuditLogRepository


async def analysis_profile_service_dependency(
    session: DatabaseTransactionDependency,
) -> AnalysisProfileService:
    return AnalysisProfileService(
        AnalysisRepository(session), AuditLogService(SqlAlchemyAuditLogRepository(session))
    )


AnalysisProfileServiceDependency = Annotated[
    AnalysisProfileService, Depends(analysis_profile_service_dependency)
]
