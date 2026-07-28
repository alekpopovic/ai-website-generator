"""Embedding control-plane dispatch, idempotency, and progress tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from platform_api.config import QdrantSettings
from platform_api.dependencies import AfterCommitActions
from platform_api.embedding.schemas import EmbeddingRunCreateRequest
from platform_api.embedding.service import EmbeddingRunService
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import AuditLog, EmbeddingRun
from platform_workflows.dispatcher import FakeWorkflowDispatcher

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class FakeEmbeddingRunRepository:
    def __init__(self, *, owner_id: UUID) -> None:
        self.owner_id = owner_id
        self.runs: dict[UUID, EmbeddingRun] = {}

    def add(self, run: EmbeddingRun) -> None:
        run.created_at = NOW
        run.updated_at = NOW
        run.version = 1
        self.runs[run.id] = run

    async def flush(self) -> None:
        return None

    async def owns_project(
        self, project_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> bool:
        return owner_id == self.owner_id

    async def by_idempotency(self, project_id: UUID, key: str) -> EmbeddingRun | None:
        return next(
            (
                run
                for run in self.runs.values()
                if run.project_id == project_id and run.idempotency_key == key
            ),
            None,
        )


class RecordingAuditRepository:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def add(self, entry: AuditLog) -> None:
        self.entries.append(entry)


@pytest.mark.anyio
async def test_create_queues_identifier_only_temporal_work_after_commit() -> None:
    owner_id, project_id = uuid4(), uuid4()
    repository = FakeEmbeddingRunRepository(owner_id=owner_id)
    dispatcher = FakeWorkflowDispatcher()
    after_commit = AfterCommitActions()
    audits = RecordingAuditRepository()
    service = EmbeddingRunService(
        repository,  # type: ignore[arg-type]
        AuditLogService(audits),
        dispatcher,
        after_commit,
        QdrantSettings(),
    )

    run = await service.create(
        project_id,
        EmbeddingRunCreateRequest(
            kind="reindex",
            idempotency_key="reindex-001",
            batch_size=32,
            promote_alias=True,
        ),
        owner_id=owner_id,
        request_id="request-001",
    )

    assert run.status == "queued"
    assert dispatcher.embedding_indexes == []
    await after_commit.run()
    assert dispatcher.embedding_indexes[0].embedding_run_id == str(run.id)
    assert audits.entries[0].details == {"kind": "reindex", "promote_alias": True}


@pytest.mark.anyio
async def test_idempotency_key_returns_existing_run_without_second_dispatch() -> None:
    owner_id, project_id = uuid4(), uuid4()
    repository = FakeEmbeddingRunRepository(owner_id=owner_id)
    dispatcher = FakeWorkflowDispatcher()
    after_commit = AfterCommitActions()
    service = EmbeddingRunService(
        repository,  # type: ignore[arg-type]
        AuditLogService(RecordingAuditRepository()),
        dispatcher,
        after_commit,
        QdrantSettings(),
    )
    payload = EmbeddingRunCreateRequest(idempotency_key="incremental-001")

    first = await service.create(project_id, payload, owner_id=owner_id, request_id="request-1")
    second = await service.create(project_id, payload, owner_id=owner_id, request_id="request-2")
    await after_commit.run()

    assert second.id == first.id
    assert len(dispatcher.embedding_indexes) == 1


def test_incremental_run_cannot_switch_collection_alias() -> None:
    with pytest.raises(ValueError, match="alias promotion"):
        EmbeddingRunCreateRequest(
            kind="incremental", idempotency_key="unsafe-promotion", promote_alias=True
        )
