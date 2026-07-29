"""Dataset lifecycle, reproducibility, and source-domain leakage tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest
from platform_api.datasets.build_service import DatasetBuildService
from platform_api.datasets.builder import evaluate_dataset_build
from platform_api.datasets.repository import DatasetCandidate, DatasetRepository
from platform_api.datasets.schemas import (
    DatasetBuildCancelRequest,
    DatasetBuildRetryRequest,
    DatasetBuildStartRequest,
    DatasetCreateRequest,
    DatasetQualityPolicy,
    DatasetVersionCreateRequest,
    DatasetVersionUpdateRequest,
    SelectionPolicy,
)
from platform_api.datasets.service import DatasetService
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.json import JsonValue
from platform_api.persistence.models import (
    AuditLog,
    Dataset,
    DatasetBuild,
    DatasetItem,
    DatasetQualityReport,
    DatasetVersion,
    Project,
)
from platform_api.persistence.pagination import Page
from platform_workflows.dispatcher import DatasetBuildSignal, FakeWorkflowDispatcher
from platform_workflows.identifiers import WorkflowKind

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class RecordingAuditRepository:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def add(self, entry: AuditLog) -> None:
        self.entries.append(entry)


class FakeDatasetRepository(DatasetRepository):
    def __init__(self, project: Project, candidates: tuple[DatasetCandidate, ...]) -> None:
        self.project = project
        self.datasets: dict[UUID, Dataset] = {}
        self.versions: dict[UUID, DatasetVersion] = {}
        self.items: list[DatasetItem] = []
        self.reports: list[DatasetQualityReport] = []
        self.builds: dict[UUID, DatasetBuild] = {}
        self._candidates = candidates

    def add(self, entity: object) -> None:
        if isinstance(entity, Dataset):
            _identity(entity)
            self.datasets[entity.id] = entity
        elif isinstance(entity, DatasetVersion):
            _identity(entity)
            self.versions[entity.id] = entity
        elif isinstance(entity, DatasetQualityReport):
            entity.id = uuid4()
            entity.created_at = NOW
            self.reports.append(entity)
        elif isinstance(entity, DatasetBuild):
            _identity(entity)
            self.builds[entity.id] = entity

    def add_all(self, entities: list[object]) -> None:
        for entity in entities:
            assert isinstance(entity, DatasetItem)
            entity.id = uuid4()
            entity.created_at = NOW
            self.items.append(entity)

    async def flush(self) -> None:
        return None

    async def build_by_idempotency(
        self, version_id: UUID, idempotency_key: str
    ) -> DatasetBuild | None:
        return next(
            (
                item
                for item in self.builds.values()
                if item.dataset_version_id == version_id and item.idempotency_key == idempotency_key
            ),
            None,
        )

    async def active_build(self, version_id: UUID) -> DatasetBuild | None:
        return next(
            (
                item
                for item in self.builds.values()
                if item.dataset_version_id == version_id
                and item.status in {"queued", "running", "cancelling"}
            ),
            None,
        )

    async def build(
        self,
        project_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        build_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> DatasetBuild | None:
        del for_update
        item = self.builds.get(build_id)
        if (
            item is None
            or owner_id != self.project.owner_id
            or (item.project_id, item.dataset_id, item.dataset_version_id)
            != (project_id, dataset_id, version_id)
        ):
            return None
        return item

    async def delete(self, entity: Dataset | DatasetVersion) -> None:
        if isinstance(entity, Dataset):
            self.datasets.pop(entity.id)

    async def owned_project(self, project_id: UUID, owner_id: UUID) -> Project | None:
        return (
            self.project
            if (self.project.id, self.project.owner_id) == (project_id, owner_id)
            else None
        )

    async def name_exists(
        self, project_id: UUID, name: str, *, exclude_id: UUID | None = None
    ) -> bool:
        return any(
            item.project_id == project_id and item.name == name and item.id != exclude_id
            for item in self.datasets.values()
        )

    async def dataset(
        self, project_id: UUID, dataset_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> Dataset | None:
        del for_update
        entity = self.datasets.get(dataset_id)
        if entity is None or entity.project_id != project_id or owner_id != self.project.owner_id:
            return None
        return entity

    async def next_version_number(self, dataset_id: UUID) -> int:
        return 1 + max(
            (
                item.version_number
                for item in self.versions.values()
                if item.dataset_id == dataset_id
            ),
            default=0,
        )

    async def version(
        self,
        project_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> DatasetVersion | None:
        del for_update
        if owner_id != self.project.owner_id or project_id != self.project.id:
            return None
        entity = self.versions.get(version_id)
        return entity if entity is not None and entity.dataset_id == dataset_id else None

    async def candidates(
        self, project_id: UUID, config: SelectionPolicy
    ) -> tuple[DatasetCandidate, ...]:
        assert project_id == self.project.id
        assert config.require_approved
        return self._candidates

    async def clear_items(self, version_id: UUID) -> None:
        self.items = [item for item in self.items if item.dataset_version_id != version_id]

    async def has_sealed_version(self, dataset_id: UUID) -> bool:
        return any(
            item.dataset_id == dataset_id and item.status == "sealed"
            for item in self.versions.values()
        )

    async def latest_quality_report(self, version_id: UUID) -> DatasetQualityReport | None:
        return next(
            (item for item in reversed(self.reports) if item.dataset_version_id == version_id), None
        )

    async def version_page(
        self, dataset_id: UUID, *, limit: int, offset: int
    ) -> Page[DatasetVersion]:
        values = tuple(item for item in self.versions.values() if item.dataset_id == dataset_id)
        return Page(
            items=values[offset : offset + limit], total=len(values), limit=limit, offset=offset
        )

    async def item_page(self, version_id: UUID, *, limit: int, offset: int) -> Page[DatasetItem]:
        values = tuple(item for item in self.items if item.dataset_version_id == version_id)
        return Page(
            items=values[offset : offset + limit], total=len(values), limit=limit, offset=offset
        )


@pytest.mark.anyio
async def test_draft_version_can_change_before_a_workflow_build() -> None:
    owner_id = uuid4()
    project = Project(id=uuid4(), owner_id=owner_id, name="P", slug="p", default_language="en")
    candidates = (
        _candidate("same.example", "section_pattern"),
        _candidate("same.example", "section_pattern"),
        _candidate("other.example", "full_site_spec"),
    )
    repository = FakeDatasetRepository(project, candidates)
    audit = RecordingAuditRepository()
    service = DatasetService(repository, AuditLogService(audit))
    dataset = await service.create(
        project.id,
        DatasetCreateRequest(
            name="Curated patterns",
            purpose="Generate governed layouts",
            item_types=("section_pattern", "full_site_spec"),
        ),
        owner_id=owner_id,
        request_id="create",
    )
    version = await service.create_version(
        project.id,
        dataset.id,
        DatasetVersionCreateRequest(),
        owner_id=owner_id,
        request_id="version",
    )
    changed = await service.update_version(
        project.id,
        dataset.id,
        version.id,
        DatasetVersionUpdateRequest(
            version=version.version, embedding_version="ollama:model@digest"
        ),
        owner_id=owner_id,
        request_id="edit",
    )
    assert changed.status == "draft"
    assert changed.embedding_version == "ollama:model@digest"
    assert repository.items == []


def test_dataset_openapi_exposes_crud_sealing_and_items(app: object) -> None:
    paths = app.openapi()["paths"]  # type: ignore[attr-defined]
    root = "/api/v1/projects/{project_id}/datasets/{dataset_id}"
    version = f"{root}/versions/{{version_id}}"
    assert {"get", "patch", "delete"} <= paths[root].keys()
    builds = f"{version}/builds"
    build = f"{builds}/{{build_id}}"
    assert paths[builds]["post"]["operationId"] == "startDatasetBuild"
    assert paths[build]["get"]["operationId"] == "getDatasetBuild"
    assert paths[f"{build}/cancel"]["post"]["operationId"] == "cancelDatasetBuild"
    assert paths[f"{build}/retry"]["post"]["operationId"] == "retryDatasetBuild"
    assert paths[f"{version}/items"]["get"]["operationId"] == "listDatasetItems"


class RecordingAfterCommit:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[], Awaitable[None]]] = []

    def add(self, name: str, callback: Callable[[], Awaitable[None]]) -> None:
        assert name
        self.callbacks.append(callback)

    async def run(self) -> None:
        callbacks, self.callbacks = self.callbacks, []
        for callback in callbacks:
            await callback()


@pytest.mark.anyio
async def test_dataset_build_start_cancel_and_retry_dispatch_compact_workflows() -> None:
    owner_id = uuid4()
    project = Project(id=uuid4(), owner_id=owner_id, name="P", slug="p", default_language="en")
    repository = FakeDatasetRepository(project, ())
    audit = RecordingAuditRepository()
    lifecycle = DatasetService(repository, AuditLogService(audit))
    dataset = await lifecycle.create(
        project.id,
        DatasetCreateRequest(name="Builds", purpose="Workflow coverage"),
        owner_id=owner_id,
        request_id="dataset",
    )
    version = await lifecycle.create_version(
        project.id,
        dataset.id,
        DatasetVersionCreateRequest(),
        owner_id=owner_id,
        request_id="version",
    )
    dispatcher = FakeWorkflowDispatcher()
    after_commit = RecordingAfterCommit()
    service = DatasetBuildService(repository, AuditLogService(audit), dispatcher, after_commit)

    started = await service.start(
        project.id,
        dataset.id,
        version.id,
        DatasetBuildStartRequest(idempotency_key="build-1"),
        owner_id=owner_id,
        request_id="start",
    )
    await after_commit.run()
    assert started.status == "queued"
    assert dispatcher.dispatched[0][0] is WorkflowKind.DATASET_BUILD
    assert dispatcher.dispatched[0][1].resource_ids == (str(version.id),)

    cancelled = await service.cancel(
        project.id,
        dataset.id,
        version.id,
        started.id,
        DatasetBuildCancelRequest(version=started.version),
        owner_id=owner_id,
        request_id="cancel",
    )
    await after_commit.run()
    assert cancelled.status == "cancelling"
    assert dispatcher.dataset_signals == [(started.workflow_id, DatasetBuildSignal.CANCEL)]
    repository.builds[started.id].status = "cancelled"
    retried = await service.retry(
        project.id,
        dataset.id,
        version.id,
        started.id,
        DatasetBuildRetryRequest(idempotency_key="build-2"),
        owner_id=owner_id,
        request_id="retry",
    )
    assert retried.workflow_attempt == 2
    assert retried.id != started.id


def test_quality_engine_filters_deduplicates_splits_and_reports_distributions() -> None:
    now = NOW
    candidates = (
        _build_candidate("one.example", "hero", "technology", pattern_hash="a"),
        _build_candidate("two.example", "footer", "hospitality", pattern_hash="b"),
        _build_candidate("three.example", "hero", "technology", pattern_hash="c"),
        _build_candidate("four.example", "hero", "technology", pattern_hash="a"),
        _build_candidate("low.example", "hero", "technology", confidence=0.2),
        _build_candidate("removed.example", "hero", "technology", removed=True),
        _build_candidate("suppressed.example", "hero", "technology", suppressed=True),
        _build_candidate(
            "expired.example", "hero", "technology", expires_at=now - timedelta(seconds=1)
        ),
        _build_candidate("rejected.example", "hero", "technology", approval_state="rejected"),
        _build_candidate("provenance.example", "hero", "technology", provenance_state="removed"),
    )
    result = evaluate_dataset_build(
        version_id=uuid4(),
        candidates=candidates,
        selection=SelectionPolicy(minimum_confidence=0.7),
        quality=DatasetQualityPolicy(
            max_domain_share=0.6,
            minimum_category_count=2,
            max_repeated_template_share=0.5,
            required_section_types=("hero", "footer"),
        ),
        schema_version=1,
        now=now,
    )

    assert result.passed
    assert len(result.items) == 3
    assert result.excluded_counts == {
        "duplicate_hash": 1,
        "expired": 1,
        "insufficient_confidence": 1,
        "rejected_or_unapproved": 1,
        "removed": 1,
        "suppressed": 1,
        "unauthorized_provenance": 1,
    }
    assert result.statistics["source_domain_leakage_count"] == 0
    assert result.statistics["section_types"] == {"footer": 1, "hero": 2}
    assert set(cast(dict[str, int], result.statistics["splits"])) == {
        "train",
        "validation",
        "test",
    }


def test_domain_splits_are_case_insensitive_and_cannot_leak() -> None:
    result = evaluate_dataset_build(
        version_id=uuid4(),
        candidates=(
            _build_candidate("Example.COM", "hero", "technology", pattern_hash="a"),
            _build_candidate("example.com", "footer", "technology", pattern_hash="b"),
        ),
        selection=SelectionPolicy(),
        quality=DatasetQualityPolicy(
            max_domain_share=1,
            minimum_category_count=1,
            max_repeated_template_share=1,
        ),
        schema_version=1,
        now=NOW,
    )
    assert result.statistics["source_domain_count"] == 1
    assert result.statistics["source_domain_leakage_count"] == 0
    assert len({item.split for item in result.items}) == 1
    assert "split_leakage" not in {cast(str, finding["code"]) for finding in result.findings}


def test_quality_engine_detects_every_required_content_and_distribution_failure() -> None:
    candidate = _build_candidate(
        "acme.example",
        "hero",
        "technology",
        content={
            "pattern": {
                "schema_version": 2,
                "section_type": "hero",
                "order": 0,
                "copy_purpose": "Visit https://acme.example for the best branded experience available today now",
                "layout": "split",
                "oversized": "x" * 500,
            }
        },
    )
    result = evaluate_dataset_build(
        version_id=uuid4(),
        candidates=(candidate,),
        selection=SelectionPolicy(),
        quality=DatasetQualityPolicy(
            max_domain_share=0.5,
            minimum_category_count=2,
            max_repeated_template_share=0,
            required_section_types=("footer",),
            maximum_serialized_text_chars=256,
        ),
        schema_version=1,
        now=NOW,
    )
    codes = {cast(str, finding["code"]) for finding in result.findings}
    assert {
        "excessive_domain_dependence",
        "low_category_diversity",
        "missing_required_section_types",
        "copied_branding",
        "source_specific_copied_text",
        "oversized_text",
        "schema_mismatch",
        "invalid_tokens",
    } <= codes


def _candidate(
    domain: str, item_type: Literal["section_pattern", "full_site_spec"]
) -> DatasetCandidate:
    return DatasetCandidate(
        item_type=item_type,
        source_record_id=uuid4(),
        campaign_id=uuid4(),
        website_id=uuid4(),
        page_id=uuid4() if item_type == "section_pattern" else None,
        source_domain=domain,
        category="technology",
        language="en",
        confidence=0.9,
        schema_version=1,
        analyzer_version="analyzer-v1",
        content={"abstract": "layout metadata"},
    )


def _build_candidate(
    domain: str,
    section_type: str,
    category: str,
    *,
    pattern_hash: str | None = None,
    confidence: float = 0.9,
    content: JsonValue | None = None,
    approval_state: str = "approved",
    provenance_state: str = "authorized",
    expires_at: datetime | None = None,
    removed: bool = False,
    suppressed: bool = False,
) -> DatasetCandidate:
    pattern = content or {
        "pattern": {
            "schema_version": 1,
            "section_type": section_type,
            "order": 0,
            "copy_purpose": "value-proposition",
            "layout": "split",
            "components": [],
            "responsive_behaviors": [],
        }
    }
    return DatasetCandidate(
        item_type="section_pattern",
        source_record_id=uuid4(),
        campaign_id=uuid4(),
        website_id=uuid4(),
        page_id=uuid4(),
        source_domain=domain,
        category=category,
        language="en",
        confidence=confidence,
        schema_version=1,
        analyzer_version="analyzer-v1",
        content=pattern,
        pattern_hash=pattern_hash,
        section_type=section_type,
        layout="split",
        approval_state=approval_state,
        provenance_state=provenance_state,
        expires_at=expires_at,
        removed=removed,
        suppressed=suppressed,
    )


def _identity(entity: Dataset | DatasetVersion | DatasetBuild) -> None:
    entity.id = uuid4()
    entity.created_at = NOW
    entity.updated_at = NOW
    entity.version = 1
