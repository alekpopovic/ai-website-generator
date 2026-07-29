"""Temporal test-environment coverage for deterministic workflow skeletons."""

from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from platform_workflows.commands import (
    ActivityCommand,
    ActivityResult,
    CompactWorkflowInput,
    CrawlTargetInput,
    DatasetBuildStageInput,
    DatasetBuildStageResult,
    EmbeddingIndexInput,
    ModelWarmupInput,
    RenderPageInput,
    ScanAggregationInput,
    ScanCampaignPlan,
    ScanIdentifierPage,
    ScanListInput,
    ScanPageInput,
    ScanProgressInput,
    WorkflowResult,
)
from platform_workflows.identifiers import ModelRole
from platform_workflows.queues import TaskQueue
from platform_workflows.testing import TemporalTestServerConfig, temporal_test_environment
from platform_workflows.workflows import (
    DatasetBuildWorkflow,
    ModelWarmupWorkflow,
    ScanCampaignWorkflow,
    ScanTargetWorkflow,
    SiteGenerationWorkflow,
    TrainingRunWorkflow,
)
from temporalio import activity
from temporalio.worker import Worker

pytestmark = pytest.mark.integration

_ACTIVITY_QUEUES = {
    "prepare-generation": TaskQueue.CONTROL,
    "analyze-generation": TaskQueue.AI_ANALYSIS,
    "generate-site-spec": TaskQueue.GENERATION,
    "render-site": TaskQueue.RENDER,
    "validate-site": TaskQueue.VALIDATION,
    "complete-generation": TaskQueue.CONTROL,
    "prepare-training": TaskQueue.CONTROL,
    "run-training": TaskQueue.TRAINING,
    "validate-training": TaskQueue.VALIDATION,
    "complete-training": TaskQueue.CONTROL,
}


def _test_server_exists(config: TemporalTestServerConfig) -> bool:
    return Path(config.executable).is_file()


def fake_activity(name: str):  # type: ignore[no-untyped-def]
    @activity.defn(name=name)
    async def run(command: ActivityCommand) -> ActivityResult:
        activity.heartbeat({"stage": command.stage})
        return ActivityResult(
            record_id=command.job_id,
            output_object_key=f"workflow-tests/{command.job_id}/{command.stage}.json",
        )

    return run


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("workflow_type", "workflow_name", "name"),
    [
        (SiteGenerationWorkflow, "SiteGenerationWorkflow", "generation"),
        (TrainingRunWorkflow, "TrainingRunWorkflow", "training"),
    ],
)
async def test_workflow_skeleton_runs_with_fake_activities(
    workflow_type: type[Any], workflow_name: str, name: str
) -> None:
    config = TemporalTestServerConfig.from_environment()
    if config is None or not _test_server_exists(config):
        pytest.skip("TEMPORAL_TEST_SERVER_PATH is not configured to an existing binary")
    activities = {activity_name: fake_activity(activity_name) for activity_name in _ACTIVITY_QUEUES}
    job_id = str(uuid4())
    command = CompactWorkflowInput(
        job_id=job_id,
        project_id=str(uuid4()),
        requested_by_user_id=str(uuid4()),
        idempotency_key=f"{name}-request",
    )

    async with temporal_test_environment(config) as environment, AsyncExitStack() as workers:
        for queue in TaskQueue:
            queue_activities = [
                activities[activity_name]
                for activity_name, activity_queue in _ACTIVITY_QUEUES.items()
                if activity_queue is queue
            ]
            await workers.enter_async_context(
                Worker(
                    environment.client,
                    task_queue=queue.value,
                    workflows=[workflow_type] if queue is TaskQueue.CONTROL else [],
                    activities=queue_activities,
                )
            )
        result = await environment.client.execute_workflow(
            workflow_name,
            command,
            id=f"workflow-test-{name}-{job_id}",
            task_queue=TaskQueue.CONTROL.value,
            result_type=WorkflowResult,
        )

    assert result.status == "completed"
    assert result.job_id == job_id
    assert result.output_object_key is not None


@activity.defn(name="run-dataset-build-stage")
async def fake_dataset_stage(command: DatasetBuildStageInput) -> DatasetBuildStageResult:
    activity.heartbeat({"stage": command.stage})
    return DatasetBuildStageResult(
        command.build_id,
        "sealed" if command.stage == "seal-dataset-version" else "passed",
    )


@pytest.mark.anyio
async def test_dataset_build_workflow_runs_all_governance_stages() -> None:
    config = TemporalTestServerConfig.from_environment()
    if config is None or not _test_server_exists(config):
        pytest.skip("TEMPORAL_TEST_SERVER_PATH is not configured to an existing binary")
    job_id = str(uuid4())
    command = CompactWorkflowInput(
        job_id=job_id,
        project_id=str(uuid4()),
        requested_by_user_id=str(uuid4()),
        idempotency_key="dataset-request",
    )
    async with (
        temporal_test_environment(config) as environment,
        Worker(
            environment.client,
            task_queue=TaskQueue.CONTROL.value,
            workflows=[DatasetBuildWorkflow],
            activities=[fake_dataset_stage],
        ),
    ):
        result = await environment.client.execute_workflow(
            DatasetBuildWorkflow.run,
            command,
            id=f"workflow-test-dataset-{job_id}",
            task_queue=TaskQueue.CONTROL.value,
        )
    assert result.status == "completed"
    assert result.job_id == job_id


@activity.defn(name="validate-scan-campaign")
async def fake_scan_validate(command: CompactWorkflowInput) -> ScanCampaignPlan:
    return ScanCampaignPlan(command.job_id, 2, 2, 1)


