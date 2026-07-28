"""Control-plane-only creation and observation of worker embedding runs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Protocol
from uuid import UUID, uuid4

from platform_workflows.commands import EmbeddingIndexInput
from platform_workflows.dispatcher import (
    DuplicateWorkflowDispatchError,
    WorkflowDispatcher,
)
from platform_workflows.identifiers import WorkflowKind, workflow_id
from temporalio.exceptions import WorkflowAlreadyStartedError

from platform_api.config import QdrantSettings
from platform_api.embedding.repository import EmbeddingRunRepository
from platform_api.embedding.schemas import (
    EmbeddingFailureResponse,
    EmbeddingRunCreateRequest,
    EmbeddingRunResponse,
)
from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import EmbeddingRun
from platform_api.persistence.pagination import Page


class AfterCommitScheduler(Protocol):
    def add(self, name: str, callback: Callable[[], Awaitable[None]]) -> None: ...


class EmbeddingRunService:
    def __init__(
        self,
        repository: EmbeddingRunRepository,
        audit: AuditLogService,
        dispatcher: WorkflowDispatcher,
        after_commit: AfterCommitScheduler,
        qdrant: QdrantSettings,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._dispatcher = dispatcher
        self._after_commit = after_commit
        self._qdrant = qdrant

    async def create(
        self,
        project_id: UUID,
        payload: EmbeddingRunCreateRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> EmbeddingRunResponse:
        # Serialize creation per project so the idempotency lookup and insert
        # remain one race-safe transaction.
        if not await self._repository.owns_project(project_id, owner_id, for_update=True):
            raise ApiError(HTTPStatus.NOT_FOUND, "project_not_found", "Project was not found.")
        existing = await self._repository.by_idempotency(project_id, payload.idempotency_key)
        if existing is not None:
            return EmbeddingRunResponse.model_validate(existing)
        run = EmbeddingRun(
            id=uuid4(),
            project_id=project_id,
            requested_by_user_id=owner_id,
            kind=payload.kind,
            status="queued",
            idempotency_key=payload.idempotency_key,
            batch_size=payload.batch_size,
            promote_alias=payload.promote_alias,
            collection_alias=self._qdrant.collection_alias,
            serialization_schema_version=self._qdrant.serialization_schema_version,
            vector_name=self._qdrant.vector_name,
            total_patterns=0,
            processed_patterns=0,
            indexed_patterns=0,
            deleted_patterns=0,
            failed_patterns=0,
        )
        run.workflow_id = workflow_id(
            WorkflowKind.EMBEDDING_INDEX, project_id, payload.idempotency_key
        )
        self._repository.add(run)
        await self._repository.flush()
        self._audit.record(
            action="embedding_run.queued",
            resource_type="embedding_run",
            resource_id=run.id,
            actor_user_id=owner_id,
            request_id=request_id,
            details={"kind": run.kind, "promote_alias": run.promote_alias},
        )

        async def dispatch() -> None:
            try:
                await self._dispatcher.dispatch_embedding_index(
                    EmbeddingIndexInput(str(run.id)),
                    project_id=str(project_id),
                    idempotency_key=payload.idempotency_key,
                )
            except (DuplicateWorkflowDispatchError, WorkflowAlreadyStartedError):
                return

        self._after_commit.add(f"embedding-index-dispatch:{run.id}", dispatch)
        return EmbeddingRunResponse.model_validate(run)

    async def get(self, project_id: UUID, run_id: UUID, *, owner_id: UUID) -> EmbeddingRunResponse:
        run = await self._repository.owned(run_id, project_id, owner_id)
        if run is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND, "embedding_run_not_found", "Embedding run was not found."
            )
        return EmbeddingRunResponse.model_validate(run)

    async def list(
        self, project_id: UUID, *, owner_id: UUID, limit: int, offset: int
    ) -> Page[EmbeddingRunResponse]:
        page = await self._repository.page(
            project_id=project_id, owner_id=owner_id, limit=limit, offset=offset
        )
        if page is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "project_not_found", "Project was not found.")
        return Page(
            tuple(EmbeddingRunResponse.model_validate(item) for item in page.items),
            page.total,
            limit,
            offset,
        )

    async def failures(
        self, project_id: UUID, run_id: UUID, *, owner_id: UUID, limit: int, offset: int
    ) -> Page[EmbeddingFailureResponse]:
        page = await self._repository.failure_page(
            run_id=run_id, project_id=project_id, owner_id=owner_id, limit=limit, offset=offset
        )
        if page is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND, "embedding_run_not_found", "Embedding run was not found."
            )
        return Page(
            tuple(EmbeddingFailureResponse.model_validate(item) for item in page.items),
            page.total,
            limit,
            offset,
        )
