"""Control-plane workflow dispatch boundary and deterministic fake."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from temporalio.client import Client

from platform_workflows.commands import CompactWorkflowInput, ModelWarmupInput, WorkflowResult
from platform_workflows.identifiers import (
    WORKFLOW_ID_CONFLICT_POLICY,
    WORKFLOW_ID_REUSE_POLICY,
    WorkflowKind,
    workflow_id,
)
from platform_workflows.queues import TaskQueue


@dataclass(frozen=True, slots=True)
class WorkflowDispatch:
    """Safe workflow start acknowledgement for persistence and API responses."""

    workflow_id: str
    run_id: str | None


class WorkflowDispatcher(Protocol):
    """Boundary used by the FastAPI control plane after authorization and commit."""

    async def dispatch(
        self, kind: WorkflowKind, command: CompactWorkflowInput
    ) -> WorkflowDispatch: ...

    async def dispatch_model_warmup(self, command: ModelWarmupInput) -> WorkflowDispatch: ...


class TemporalClientSource(Protocol):
    """Lazy client source used to avoid startup dependency coupling."""

    async def get(self) -> Client: ...


_WORKFLOW_NAMES = {
    WorkflowKind.SCAN_CAMPAIGN: "ScanCampaignWorkflow",
    WorkflowKind.DATASET_BUILD: "DatasetBuildWorkflow",
    WorkflowKind.SITE_GENERATION: "SiteGenerationWorkflow",
    WorkflowKind.TRAINING_RUN: "TrainingRunWorkflow",
}
_EXECUTION_TIMEOUTS = {
    WorkflowKind.SCAN_CAMPAIGN: timedelta(hours=4),
    WorkflowKind.DATASET_BUILD: timedelta(hours=4),
    WorkflowKind.SITE_GENERATION: timedelta(hours=2),
    WorkflowKind.TRAINING_RUN: timedelta(days=2),
}


class TemporalWorkflowDispatcher:
    """Start named workflows with duplicate-safe identity semantics."""

    def __init__(self, clients: TemporalClientSource) -> None:
        self._clients = clients

    async def dispatch(self, kind: WorkflowKind, command: CompactWorkflowInput) -> WorkflowDispatch:
        if kind is WorkflowKind.MODEL_WARMUP:
            raise ValueError("model warm-up requires dispatch_model_warmup")
        client = await self._clients.get()
        dispatch_id = workflow_id(kind, command.project_id, command.idempotency_key)
        handle = await client.start_workflow(
            _WORKFLOW_NAMES[kind],
            command,
            id=dispatch_id,
            task_queue=TaskQueue.CONTROL.value,
            result_type=WorkflowResult,
            execution_timeout=_EXECUTION_TIMEOUTS[kind],
            id_reuse_policy=WORKFLOW_ID_REUSE_POLICY,
            id_conflict_policy=WORKFLOW_ID_CONFLICT_POLICY,
        )
        return WorkflowDispatch(workflow_id=handle.id, run_id=handle.first_execution_run_id)

    async def dispatch_model_warmup(self, command: ModelWarmupInput) -> WorkflowDispatch:
        client = await self._clients.get()
        dispatch_id = workflow_id(
            WorkflowKind.MODEL_WARMUP,
            command.requested_by_user_id,
            command.idempotency_key,
        )
        handle = await client.start_workflow(
            "ModelWarmupWorkflow",
            command,
            id=dispatch_id,
            task_queue=TaskQueue.CONTROL.value,
            result_type=WorkflowResult,
            execution_timeout=timedelta(minutes=20),
            id_reuse_policy=WORKFLOW_ID_REUSE_POLICY,
            id_conflict_policy=WORKFLOW_ID_CONFLICT_POLICY,
        )
        return WorkflowDispatch(workflow_id=handle.id, run_id=handle.first_execution_run_id)


class DuplicateWorkflowDispatchError(RuntimeError):
    """Raised by the fake when one logical command is submitted twice."""


class FakeWorkflowDispatcher:
    """No-I/O workflow dispatcher for API unit tests and fake dependency mode."""

    def __init__(self) -> None:
        self.dispatched: list[tuple[WorkflowKind, CompactWorkflowInput]] = []
        self.warmups: list[ModelWarmupInput] = []
        self._workflow_ids: set[str] = set()

    async def dispatch(self, kind: WorkflowKind, command: CompactWorkflowInput) -> WorkflowDispatch:
        if kind is WorkflowKind.MODEL_WARMUP:
            raise ValueError("model warm-up requires dispatch_model_warmup")
        dispatch_id = workflow_id(kind, command.project_id, command.idempotency_key)
        if dispatch_id in self._workflow_ids:
            raise DuplicateWorkflowDispatchError(dispatch_id)
        self._workflow_ids.add(dispatch_id)
        self.dispatched.append((kind, command))
        return WorkflowDispatch(workflow_id=dispatch_id, run_id=None)

    async def dispatch_model_warmup(self, command: ModelWarmupInput) -> WorkflowDispatch:
        dispatch_id = workflow_id(
            WorkflowKind.MODEL_WARMUP,
            command.requested_by_user_id,
            command.idempotency_key,
        )
        if dispatch_id in self._workflow_ids:
            raise DuplicateWorkflowDispatchError(dispatch_id)
        self._workflow_ids.add(dispatch_id)
        self.warmups.append(command)
        return WorkflowDispatch(workflow_id=dispatch_id, run_id=None)
