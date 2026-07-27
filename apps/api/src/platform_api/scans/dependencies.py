"""Explicit scan-domain dependencies and bounded query parsing."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query

from platform_api.dependencies import (
    AfterCommitActionsDependency,
    DatabaseTransactionDependency,
    WorkflowDispatcherDependency,
)
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.repositories import SqlAlchemyAuditLogRepository
from platform_api.scans.repositories import ScanCampaignRepository
from platform_api.scans.schemas import (
    CampaignListParams,
    CampaignSort,
    CrawlPageStatus,
    FailureListParams,
    FailureStage,
    ScanCampaignStatus,
    ScanItemListParams,
    ScanTargetStatus,
    SortOrder,
)
from platform_api.scans.service import ScanCampaignService


async def scan_campaign_service_dependency(
    session: DatabaseTransactionDependency,
    dispatcher: WorkflowDispatcherDependency,
    after_commit: AfterCommitActionsDependency,
) -> ScanCampaignService:
    return ScanCampaignService(
        ScanCampaignRepository(session),
        AuditLogService(SqlAlchemyAuditLogRepository(session)),
        dispatcher,
        after_commit,
    )


ScanCampaignServiceDependency = Annotated[
    ScanCampaignService, Depends(scan_campaign_service_dependency)
]


async def campaign_list_params_dependency(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    status: Annotated[ScanCampaignStatus | None, Query()] = None,
    sort_by: Annotated[CampaignSort, Query()] = "updated_at",
    sort_order: Annotated[SortOrder, Query()] = "desc",
) -> CampaignListParams:
    return CampaignListParams(
        offset=offset,
        limit=limit,
        search=search,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )


CampaignListParamsDependency = Annotated[
    CampaignListParams, Depends(campaign_list_params_dependency)
]


async def target_list_params_dependency(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[ScanTargetStatus | None, Query()] = None,
) -> ScanItemListParams:
    return ScanItemListParams(offset=offset, limit=limit, status=status)


TargetListParamsDependency = Annotated[ScanItemListParams, Depends(target_list_params_dependency)]


async def page_list_params_dependency(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[CrawlPageStatus | None, Query()] = None,
) -> ScanItemListParams:
    return ScanItemListParams(offset=offset, limit=limit, status=status)


PageListParamsDependency = Annotated[ScanItemListParams, Depends(page_list_params_dependency)]


async def failure_list_params_dependency(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    stage: Annotated[FailureStage | None, Query()] = None,
    retryable: Annotated[bool | None, Query()] = None,
    unresolved_only: Annotated[bool, Query()] = False,
) -> FailureListParams:
    return FailureListParams(
        offset=offset,
        limit=limit,
        stage=stage,
        retryable=retryable,
        unresolved_only=unresolved_only,
    )


FailureListParamsDependency = Annotated[FailureListParams, Depends(failure_list_params_dependency)]
