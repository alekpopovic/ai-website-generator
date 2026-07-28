"""Scan campaign ownership, state machine, workflow dispatch, and API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi import FastAPI
from platform_api.auth.dependencies import current_user_dependency
from platform_api.dependencies import AfterCommitActions
from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import (
    AuditLog,
    CrawlPage,
    JobEvent,
    Project,
    ScanCampaign,
    ScanFailure,
    ScanTarget,
    User,
)
from platform_api.persistence.pagination import Page
from platform_api.scans.dependencies import scan_campaign_service_dependency
from platform_api.scans.repositories import DuplicateGroupProjection
from platform_api.scans.schemas import (
    ScanCampaignCreateRequest,
    ScanCampaignUpdateRequest,
    ScanTargetCreateRequest,
    normalize_public_scan_url,
)
from platform_api.scans.service import ScanCampaignService
from platform_workflows.dispatcher import FakeWorkflowDispatcher, ScanCampaignSignal
from platform_workflows.identifiers import WorkflowKind

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


class RecordingAuditRepository:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def add(self, entry: AuditLog) -> None:
        self.entries.append(entry)


class FakeScanRepository:
    """Owner-scoped fake with simple optimistic version tracking."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.campaigns: dict[UUID, ScanCampaign] = {}
        self.targets: dict[UUID, ScanTarget] = {}
        self.pages: dict[UUID, CrawlPage] = {}
        self.failures: dict[UUID, ScanFailure] = {}
        self._new: set[UUID] = set()
        self._snapshots: dict[UUID, tuple[object, ...]] = {}

    def add(self, entity: ScanCampaign | ScanTarget) -> None:
        entity.id = uuid4()
        entity.created_at = NOW
        entity.updated_at = NOW
        entity.version = 1
        self._new.add(entity.id)
        if isinstance(entity, ScanCampaign):
            self.campaigns[entity.id] = entity
        else:
            self.targets[entity.id] = entity

    async def delete(self, entity: ScanCampaign | ScanTarget) -> None:
        if isinstance(entity, ScanCampaign):
            self.campaigns.pop(entity.id, None)
            self.targets = {
                key: target
                for key, target in self.targets.items()
                if target.campaign_id != entity.id
            }
        else:
            self.targets.pop(entity.id, None)

    @staticmethod
    def _snapshot(entity: ScanCampaign | ScanTarget | CrawlPage) -> tuple[object, ...]:
        ignored = {"created_at", "updated_at", "version"}
        return tuple(
            getattr(entity, column.name)
            for column in entity.__table__.columns
            if column.name not in ignored
        )

    async def flush(self) -> None:
        entities: tuple[ScanCampaign | ScanTarget | CrawlPage, ...] = (
            *self.campaigns.values(),
            *self.targets.values(),
            *self.pages.values(),
        )
        for entity in entities:
            snapshot = self._snapshot(entity)
            if entity.id in self._new:
                self._new.remove(entity.id)
            elif entity.id in self._snapshots and self._snapshots[entity.id] != snapshot:
                entity.version += 1
                entity.updated_at = NOW
            self._snapshots[entity.id] = snapshot

    async def owned_project(self, project_id: UUID, owner_id: UUID) -> Project | None:
        if self.project.id == project_id and self.project.owner_id == owner_id:
            return self.project
        return None

    async def campaign_owned(
        self,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScanCampaign | None:
        del for_update
        campaign = self.campaigns.get(campaign_id)
        if (
            campaign is not None
            and campaign.project_id == project_id
            and self.project.owner_id == owner_id
        ):
            return campaign
        return None

    async def campaign_name_exists(
        self, project_id: UUID, name: str, *, exclude_id: UUID | None = None
    ) -> bool:
        return any(
            item.project_id == project_id and item.name == name and item.id != exclude_id
            for item in self.campaigns.values()
        )

    async def campaign_page(self, **kwargs: Any) -> Page[ScanCampaign]:
        items = [
            item
            for item in self.campaigns.values()
            if item.project_id == kwargs["project_id"]
            and self.project.owner_id == kwargs["owner_id"]
        ]
        if kwargs["search"]:
            items = [item for item in items if kwargs["search"].casefold() in item.name.casefold()]
        if kwargs["status"]:
            items = [item for item in items if item.status == kwargs["status"]]
        items.sort(
            key=lambda item: getattr(item, kwargs["sort_by"]),
            reverse=kwargs["sort_order"] == "desc",
        )
        offset, limit = kwargs["offset"], kwargs["limit"]
        return Page(
            items=tuple(items[offset : offset + limit]),
            total=len(items),
            limit=limit,
            offset=offset,
        )

    async def target_owned(
        self,
        target_id: UUID,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScanTarget | None:
        del for_update
        target = self.targets.get(target_id)
        campaign = self.campaigns.get(campaign_id)
        if (
            target is not None
            and campaign is not None
            and target.campaign_id == campaign_id
            and campaign.project_id == project_id
            and self.project.owner_id == owner_id
        ):
            return target
        return None

    async def target_url_exists(self, campaign_id: UUID, normalized_url: str) -> bool:
        return any(
            item.campaign_id == campaign_id and item.normalized_url == normalized_url
            for item in self.targets.values()
        )

    async def target_page(self, **kwargs: Any) -> Page[ScanTarget]:
        items = [
            target
            for target in self.targets.values()
            if target.campaign_id == kwargs["campaign_id"]
            and self.project.owner_id == kwargs["owner_id"]
        ]
        if kwargs["status"]:
            items = [item for item in items if item.status == kwargs["status"]]
        offset, limit = kwargs["offset"], kwargs["limit"]
        return Page(
            items=tuple(items[offset : offset + limit]),
            total=len(items),
            limit=limit,
            offset=offset,
        )

    async def crawl_page_page(self, **kwargs: Any) -> Page[CrawlPage]:
        items = [item for item in self.pages.values() if item.campaign_id == kwargs["campaign_id"]]
        offset, limit = kwargs["offset"], kwargs["limit"]
        return Page(
            items=tuple(items[offset : offset + limit]),
            total=len(items),
            limit=limit,
            offset=offset,
        )

    async def crawl_page_owned(
        self,
        page_id: UUID,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> CrawlPage | None:
        del for_update
        page = self.pages.get(page_id)
        campaign = self.campaigns.get(campaign_id)
        if (
            page is not None
            and campaign is not None
            and page.campaign_id == campaign_id
            and campaign.project_id == project_id
            and self.project.owner_id == owner_id
        ):
            return page
        return None

    async def campaign_pages_for_selection(self, campaign_id: UUID) -> tuple[CrawlPage, ...]:
        return tuple(
            sorted(
                (
                    page
                    for page in self.pages.values()
                    if page.campaign_id == campaign_id and page.status == "fetched"
                ),
                key=lambda page: (page.normalized_url, str(page.id)),
            )
        )

    async def failure_page(self, **kwargs: Any) -> Page[ScanFailure]:
        items = [
            item for item in self.failures.values() if item.campaign_id == kwargs["campaign_id"]
        ]
        offset, limit = kwargs["offset"], kwargs["limit"]
        return Page(
            items=tuple(items[offset : offset + limit]),
            total=len(items),
            limit=limit,
            offset=offset,
        )

    async def summary_counts(
        self, campaign_id: UUID
    ) -> tuple[
        dict[str, int],
        dict[str, int],
        dict[str, int],
        int,
        int,
        int,
        dict[str, int],
        dict[str, int],
    ]:
        targets = [target for target in self.targets.values() if target.campaign_id == campaign_id]
        failures = [
            failure for failure in self.failures.values() if failure.campaign_id == campaign_id
        ]
        page_type_counts: dict[str, int] = {}
        for page in self.pages.values():
            if page.campaign_id == campaign_id and page.page_type is not None:
                page_type_counts[page.page_type] = page_type_counts.get(page.page_type, 0) + 1
        return (
            {"pending": len(targets)} if targets else {},
            {},
            {},
            len(failures),
            sum(failure.retryable for failure in failures),
            sum(failure.resolved_at is None for failure in failures),
            {
                "fingerprinted_pages": 0,
                "unique_representatives": 0,
                "exact_duplicate_pages": 0,
                "exact_duplicate_groups": 0,
                "near_duplicate_pages": 0,
                "near_duplicate_groups": 0,
                "shared_template_pages": 0,
                "shared_template_groups": 0,
                "repeated_collection_groups": 0,
            },
            page_type_counts,
        )

    async def has_retryable_failures(self, campaign_id: UUID) -> bool:
        return any(
            failure.campaign_id == campaign_id and failure.retryable and failure.resolved_at is None
            for failure in self.failures.values()
        )

    async def selected_retryable_failures(
        self, campaign_id: UUID, failure_ids: tuple[UUID, ...]
    ) -> tuple[ScanFailure, ...]:
        return tuple(
            failure
            for failure_id in failure_ids
            if (failure := self.failures.get(failure_id)) is not None
            and failure.campaign_id == campaign_id
            and failure.retryable
            and failure.resolved_at is None
        )

    async def failures_for_page(self, page_id: UUID) -> tuple[ScanFailure, ...]:
        return tuple(
            failure for failure in self.failures.values() if failure.crawl_page_id == page_id
        )

    async def target_summary_counts(
        self, campaign_id: UUID, target_id: UUID
    ) -> tuple[dict[str, int], dict[str, int], int, int]:
        pages = [
            page
            for page in self.pages.values()
            if page.campaign_id == campaign_id and page.target_id == target_id
        ]
        failures = [failure for failure in self.failures.values() if failure.target_id == target_id]
        return (
            {
                status: sum(page.status == status for page in pages)
                for status in {p.status for p in pages}
            },
            {},
            len(failures),
            sum(failure.resolved_at is None for failure in failures),
        )

    async def duplicate_group_page(
        self, campaign_id: UUID, *, group_type: str, limit: int, offset: int
    ) -> Page[DuplicateGroupProjection]:
        del campaign_id, group_type
        return Page(items=(), total=0, limit=limit, offset=offset)

    async def activity_page(self, campaign_id: UUID, *, limit: int, offset: int) -> Page[JobEvent]:
        del campaign_id
        return Page(items=(), total=0, limit=limit, offset=offset)


def fixture() -> tuple[
    ScanCampaignService,
    FakeScanRepository,
    RecordingAuditRepository,
    FakeWorkflowDispatcher,
    AfterCommitActions,
    UUID,
]:
    owner_id = uuid4()
    project = Project(
        id=uuid4(),
        owner_id=owner_id,
        name="Scan Project",
        slug="scan-project",
        default_language="en",
        status="draft",
        settings={},
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )
    repository = FakeScanRepository(project)
    audits = RecordingAuditRepository()
    dispatcher = FakeWorkflowDispatcher()
    after_commit = AfterCommitActions()
    service = ScanCampaignService(
        repository,
        AuditLogService(audits),
        dispatcher,
        after_commit,
    )
    return service, repository, audits, dispatcher, after_commit, owner_id


def campaign_payload(name: str = "Primary scan") -> ScanCampaignCreateRequest:
    return ScanCampaignCreateRequest(name=name, authorization_attested_at=NOW)


def crawl_page(
    campaign_id: UUID,
    *,
    number: int,
    page_type: str,
    template_group_key: str | None = None,
) -> CrawlPage:
    url = "https://example.com/" if page_type == "homepage" else f"https://example.com/{page_type}"
    return CrawlPage(
        id=UUID(int=number),
        campaign_id=campaign_id,
        target_id=uuid4(),
        url=url,
        normalized_url=url,
        final_url=url,
        source_domain="example.com",
        depth=0,
        status="fetched",
        robots_allowed=True,
        crawl_policy_provenance={},
        http_status=200,
        content_type="text/html",
        title=page_type.title(),
        hreflang_links=[],
        content_length=1_000,
        discovery_source="submitted_root",
        normalized_text_length=1_000,
        template_group_key=template_group_key,
        page_type=page_type,
        page_type_score=0.9,
        classification_features={},
        classification_explanation=[f"path:{page_type}"],
        classifier="deterministic-page-classifier",
        classifier_version=1,
        classified_at=NOW,
        representative_selected=False,
        selection_explanation=[],
        manual_selection="automatic",
        discovered_at=NOW,
        fetched_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )


def test_normal_users_cannot_disable_robots_compliance() -> None:
    with pytest.raises(ValueError):
        ScanCampaignCreateRequest.model_validate(
            {"name": "Unsafe scan", "authorization_attested_at": NOW, "respect_robots_txt": False}
        )


@pytest.mark.anyio
async def test_campaign_crud_is_owner_scoped_and_draft_only() -> None:
    service, repository, audits, _, _, owner_id = fixture()
    project_id = repository.project.id
    created = await service.create(
        project_id, campaign_payload(), owner_id=owner_id, request_id="create"
    )
    updated = await service.update(
        project_id,
        created.id,
        ScanCampaignUpdateRequest(
            version=created.version,
            name="Updated scan",
            max_discovered_pages_per_domain=50,
            max_visual_pages_per_domain=10,
        ),
        owner_id=owner_id,
        request_id="update",
    )

    assert updated.name == "Updated scan"
    assert updated.respect_robots_txt is True
    assert updated.desktop_viewport.width == 1440
    assert [entry.action for entry in audits.entries] == [
        "scan_campaign.created",
        "scan_campaign.updated",
    ]
    with pytest.raises(ApiError) as hidden:
        await service.get(project_id, created.id, owner_id=uuid4())
    assert hidden.value.code == "scan_campaign_not_found"


def test_scan_target_url_validation_rejects_static_ssrf_destinations() -> None:
    for url in (
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://service.internal/",
        "https://user:password@example.com/",  # pragma: allowlist secret
        "https://example.com:8443/",
    ):
        with pytest.raises(ValueError):
            normalize_public_scan_url(url)
    assert normalize_public_scan_url("HTTPS://Example.COM/pricing?annual=1") == (
        "https://example.com/pricing?annual=1",
        "example.com",
    )
    assert normalize_public_scan_url("https://[2606:4700:4700::1111]/") == (
        "https://[2606:4700:4700::1111]/",
        "2606:4700:4700::1111",
    )


@pytest.mark.anyio
async def test_start_dispatches_compact_workflow_only_after_commit_and_requires_target() -> None:
    service, repository, _, dispatcher, after_commit, owner_id = fixture()
    created = await service.create(
        repository.project.id, campaign_payload(), owner_id=owner_id, request_id="create"
    )
    with pytest.raises(ApiError) as no_targets:
        await service.start(
            repository.project.id,
            created.id,
            version=created.version,
            idempotency_key="first-run",
            owner_id=owner_id,
            request_id="start-empty",
        )
    assert no_targets.value.code == "scan_campaign_has_no_targets"

    await service.add_target(
        repository.project.id,
        created.id,
        ScanTargetCreateRequest(url="https://example.com/"),
        owner_id=owner_id,
        request_id="target",
    )
    current = await service.get(repository.project.id, created.id, owner_id=owner_id)
    queued = await service.start(
        repository.project.id,
        created.id,
        version=current.version,
        idempotency_key="first-run",
        owner_id=owner_id,
        request_id="start",
    )

    assert queued.status == "queued"
    assert dispatcher.dispatched == []
    await after_commit.run()
    assert len(dispatcher.dispatched) == 1
    kind, command = dispatcher.dispatched[0]
    assert kind is WorkflowKind.SCAN_CAMPAIGN
    assert command.job_id == str(created.id)
    assert command.project_id == str(repository.project.id)
    assert command.input_object_key is None


@pytest.mark.anyio
async def test_pause_resume_cancel_enforce_state_machine_and_signal_after_commit() -> None:
    service, repository, _, dispatcher, after_commit, owner_id = fixture()
    campaign = await service.create(
        repository.project.id, campaign_payload(), owner_id=owner_id, request_id="create"
    )
    await service.add_target(
        repository.project.id,
        campaign.id,
        ScanTargetCreateRequest(url="https://example.com/"),
        owner_id=owner_id,
        request_id="target",
    )
    campaign = await service.get(repository.project.id, campaign.id, owner_id=owner_id)
    campaign = await service.start(
        repository.project.id,
        campaign.id,
        version=campaign.version,
        idempotency_key="signals",
        owner_id=owner_id,
        request_id="start",
    )
    await after_commit.run()

    repository.campaigns[campaign.id].status = "running"
    await repository.flush()
    current = await service.get(repository.project.id, campaign.id, owner_id=owner_id)
    pausing = await service.pause(
        repository.project.id,
        campaign.id,
        version=current.version,
        owner_id=owner_id,
        request_id="pause",
    )
    assert pausing.status == "pausing"
    await after_commit.run()

    repository.campaigns[campaign.id].status = "paused"
    await repository.flush()
    current = await service.get(repository.project.id, campaign.id, owner_id=owner_id)
    resumed = await service.resume(
        repository.project.id,
        campaign.id,
        version=current.version,
        owner_id=owner_id,
        request_id="resume",
    )
    assert resumed.status == "running"
    await after_commit.run()
    cancelled = await service.cancel(
        repository.project.id,
        campaign.id,
        version=resumed.version,
        owner_id=owner_id,
        request_id="cancel",
    )
    assert cancelled.status == "cancelling"
    await after_commit.run()

    assert [signal for _, signal in dispatcher.scan_signals] == [
        ScanCampaignSignal.PAUSE,
        ScanCampaignSignal.RESUME,
        ScanCampaignSignal.CANCEL,
    ]
    with pytest.raises(ApiError) as invalid:
        await service.pause(
            repository.project.id,
            campaign.id,
            version=cancelled.version,
            owner_id=owner_id,
            request_id="invalid-pause",
        )
    assert invalid.value.code == "invalid_scan_campaign_transition"


@pytest.mark.anyio
async def test_retry_failures_requires_terminal_state_and_retryable_projection() -> None:
    service, repository, _, dispatcher, after_commit, owner_id = fixture()
    campaign = await service.create(
        repository.project.id, campaign_payload(), owner_id=owner_id, request_id="create"
    )
    stored = repository.campaigns[campaign.id]
    stored.status = "partially_succeeded"
    failure = ScanFailure(
        id=uuid4(),
        campaign_id=campaign.id,
        stage="crawl",
        error_code="timeout",
        message="The page fetch exceeded its bounded timeout.",
        retryable=True,
        attempt=1,
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )
    repository.failures[failure.id] = failure
    await repository.flush()
    current = await service.get(repository.project.id, campaign.id, owner_id=owner_id)

    retried = await service.retry_failures(
        repository.project.id,
        campaign.id,
        version=current.version,
        idempotency_key="retry-1",
        owner_id=owner_id,
        request_id="retry",
    )
    await after_commit.run()

    assert retried.status == "queued"
    assert retried.workflow_attempt == 1
    assert dispatcher.dispatched[0][1].job_id == str(campaign.id)


@pytest.mark.anyio
async def test_retry_selected_failures_passes_only_failure_ids_to_temporal() -> None:
    service, repository, _, dispatcher, after_commit, owner_id = fixture()
    campaign = await service.create(
        repository.project.id, campaign_payload(), owner_id=owner_id, request_id="create"
    )
    repository.campaigns[campaign.id].status = "partially_succeeded"
    failure = ScanFailure(
        id=uuid4(),
        campaign_id=campaign.id,
        stage="browser",
        error_code="navigation_timeout",
        message="Navigation exceeded its bounded timeout.",
        retryable=True,
        attempt=1,
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )
    repository.failures[failure.id] = failure
    await repository.flush()
    current = await service.get(repository.project.id, campaign.id, owner_id=owner_id)

    await service.retry_selected_failures(
        repository.project.id,
        campaign.id,
        version=current.version,
        idempotency_key="selected-retry",
        failure_ids=(failure.id,),
        owner_id=owner_id,
        request_id="retry-selected",
    )
    await after_commit.run()

    assert dispatcher.dispatched[0][1].resource_ids == (str(failure.id),)
    assert dispatcher.dispatched[0][1].input_object_key is None


@pytest.mark.anyio
async def test_scan_campaign_api_exposes_crud_targets_summary_and_control(app: FastAPI) -> None:
    service, repository, _, dispatcher, after_commit, owner_id = fixture()
    user = User(
        id=owner_id,
        email="owner@example.test",
        display_name="Owner",
        status="active",
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )

    async def override_user() -> User:
        return user

    async def override_service() -> ScanCampaignService:
        return service

    app.dependency_overrides[current_user_dependency] = override_user
    app.dependency_overrides[scan_campaign_service_dependency] = override_service
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        base = f"/api/v1/projects/{repository.project.id}/scan-campaigns"
        created = await client.post(
            base,
            json={"name": "API scan", "authorization_attested_at": NOW.isoformat()},
        )
        campaign = created.json()
        target = await client.post(
            f"{base}/{campaign['id']}/targets", json={"url": "https://example.com"}
        )
        listed = await client.get(base)
        summary = await client.get(f"{base}/{campaign['id']}/summary")
        started = await client.post(
            f"{base}/{campaign['id']}/start",
            json={"version": campaign["version"], "idempotency_key": "api-start"},
        )
        await after_commit.run()

    assert created.status_code == 201
    assert target.status_code == 201
    assert listed.json()["pagination"]["total"] == 1
    assert summary.json()["target_counts"] == {"pending": 1}
    assert summary.json()["deduplication"]["fingerprinted_pages"] == 0
    assert started.status_code == 202
    assert started.json()["status"] == "queued"
    assert len(dispatcher.dispatched) == 1
    paths = app.openapi()["paths"]
    assert "/api/v1/projects/{project_id}/scan-campaigns/{campaign_id}/pages" in paths
    assert "/api/v1/projects/{project_id}/scan-campaigns/{campaign_id}/failures" in paths


@pytest.mark.anyio
async def test_representative_override_is_owned_versioned_and_reselects_campaign(
    app: FastAPI,
) -> None:
    service, repository, audits, _, _, owner_id = fixture()
    campaign = await service.create(
        repository.project.id, campaign_payload(), owner_id=owner_id, request_id="create"
    )
    home = crawl_page(campaign.id, number=101, page_type="homepage")
    legal = crawl_page(campaign.id, number=102, page_type="legal")
    repository.pages = {home.id: home, legal.id: legal}
    await repository.flush()
    user = User(
        id=owner_id,
        email="owner@example.test",
        display_name="Owner",
        status="active",
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )

    async def override_user() -> User:
        return user

    async def override_service() -> ScanCampaignService:
        return service

    app.dependency_overrides[current_user_dependency] = override_user
    app.dependency_overrides[scan_campaign_service_dependency] = override_service
    path = (
        f"/api/v1/projects/{repository.project.id}/scan-campaigns/{campaign.id}"
        f"/pages/{legal.id}/representative"
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.put(
            path,
            json={"version": legal.version, "selection": "include", "reason": "User review"},
        )
        summary = await client.get(
            f"/api/v1/projects/{repository.project.id}/scan-campaigns/{campaign.id}/summary"
        )
        stale = await client.put(
            path,
            json={"version": 1, "selection": "exclude", "reason": "Stale edit"},
        )

    assert response.status_code == 200
    assert response.json()["manual_selection"] == "include"
    assert response.json()["representative_selected"] is True
    assert home.representative_selected is True
    assert home.representative_rank == 1
    assert summary.json()["page_type_counts"] == {"homepage": 1, "legal": 1}
    assert stale.status_code == 409
    assert audits.entries[-1].action == "crawl_page.representative_override"
