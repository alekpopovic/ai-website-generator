"""Owner-scoped dataset build commands and Temporal dispatch control."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Protocol
from uuid import UUID, uuid4

from platform_workflows.commands import CompactWorkflowInput
from platform_workflows.dispatcher import (
    DatasetBuildSignal,
    DuplicateWorkflowDispatchError,
    WorkflowDispatcher,
)
from platform_workflows.identifiers import WorkflowKind, workflow_id
from temporalio.exceptions import WorkflowAlreadyStartedError

from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import DatasetBuild

from .repository import DatasetRepository
from .schemas import (
    DatasetBuildCancelRequest,
    DatasetBuildResponse,
    DatasetBuildRetryRequest,
    DatasetBuildStartRequest,
)


class AfterCommitScheduler(Protocol):
    def add(self, name: str, callback: Callable[[], Awaitable[None]]) -> None: ...


class DatasetBuildService:
    def __init__(
        self,
        repository: DatasetRepository,
        audit: AuditLogService,
        dispatcher: WorkflowDispatcher,
        after_commit: AfterCommitScheduler,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._dispatcher = dispatcher
        self._after_commit = after_commit

    async def start(
        self,
        project_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        payload: DatasetBuildStartRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> DatasetBuildResponse:
        dataset = await self._repository.dataset(project_id, dataset_id, owner_id)
        if dataset is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "dataset_not_found", "The dataset was not found.")
        if dataset.status != "active":
            raise self._conflict("dataset_archived", "Archived datasets cannot be built.")
        version = await self._repository.version(
            project_id, dataset_id, version_id, owner_id, for_update=True
        )
        if version is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "dataset_version_not_found",
                "The dataset version was not found.",
            )
        if version.status != "draft":
            raise self._conflict("dataset_version_sealed", "Sealed versions cannot be rebuilt.")
        existing = await self._repository.build_by_idempotency(version_id, payload.idempotency_key)
        if existing is not None:
            return self._response(existing)
        if await self._repository.active_build(version_id) is not None:
            raise self._conflict(
                "dataset_build_in_progress", "This dataset version already has an active build."
            )
        build = DatasetBuild(
            id=uuid4(),
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            requested_by_user_id=owner_id,
            status="queued",
            stage="queued",
            idempotency_key=payload.idempotency_key,
            quality_policy=payload.quality_policy.model_dump(mode="json"),
            enqueue_missing_embeddings=payload.enqueue_missing_embeddings,
            excluded_counts={},
            workflow_attempt=1,
        )
        build.workflow_id = workflow_id(
            WorkflowKind.DATASET_BUILD, project_id, payload.idempotency_key
        )
        self._repository.add(build)
        await self._repository.flush()
        self._record("build_queued", build, owner_id, request_id)
        self._schedule_dispatch(build)
        return self._response(build)

    async def get(
        self,
        project_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        build_id: UUID,
        *,
        owner_id: UUID,
    ) -> DatasetBuildResponse:
        build = await self._owned_build(project_id, dataset_id, version_id, build_id, owner_id)
        return self._response(build)

    async def cancel(
        self,
        project_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        build_id: UUID,
        payload: DatasetBuildCancelRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> DatasetBuildResponse:
        build = await self._owned_build(
            project_id, dataset_id, version_id, build_id, owner_id, for_update=True
        )
        if build.version != payload.version:
            raise self._conflict(
                "optimistic_concurrency_conflict", "The build changed since it was loaded."
            )
        if build.status in {"cancelled", "failed", "succeeded"}:
            return self._response(build)
        build.status = "cancelling"
        build.stage = "cancelling"
        await self._repository.flush()
        self._record("build_cancel_requested", build, owner_id, request_id)
        workflow_identifier = build.workflow_id
        if workflow_identifier is not None:

            async def signal() -> None:
                await self._dispatcher.signal_dataset_build(
                    workflow_identifier, DatasetBuildSignal.CANCEL
                )

            self._after_commit.add(f"dataset-build-cancel:{build.id}", signal)
        return self._response(build)

    async def retry(
        self,
        project_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        build_id: UUID,
        payload: DatasetBuildRetryRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> DatasetBuildResponse:
        dataset = await self._repository.dataset(project_id, dataset_id, owner_id)
        if dataset is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "dataset_not_found", "The dataset was not found.")
        if dataset.status != "active":
            raise self._conflict("dataset_archived", "Archived datasets cannot be retried.")
        previous = await self._owned_build(
            project_id, dataset_id, version_id, build_id, owner_id, for_update=True
        )
        if previous.status not in {"failed", "cancelled"}:
            raise self._conflict(
                "dataset_build_not_retryable", "Only failed or cancelled builds can be retried."
            )
        existing = await self._repository.build_by_idempotency(version_id, payload.idempotency_key)
        if existing is not None:
            return self._response(existing)
        if await self._repository.active_build(version_id) is not None:
            raise self._conflict(
                "dataset_build_in_progress", "This dataset version already has an active build."
            )
        build = DatasetBuild(
            id=uuid4(),
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            requested_by_user_id=owner_id,
            status="queued",
            stage="queued",
            idempotency_key=payload.idempotency_key,
            quality_policy=previous.quality_policy,
            enqueue_missing_embeddings=previous.enqueue_missing_embeddings,
            excluded_counts={},
            workflow_attempt=previous.workflow_attempt + 1,
            workflow_id=workflow_id(
                WorkflowKind.DATASET_BUILD, project_id, payload.idempotency_key
            ),
        )
        self._repository.add(build)
        await self._repository.flush()
        self._record(
            "build_retried",
            build,
            owner_id,
            request_id,
            details={"previous_build_id": str(previous.id)},
        )
        self._schedule_dispatch(build)
        return self._response(build)

    def _schedule_dispatch(self, build: DatasetBuild) -> None:
        command = CompactWorkflowInput(
            job_id=str(build.id),
            project_id=str(build.project_id),
            requested_by_user_id=str(build.requested_by_user_id),
            idempotency_key=build.idempotency_key,
            resource_ids=(str(build.dataset_version_id),),
        )

        async def dispatch() -> None:
            try:
                await self._dispatcher.dispatch(WorkflowKind.DATASET_BUILD, command)
            except (DuplicateWorkflowDispatchError, WorkflowAlreadyStartedError):
                return

        self._after_commit.add(f"dataset-build-dispatch:{build.id}", dispatch)

    async def _owned_build(
        self,
        project_id: UUID,
        dataset_id: UUID,
        version_id: UUID,
        build_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> DatasetBuild:
        build = await self._repository.build(
            project_id,
            dataset_id,
            version_id,
            build_id,
            owner_id,
            for_update=for_update,
        )
        if build is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND, "dataset_build_not_found", "The dataset build was not found."
            )
        return build

    @staticmethod
    def _response(build: DatasetBuild) -> DatasetBuildResponse:
        return DatasetBuildResponse.model_validate(build, from_attributes=True)

    @staticmethod
    def _conflict(code: str, detail: str) -> ApiError:
        return ApiError(HTTPStatus.CONFLICT, code, detail)

    def _record(
        self,
        action: str,
        build: DatasetBuild,
        owner_id: UUID,
        request_id: str,
        *,
        details: object | None = None,
    ) -> None:
        self._audit.record(
            action=f"dataset.{action}",
            resource_type="dataset_build",
            resource_id=build.id,
            actor_user_id=owner_id,
            request_id=request_id,
            details=details,
        )