@activity.defn(name="list-scan-targets")
async def fake_scan_targets(command: ScanListInput) -> ScanIdentifierPage:
    return ScanIdentifierPage((str(uuid4()),))


@activity.defn(name="list-representative-pages")
async def fake_representatives(command: ScanListInput) -> ScanIdentifierPage:
    return ScanIdentifierPage((str(uuid4()),))


def fake_scan_stage(name: str):  # type: ignore[no-untyped-def]
    @activity.defn(name=name)
    async def run(command: CrawlTargetInput) -> ActivityResult:
        activity.heartbeat({"stage": name})
        return ActivityResult(command.scan_target_id)

    return run


@activity.defn(name="render-representative-page")
async def fake_scan_render(command: RenderPageInput) -> ActivityResult:
    return ActivityResult(command.crawl_page_id)


@activity.defn(name="analyze-and-persist-page-profile")
async def fake_scan_analysis(command: ScanPageInput) -> ActivityResult:
    return ActivityResult(str(uuid4()))


@activity.defn(name="persist-scan-progress")
async def fake_scan_progress(command: ScanProgressInput) -> ActivityResult:
    return ActivityResult(command.campaign_id)


@activity.defn(name="prepare-scan-embedding")
async def fake_scan_embedding_run(command: CompactWorkflowInput) -> ActivityResult:
    return ActivityResult(str(uuid4()))


@activity.defn(name="index-section-patterns")
async def fake_scan_embedding(command: EmbeddingIndexInput) -> ActivityResult:
    return ActivityResult(command.embedding_run_id)


@activity.defn(name="aggregate-scan-campaign")
async def fake_scan_aggregate(command: ScanAggregationInput) -> ActivityResult:
    return ActivityResult(command.campaign_id)


@pytest.mark.anyio
async def test_scan_workflow_runs_complete_identifier_only_pipeline() -> None:
    config = TemporalTestServerConfig.from_environment()
    if config is None or not _test_server_exists(config):
        pytest.skip("TEMPORAL_TEST_SERVER_PATH is not configured to an existing binary")
    command = CompactWorkflowInput(
        job_id=str(uuid4()),
        project_id=str(uuid4()),
        requested_by_user_id=str(uuid4()),
        idempotency_key="scan-pipeline",
    )
    stages = [
        fake_scan_stage("crawl-scan-target"),
        fake_scan_stage("fingerprint-scan-target"),
        fake_scan_stage("classify-scan-target"),
        fake_scan_stage("select-scan-representatives"),
    ]
    async with temporal_test_environment(config) as environment, AsyncExitStack() as workers:
        await workers.enter_async_context(
            Worker(
                environment.client,
                task_queue=TaskQueue.CONTROL.value,
                workflows=[ScanCampaignWorkflow, ScanTargetWorkflow],
                activities=[
                    fake_scan_validate,
                    fake_scan_targets,
                    fake_representatives,
                    fake_scan_progress,
                    fake_scan_embedding_run,
                    fake_scan_aggregate,
                ],
            )
        )
        await workers.enter_async_context(
            Worker(environment.client, task_queue=TaskQueue.CRAWL.value, activities=stages)
        )
        await workers.enter_async_context(
            Worker(
                environment.client,
                task_queue=TaskQueue.BROWSER.value,
                activities=[fake_scan_render],
            )
        )
        await workers.enter_async_context(
            Worker(
                environment.client,
                task_queue=TaskQueue.AI_ANALYSIS.value,
                activities=[fake_scan_analysis],
            )
        )
        await workers.enter_async_context(
            Worker(
                environment.client,
                task_queue=TaskQueue.EMBEDDING.value,
                activities=[fake_scan_embedding],
            )
        )
        result = await environment.client.execute_workflow(
            "ScanCampaignWorkflow",
            command,
            id=f"workflow-test-scan-{command.job_id}",
            task_queue=TaskQueue.CONTROL.value,
            result_type=WorkflowResult,
        )

    assert result == WorkflowResult(job_id=command.job_id, status="completed")


@activity.defn(name="warm-up-model")
async def fake_model_warmup(command: ModelWarmupInput) -> ActivityResult:
    activity.heartbeat({"stage": "warm-up-model"})
    return ActivityResult(record_id=command.job_id)


@pytest.mark.anyio
async def test_model_warmup_workflow_routes_only_compact_role_to_ai_worker() -> None:
    config = TemporalTestServerConfig.from_environment()
    if config is None or not _test_server_exists(config):
        pytest.skip("TEMPORAL_TEST_SERVER_PATH is not configured to an existing binary")
    command = ModelWarmupInput(
        job_id=str(uuid4()),
        requested_by_user_id=str(uuid4()),
        idempotency_key="warmup-request",
        model_role=ModelRole.VISION,
    )

    async with temporal_test_environment(config) as environment, AsyncExitStack() as workers:
        await workers.enter_async_context(
            Worker(
                environment.client,
                task_queue=TaskQueue.CONTROL.value,
                workflows=[ModelWarmupWorkflow],
            )
        )
        await workers.enter_async_context(
            Worker(
                environment.client,
                task_queue=TaskQueue.AI_ANALYSIS.value,
                activities=[fake_model_warmup],
            )
        )
        result = await environment.client.execute_workflow(
            "ModelWarmupWorkflow",
            command,
            id=f"workflow-test-warmup-{command.job_id}",
            task_queue=TaskQueue.CONTROL.value,
            result_type=WorkflowResult,
        )

    assert result == WorkflowResult(job_id=command.job_id, status="completed")
