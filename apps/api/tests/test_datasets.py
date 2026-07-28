"""Dataset lifecycle, reproducibility, and source-domain leakage tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest
from platform_api.datasets.repository import DatasetCandidate, DatasetRepository
from platform_api.datasets.schemas import (
    DatasetCreateRequest,
    DatasetVersionCreateRequest,
    DatasetVersionUpdateRequest,
    SealDatasetVersionRequest,
    SelectionPolicy,
)
from platform_api.datasets.service import DatasetService, _domain_split
from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import (
    AuditLog,
    Dataset,
    DatasetItem,
    DatasetQualityReport,
    DatasetVersion,
    Project,
)
from platform_api.persistence.pagination import Page

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

    def add_all(self, entities: list[object]) -> None:
        for entity in entities:
            assert isinstance(entity, DatasetItem)
            entity.id = uuid4()
            entity.created_at = NOW
            self.items.append(entity)

    async def flush(self) -> None:
        return None

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
async def test_draft_can_change_then_seal_is_immutable_and_reproducible() -> None:
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
    sealed = await service.seal(
        project.id,
        dataset.id,
        version.id,
        SealDatasetVersionRequest(version=changed.version),
        owner_id=owner_id,
        request_id="seal",
    )

    assert sealed.version.status == "sealed"
    assert sealed.version.manifest_sha256 is not None
    assert sealed.quality_report is not None and sealed.quality_report.status == "passed"
    domain_splits: dict[str, set[str]] = {}
    for item in repository.items:
        domain_splits.setdefault(item.source_domain, set()).add(item.split)
        assert cast(dict[str, object], item.source_reference)["prompt_default"] == "excluded"
    assert all(len(splits) == 1 for splits in domain_splits.values())
    assert sealed.version.statistics["source_domain_leakage_count"] == 0

    with pytest.raises(ApiError) as immutable:
        await service.update_version(
            project.id,
            dataset.id,
            version.id,
            DatasetVersionUpdateRequest(version=changed.version, schema_version=2),
            owner_id=owner_id,
            request_id="late-edit",
        )
    assert immutable.value.code == "dataset_version_sealed"
    assert [entry.action for entry in audit.entries][-1] == "dataset.version_sealed"


def test_source_domain_split_is_stable_and_case_insensitive() -> None:
    assert _domain_split("Example.COM") == _domain_split("example.com")


def test_dataset_openapi_exposes_crud_sealing_and_items(app: object) -> None:
    paths = app.openapi()["paths"]  # type: ignore[attr-defined]
    root = "/api/v1/projects/{project_id}/datasets/{dataset_id}"
    version = f"{root}/versions/{{version_id}}"
    assert {"get", "patch", "delete"} <= paths[root].keys()
    assert paths[f"{version}/seal"]["post"]["operationId"] == "sealDatasetVersion"
    assert paths[f"{version}/items"]["get"]["operationId"] == "listDatasetItems"


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


def _identity(entity: Dataset | DatasetVersion) -> None:
    entity.id = uuid4()
    entity.created_at = NOW
    entity.updated_at = NOW
    entity.version = 1
