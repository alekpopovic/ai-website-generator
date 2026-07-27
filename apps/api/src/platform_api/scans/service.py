"""Scan campaign ownership, configuration, lifecycle, and dispatch rules."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Protocol
from uuid import UUID

from platform_workflows.commands import CompactWorkflowInput
from platform_workflows.dispatcher import (
    DuplicateWorkflowDispatchError,
    ScanCampaignSignal,
    WorkflowDispatcher,
)
from platform_workflows.identifiers import WorkflowKind, workflow_id
from pydantic import BaseModel
from temporalio.exceptions import WorkflowAlreadyStartedError

from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import (
    CrawlPage,
    Project,
    ScanCampaign,
    ScanFailure,
    ScanTarget,
)
from platform_api.persistence.pagination import Page
from platform_api.scans.schemas import (
    CampaignConfiguration,
    CampaignListParams,
    CrawlPageResponse,
    CrawlPageWithScansResponse,
    FailureListParams,
    PageScanResponse,
    ScanCampaignCreateRequest,
    ScanCampaignResponse,
    ScanCampaignSummaryResponse,
    ScanCampaignUpdateRequest,
    ScanFailureResponse,
    ScanItemListParams,
    ScanTargetCreateRequest,
    ScanTargetResponse,
    normalize_public_scan_url,
)

_CONFIGURATION_FIELDS = (
    "authorization_attested_at",
    "respect_robots_txt",
    "crawler_user_agent",
    "max_discovered_pages_per_domain",
    "max_visual_pages_per_domain",
    "maximum_crawl_depth",
    "per_domain_concurrency",
    "crawl_delay_seconds",
    "overall_concurrency",
    "desktop_viewport",
    "mobile_viewport",
    "allowed_content_types",
    "include_url_patterns",
    "exclude_url_patterns",
    "tracking_query_parameters",
    "query_parameter_ordering",
    "store_raw_html",
    "timeout_limits",
    "artifact_retention_policy",
)


class AfterCommitScheduler(Protocol):
    def add(self, name: str, callback: Callable[[], Awaitable[None]]) -> None: ...


class ScanCampaignRepositoryContract(Protocol):
    def add(self, entity: ScanCampaign | ScanTarget) -> None: ...

    async def delete(self, entity: ScanCampaign | ScanTarget) -> None: ...

    async def flush(self) -> None: ...

    async def owned_project(self, project_id: UUID, owner_id: UUID) -> Project | None: ...

    async def campaign_owned(
        self,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScanCampaign | None: ...

    async def campaign_name_exists(
        self, project_id: UUID, name: str, *, exclude_id: UUID | None = None
    ) -> bool: ...

    async def campaign_page(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
        search: str | None,
        status: str | None,
        sort_by: str,
        sort_order: str,
    ) -> Page[ScanCampaign]: ...

    async def target_owned(
        self,
        target_id: UUID,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScanTarget | None: ...

    async def target_url_exists(self, campaign_id: UUID, normalized_url: str) -> bool: ...

    async def target_page(
        self,
        *,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
        status: str | None,
    ) -> Page[ScanTarget]: ...

    async def crawl_page_page(
        self,
        *,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
        status: str | None,
    ) -> Page[CrawlPage]: ...

    async def failure_page(
        self,
        *,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
        stage: str | None,
        retryable: bool | None,
        unresolved_only: bool,
    ) -> Page[ScanFailure]: ...

    async def summary_counts(
        self, campaign_id: UUID
    ) -> tuple[dict[str, int], dict[str, int], dict[str, int], int, int, int]: ...

    async def has_retryable_failures(self, campaign_id: UUID) -> bool: ...


class ScanCampaignService:
    """Manage project-owned scan commands without performing scan work."""

    def __init__(
        self,
        repository: ScanCampaignRepositoryContract,
        audit: AuditLogService,
        dispatcher: WorkflowDispatcher,
        after_commit: AfterCommitScheduler,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._dispatcher = dispatcher
        self._after_commit = after_commit

    async def create(
        self,
        project_id: UUID,
        payload: ScanCampaignCreateRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> ScanCampaignResponse:
        await self._project(project_id, owner_id, require_writable=True)
        if await self._repository.campaign_name_exists(project_id, payload.name):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "scan_campaign_name_conflict",
                "A scan campaign with this name already exists in the project.",
            )
        campaign = ScanCampaign(
            project_id=project_id,
            name=payload.name,
            status="draft",
            workflow_attempt=0,
            **self._configuration_values(payload),
        )
        self._repository.add(campaign)
        await self._repository.flush()
        self._record(campaign, owner_id, request_id, "created")
        return ScanCampaignResponse.model_validate(campaign)

    async def list(
        self, project_id: UUID, *, owner_id: UUID, params: CampaignListParams
    ) -> Page[ScanCampaignResponse]:
        await self._project(project_id, owner_id)
        page = await self._repository.campaign_page(
            project_id=project_id,
            owner_id=owner_id,
            limit=params.limit,
            offset=params.offset,
            search=params.search,
            status=params.status,
            sort_by=params.sort_by,
            sort_order=params.sort_order,
        )
        return Page(
            items=tuple(ScanCampaignResponse.model_validate(item) for item in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def get(
        self, project_id: UUID, campaign_id: UUID, *, owner_id: UUID
    ) -> ScanCampaignResponse:
        return ScanCampaignResponse.model_validate(
            await self._campaign(project_id, campaign_id, owner_id)
        )

    async def update(
        self,
        project_id: UUID,
        campaign_id: UUID,
        payload: ScanCampaignUpdateRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> ScanCampaignResponse:
        await self._project(project_id, owner_id, require_writable=True)
        campaign = await self._campaign(project_id, campaign_id, owner_id, for_update=True)
        self._check_version(campaign, payload.version)
        self._require_status(campaign, {"draft"}, "Only draft campaigns can be edited.")
        changes = payload.model_dump(exclude={"version"}, exclude_unset=True)
        if "name" in changes and await self._repository.campaign_name_exists(
            project_id, str(changes["name"]), exclude_id=campaign.id
        ):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "scan_campaign_name_conflict",
                "A scan campaign with this name already exists in the project.",
            )
        proposed = {
            field: changes.get(field, getattr(campaign, field)) for field in _CONFIGURATION_FIELDS
        }
        validated = CampaignConfiguration.model_validate(proposed)
        normalized_changes = changes.copy()
        for field in _CONFIGURATION_FIELDS:
            if field in changes:
                normalized_changes[field] = getattr(validated, field)
        for field, value in normalized_changes.items():
            setattr(campaign, field, self._json_value(value))
        await self._repository.flush()
        self._record(
            campaign,
            owner_id,
            request_id,
            "updated",
            details={"changed_fields": sorted(changes)},
        )
        return ScanCampaignResponse.model_validate(campaign)

    async def delete(
        self,
        project_id: UUID,
        campaign_id: UUID,
        *,
        version: int,
        owner_id: UUID,
        request_id: str,
    ) -> None:
        await self._project(project_id, owner_id, require_writable=True)
        campaign = await self._campaign(project_id, campaign_id, owner_id, for_update=True)
        self._check_version(campaign, version)
        self._require_status(campaign, {"draft"}, "Only draft campaigns can be deleted.")
        self._record(campaign, owner_id, request_id, "deleted")
        await self._repository.delete(campaign)

    async def add_target(
        self,
        project_id: UUID,
        campaign_id: UUID,
        payload: ScanTargetCreateRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> ScanTargetResponse:
        await self._project(project_id, owner_id, require_writable=True)
        campaign = await self._campaign(project_id, campaign_id, owner_id, for_update=True)
        self._require_status(campaign, {"draft"}, "Targets can only be changed in draft.")
        normalized_url, source_domain = normalize_public_scan_url(payload.url)
        if await self._repository.target_url_exists(campaign.id, normalized_url):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "scan_target_conflict",
                "This scan target already exists in the campaign.",
            )
        target = ScanTarget(
            campaign_id=campaign.id,
            url=payload.url,
            normalized_url=normalized_url,
            source_domain=source_domain,
            status="pending",
        )
        self._repository.add(target)
        await self._repository.flush()
        self._record(
            campaign,
            owner_id,
            request_id,
            "target_added",
            details={"target_id": target.id},
        )
        return ScanTargetResponse.model_validate(target)

    async def delete_target(
        self,
        project_id: UUID,
        campaign_id: UUID,
        target_id: UUID,
        *,
        version: int,
        owner_id: UUID,
        request_id: str,
    ) -> None:
        await self._project(project_id, owner_id, require_writable=True)
        campaign = await self._campaign(project_id, campaign_id, owner_id, for_update=True)
        self._require_status(campaign, {"draft"}, "Targets can only be changed in draft.")
        target = await self._repository.target_owned(
            target_id, campaign_id, project_id, owner_id, for_update=True
        )
        if target is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "scan_target_not_found", "Target was not found.")
        if target.version != version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "scan_target_version_conflict",
                "The target changed since it was loaded.",
            )
        self._record(
            campaign,
            owner_id,
            request_id,
            "target_deleted",
            details={"target_id": target.id},
        )
        await self._repository.delete(target)

    async def list_targets(
        self,
        project_id: UUID,
        campaign_id: UUID,
        *,
        owner_id: UUID,
        params: ScanItemListParams,
    ) -> Page[ScanTargetResponse]:
        await self._campaign(project_id, campaign_id, owner_id)
        page = await self._repository.target_page(
            campaign_id=campaign_id,
            project_id=project_id,
            owner_id=owner_id,
            limit=params.limit,
            offset=params.offset,
            status=params.status,
        )
        return Page(
            items=tuple(ScanTargetResponse.model_validate(item) for item in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def list_pages(
        self,
        project_id: UUID,
        campaign_id: UUID,
        *,
        owner_id: UUID,
        params: ScanItemListParams,
    ) -> Page[CrawlPageWithScansResponse]:
        await self._campaign(project_id, campaign_id, owner_id)
        page = await self._repository.crawl_page_page(
            campaign_id=campaign_id,
            project_id=project_id,
            owner_id=owner_id,
            limit=params.limit,
            offset=params.offset,
            status=params.status,
        )
        responses = []
        for item in page.items:
            page_response = CrawlPageResponse.model_validate(item)
            responses.append(
                CrawlPageWithScansResponse(
                    **page_response.model_dump(),
                    page_scans=tuple(
                        PageScanResponse.model_validate(scan) for scan in item.page_scans
                    ),
                )
            )
        return Page(items=tuple(responses), total=page.total, limit=page.limit, offset=page.offset)

    async def list_failures(
        self,
        project_id: UUID,
        campaign_id: UUID,
        *,
        owner_id: UUID,
        params: FailureListParams,
    ) -> Page[ScanFailureResponse]:
        await self._campaign(project_id, campaign_id, owner_id)
        page = await self._repository.failure_page(
            campaign_id=campaign_id,
            project_id=project_id,
            owner_id=owner_id,
            limit=params.limit,
            offset=params.offset,
            stage=params.stage,
            retryable=params.retryable,
            unresolved_only=params.unresolved_only,
        )
        return Page(
            items=tuple(ScanFailureResponse.model_validate(item) for item in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def summary(
        self, project_id: UUID, campaign_id: UUID, *, owner_id: UUID
    ) -> ScanCampaignSummaryResponse:
        campaign = await self._campaign(project_id, campaign_id, owner_id)
        (
            targets,
            pages,
            scans,
            failures,
            retryable,
            unresolved,
        ) = await self._repository.summary_counts(campaign.id)
        return ScanCampaignSummaryResponse(
            campaign=ScanCampaignResponse.model_validate(campaign),
            target_counts=targets,
            page_counts=pages,
            page_scan_counts=scans,
            failure_count=failures,
            retryable_failure_count=retryable,
            unresolved_failure_count=unresolved,
        )

    async def start(
        self,
        project_id: UUID,
        campaign_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        owner_id: UUID,
        request_id: str,
    ) -> ScanCampaignResponse:
        await self._project(project_id, owner_id, require_writable=True)
        campaign = await self._campaign(project_id, campaign_id, owner_id, for_update=True)
        self._check_version(campaign, version)
        self._require_status(campaign, {"draft"}, "Only a draft campaign can be started.")
        target_page = await self._repository.target_page(
            campaign_id=campaign.id,
            project_id=project_id,
            owner_id=owner_id,
            limit=1,
            offset=0,
            status=None,
        )
        if target_page.total == 0:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "scan_campaign_has_no_targets",
                "Add at least one scan target before starting the campaign.",
            )
        await self._queue_workflow(
            campaign,
            idempotency_key=idempotency_key,
            owner_id=owner_id,
            request_id=request_id,
            action="started",
        )
        return ScanCampaignResponse.model_validate(campaign)

    async def pause(
        self,
        project_id: UUID,
        campaign_id: UUID,
        *,
        version: int,
        owner_id: UUID,
        request_id: str,
    ) -> ScanCampaignResponse:
        return await self._signal_transition(
            project_id,
            campaign_id,
            version=version,
            owner_id=owner_id,
            request_id=request_id,
            allowed={"queued", "running"},
            target_status="pausing",
            signal=ScanCampaignSignal.PAUSE,
        )

    async def resume(
        self,
        project_id: UUID,
        campaign_id: UUID,
        *,
        version: int,
        owner_id: UUID,
        request_id: str,
    ) -> ScanCampaignResponse:
        return await self._signal_transition(
            project_id,
            campaign_id,
            version=version,
            owner_id=owner_id,
            request_id=request_id,
            allowed={"paused"},
            target_status="running",
            signal=ScanCampaignSignal.RESUME,
        )

    async def cancel(
        self,
        project_id: UUID,
        campaign_id: UUID,
        *,
        version: int,
        owner_id: UUID,
        request_id: str,
    ) -> ScanCampaignResponse:
        return await self._signal_transition(
            project_id,
            campaign_id,
            version=version,
            owner_id=owner_id,
            request_id=request_id,
            allowed={"queued", "running", "pausing", "paused"},
            target_status="cancelling",
            signal=ScanCampaignSignal.CANCEL,
        )

    async def retry_failures(
        self,
        project_id: UUID,
        campaign_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        owner_id: UUID,
        request_id: str,
    ) -> ScanCampaignResponse:
        await self._project(project_id, owner_id, require_writable=True)
        campaign = await self._campaign(project_id, campaign_id, owner_id, for_update=True)
        self._check_version(campaign, version)
        self._require_status(
            campaign,
            {"failed", "partially_succeeded"},
            "Failures can only be retried after a failed or partially succeeded campaign.",
        )
        if not await self._repository.has_retryable_failures(campaign.id):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "scan_campaign_has_no_retryable_failures",
                "The campaign has no unresolved retryable failures.",
            )
        await self._queue_workflow(
            campaign,
            idempotency_key=idempotency_key,
            owner_id=owner_id,
            request_id=request_id,
            action="failures_retried",
        )
        return ScanCampaignResponse.model_validate(campaign)

    async def _queue_workflow(
        self,
        campaign: ScanCampaign,
        *,
        idempotency_key: str,
        owner_id: UUID,
        request_id: str,
        action: str,
    ) -> None:
        previous = campaign.status
        command = CompactWorkflowInput(
            job_id=str(campaign.id),
            project_id=str(campaign.project_id),
            requested_by_user_id=str(owner_id),
            idempotency_key=idempotency_key,
        )
        campaign.status = "queued"
        campaign.workflow_attempt += 1
        campaign.workflow_id = workflow_id(WorkflowKind.SCAN_CAMPAIGN, campaign.id, idempotency_key)
        campaign.workflow_run_id = None
        campaign.completed_at = None
        await self._repository.flush()
        self._record_transition(campaign, owner_id, request_id, action, previous)

        async def dispatch() -> None:
            try:
                await self._dispatcher.dispatch(WorkflowKind.SCAN_CAMPAIGN, command)
            except (DuplicateWorkflowDispatchError, WorkflowAlreadyStartedError):
                return

        self._after_commit.add(f"scan-campaign-dispatch:{campaign.id}", dispatch)

    async def _signal_transition(
        self,
        project_id: UUID,
        campaign_id: UUID,
        *,
        version: int,
        owner_id: UUID,
        request_id: str,
        allowed: set[str],
        target_status: str,
        signal: ScanCampaignSignal,
    ) -> ScanCampaignResponse:
        await self._project(project_id, owner_id, require_writable=True)
        campaign = await self._campaign(project_id, campaign_id, owner_id, for_update=True)
        self._check_version(campaign, version)
        self._require_status(campaign, allowed, "Campaign state does not allow this action.")
        if campaign.workflow_id is None:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "scan_workflow_not_dispatched",
                "The campaign has no workflow to control.",
            )
        previous = campaign.status
        campaign.status = target_status
        await self._repository.flush()
        self._record_transition(campaign, owner_id, request_id, signal.value, previous)
        workflow_identifier = campaign.workflow_id

        async def send_signal() -> None:
            await self._dispatcher.signal_scan_campaign(workflow_identifier, signal)

        self._after_commit.add(f"scan-campaign-{signal.value}:{campaign.id}", send_signal)
        return ScanCampaignResponse.model_validate(campaign)

    async def _project(
        self, project_id: UUID, owner_id: UUID, *, require_writable: bool = False
    ) -> Project:
        project = await self._repository.owned_project(project_id, owner_id)
        if project is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "project_not_found", "Project was not found.")
        if require_writable and project.status == "archived":
            raise ApiError(
                HTTPStatus.CONFLICT,
                "project_archived",
                "Restore the project before changing scan campaigns.",
            )
        return project

    async def _campaign(
        self,
        project_id: UUID,
        campaign_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScanCampaign:
        campaign = await self._repository.campaign_owned(
            campaign_id, project_id, owner_id, for_update=for_update
        )
        if campaign is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "scan_campaign_not_found",
                "Scan campaign was not found.",
            )
        return campaign

    @staticmethod
    def _check_version(campaign: ScanCampaign, expected: int) -> None:
        if campaign.version != expected:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "scan_campaign_version_conflict",
                "The scan campaign changed since it was loaded. Reload and try again.",
            )

    @staticmethod
    def _require_status(campaign: ScanCampaign, allowed: set[str], detail: str) -> None:
        if campaign.status not in allowed:
            raise ApiError(HTTPStatus.CONFLICT, "invalid_scan_campaign_transition", detail)

    @staticmethod
    def _configuration_values(payload: CampaignConfiguration) -> dict[str, object]:
        return {
            field: ScanCampaignService._json_value(getattr(payload, field))
            for field in _CONFIGURATION_FIELDS
        }

    @staticmethod
    def _json_value(value: object) -> object:
        if isinstance(value, BaseException):
            raise TypeError("exceptions cannot be persisted")
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, tuple):
            return list(value)
        return value

    def _record_transition(
        self,
        campaign: ScanCampaign,
        owner_id: UUID,
        request_id: str,
        action: str,
        previous: str,
    ) -> None:
        self._record(
            campaign,
            owner_id,
            request_id,
            action,
            details={"from_status": previous, "to_status": campaign.status},
        )

    def _record(
        self,
        campaign: ScanCampaign,
        owner_id: UUID,
        request_id: str,
        action: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        self._audit.record(
            action=f"scan_campaign.{action}",
            resource_type="scan_campaign",
            actor_user_id=owner_id,
            resource_id=campaign.id,
            request_id=request_id,
            details=details,
        )
