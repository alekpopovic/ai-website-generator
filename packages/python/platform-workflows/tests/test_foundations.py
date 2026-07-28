"""Unit tests for shared Temporal foundations without external services."""

import asyncio
from uuid import uuid4

import pytest
from platform_workflows.cancellation import raise_if_activity_cancelled
from platform_workflows.commands import (
    CompactWorkflowInput,
    EmbeddingIndexInput,
    ModelWarmupInput,
    ScanCampaignPlan,
    ScanIdentifierPage,
    ScanTargetWorkflowInput,
)
from platform_workflows.dispatcher import (
    DuplicateWorkflowDispatchError,
    FakeWorkflowDispatcher,
    ScanCampaignSignal,
)
from platform_workflows.events import InMemoryJobEventPublisher, JobEvent
from platform_workflows.heartbeat import ActivityHeartbeat
from platform_workflows.identifiers import ModelRole, WorkflowKind, workflow_id
from platform_workflows.queues import TaskQueue
from platform_workflows.retry import ActivityCategory, retry_policy
from platform_workflows.worker import WorkerHealthIndicator, WorkerState
from platform_workflows.workflows import WORKFLOW_TYPES, ScanTargetWorkflow
from temporalio import activity
from temporalio.testing import ActivityEnvironment


def command() -> CompactWorkflowInput:
    return CompactWorkflowInput(
        job_id=str(uuid4()),
        project_id=str(uuid4()),
        requested_by_user_id=str(uuid4()),
        idempotency_key="request-001",
        input_object_key="datasets/input/manifest.json",
    )


def test_task_queue_names_are_stable_and_complete() -> None:
    assert [queue.value for queue in TaskQueue] == [
        "control",
        "crawl",
        "browser",
        "ai-analysis",
        "embedding",
        "generation",
        "render",
        "validation",
        "training",
    ]


def test_workflow_id_is_duplicate_safe_and_validated() -> None:
    resource_id = uuid4()
    assert workflow_id(WorkflowKind.SCAN_CAMPAIGN, resource_id, "request-001") == (
        f"aiwg:scan-campaign:{resource_id}:request-001"
    )
    assert workflow_id(WorkflowKind.ARTIFACT_DELETION, resource_id, "removal-001") == (
        f"aiwg:artifact-deletion:{resource_id}:removal-001"
    )
    with pytest.raises(ValueError, match="idempotency_key"):
        workflow_id(WorkflowKind.SCAN_CAMPAIGN, resource_id, "unsafe key")


def test_compact_commands_reject_non_ids_and_unbounded_payload_shapes() -> None:
    with pytest.raises(ValueError, match="job_id"):
        CompactWorkflowInput(
            job_id="not-an-id",
            project_id=str(uuid4()),
            requested_by_user_id=str(uuid4()),
            idempotency_key="request",
        )


def test_scan_workflow_contracts_bound_history_and_concurrency() -> None:
    campaign_id = str(uuid4())
    project_id = str(uuid4())
    target_id = str(uuid4())
    plan = ScanCampaignPlan(campaign_id, 8, 4, 2)
    target = ScanTargetWorkflowInput(campaign_id, project_id, target_id, 4, 2)
    page = ScanIdentifierPage((target_id,))

    assert plan.page_size == 100
    assert target.browser_concurrency != target.ai_concurrency
    assert page.identifiers == (target_id,)
    assert ScanTargetWorkflow in WORKFLOW_TYPES
    with pytest.raises(ValueError, match="at most 100"):
        ScanIdentifierPage(tuple(str(uuid4()) for _ in range(101)))
    with pytest.raises(ValueError, match="object-storage key"):
        CompactWorkflowInput(
            job_id=str(uuid4()),
            project_id=str(uuid4()),
            requested_by_user_id=str(uuid4()),
            idempotency_key="request",
            input_object_key="<html>large payload</html>",
        )


@pytest.mark.anyio
async def test_fake_dispatcher_records_once_and_rejects_duplicate_run() -> None:
    dispatcher = FakeWorkflowDispatcher()
    workflow_command = command()

    dispatched = await dispatcher.dispatch(WorkflowKind.DATASET_BUILD, workflow_command)

    assert dispatched.workflow_id.startswith("aiwg:dataset-build:")
    assert dispatcher.dispatched == [(WorkflowKind.DATASET_BUILD, workflow_command)]
    with pytest.raises(DuplicateWorkflowDispatchError):
        await dispatcher.dispatch(WorkflowKind.DATASET_BUILD, workflow_command)


@pytest.mark.anyio
async def test_fake_dispatcher_records_scan_control_signals() -> None:
    dispatcher = FakeWorkflowDispatcher()
    workflow_command = command()
    dispatched = await dispatcher.dispatch(WorkflowKind.SCAN_CAMPAIGN, workflow_command)

    await dispatcher.signal_scan_campaign(dispatched.workflow_id, ScanCampaignSignal.PAUSE)
    await dispatcher.signal_scan_campaign(dispatched.workflow_id, ScanCampaignSignal.RESUME)
    await dispatcher.signal_scan_campaign(dispatched.workflow_id, ScanCampaignSignal.CANCEL)

    assert dispatcher.scan_signals == [
        (dispatched.workflow_id, ScanCampaignSignal.PAUSE),
        (dispatched.workflow_id, ScanCampaignSignal.RESUME),
        (dispatched.workflow_id, ScanCampaignSignal.CANCEL),
    ]


@pytest.mark.anyio
async def test_model_warmup_dispatch_is_compact_and_duplicate_safe() -> None:
    dispatcher = FakeWorkflowDispatcher()
    command = ModelWarmupInput(
        job_id=str(uuid4()),
        requested_by_user_id=str(uuid4()),
        idempotency_key="warmup-001",
        model_role=ModelRole.VISION,
    )

    dispatched = await dispatcher.dispatch_model_warmup(command)

    assert dispatched.workflow_id.startswith("aiwg:model-warmup:")
    assert dispatcher.warmups == [command]
    with pytest.raises(DuplicateWorkflowDispatchError):
        await dispatcher.dispatch_model_warmup(command)


@pytest.mark.anyio
async def test_embedding_dispatch_accepts_only_run_and_project_identifiers() -> None:
    dispatcher = FakeWorkflowDispatcher()
    project_id = str(uuid4())
    command = EmbeddingIndexInput(str(uuid4()))

    dispatched = await dispatcher.dispatch_embedding_index(
        command, project_id=project_id, idempotency_key="embedding-001"
    )

    assert dispatched.workflow_id.startswith("aiwg:embedding-index:")
    assert dispatcher.embedding_indexes == [command]
    with pytest.raises(DuplicateWorkflowDispatchError):
        await dispatcher.dispatch_embedding_index(
            command, project_id=project_id, idempotency_key="embedding-001"
        )


@pytest.mark.anyio
async def test_job_event_fake_records_compact_event() -> None:
    publisher = InMemoryJobEventPublisher()
    job_id = str(uuid4())
    event = JobEvent.create(
        job_id=job_id,
        project_id=str(uuid4()),
        sequence=3,
        event_type="scan.progress",
        status="running",
    )

    assert await publisher.publish(event) == "fake-1"
    assert publisher.events == [event]
    assert event.event_id == f"{job_id}:3"


@pytest.mark.anyio
async def test_heartbeat_reports_progress_in_activity_environment() -> None:
    heartbeats: list[tuple[object, ...]] = []
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *details: heartbeats.append(details)

    @activity.defn
    async def heartbeat_activity() -> None:
        reporter = ActivityHeartbeat()
        reporter.report(stage="crawl", completed=3)
        await reporter.while_running(asyncio.sleep(0), stage="crawl")

    await environment.run(heartbeat_activity)

    assert heartbeats == [({"stage": "crawl", "completed": 3},)]


@pytest.mark.anyio
async def test_activity_cancellation_helper_stops_at_checkpoint() -> None:
    environment = ActivityEnvironment()
    environment.cancel()

    @activity.defn
    async def cancellable_activity() -> None:
        raise_if_activity_cancelled()

    with pytest.raises(asyncio.CancelledError):
        await environment.run(cancellable_activity)


def test_retry_policies_are_bounded() -> None:
    for category in ActivityCategory:
        policy = retry_policy(category)
        assert policy.maximum_attempts > 0
        assert policy.maximum_attempts <= 7
        assert policy.maximum_interval is not None


def test_worker_health_indicator_exposes_readiness_transitions() -> None:
    health = WorkerHealthIndicator("crawler-worker", TaskQueue.CRAWL)
    assert not health.snapshot().ready

    health.transition(WorkerState.READY)

    snapshot = health.snapshot()
    assert snapshot.ready
    assert snapshot.task_queue == "crawl"
