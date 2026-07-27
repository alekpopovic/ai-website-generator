"""Deterministic orchestration skeletons with no external calls."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.workflow import ActivityCancellationType

from platform_workflows.commands import (
    ActivityCommand,
    ActivityResult,
    CompactWorkflowInput,
    WorkflowResult,
)
from platform_workflows.queues import TaskQueue
from platform_workflows.retry import ActivityCategory, retry_policy


@dataclass(frozen=True, slots=True)
class Stage:
    """Static deterministic activity routing metadata."""

    name: str
    queue: TaskQueue
    category: ActivityCategory
    timeout: timedelta
    heartbeat_timeout: timedelta


async def _run_stages(command: CompactWorkflowInput, stages: tuple[Stage, ...]) -> WorkflowResult:
    """Execute static stages sequentially and pass only the last object key."""
    object_key = command.input_object_key
    for stage in stages:
        result = await workflow.execute_activity(
            stage.name,
            ActivityCommand(
                job_id=command.job_id,
                project_id=command.project_id,
                stage=stage.name,
                input_object_key=object_key,
            ),
            result_type=ActivityResult,
            task_queue=stage.queue.value,
            start_to_close_timeout=stage.timeout,
            heartbeat_timeout=stage.heartbeat_timeout,
            retry_policy=retry_policy(stage.category),
            cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            activity_id=f"{command.job_id}:{stage.name}",
        )
        object_key = result.output_object_key
    return WorkflowResult(job_id=command.job_id, status="completed", output_object_key=object_key)


def _control(name: str) -> Stage:
    return Stage(
        name,
        TaskQueue.CONTROL,
        ActivityCategory.CONTROL,
        timedelta(minutes=1),
        timedelta(seconds=20),
    )


_SCAN_STAGES = (
    _control("prepare-scan"),
    Stage(
        "crawl-scan",
        TaskQueue.CRAWL,
        ActivityCategory.NETWORK,
        timedelta(hours=1),
        timedelta(seconds=30),
    ),
    Stage(
        "render-scan-pages",
        TaskQueue.BROWSER,
        ActivityCategory.BROWSER,
        timedelta(minutes=30),
        timedelta(seconds=30),
    ),
    Stage(
        "analyze-scan",
        TaskQueue.AI_ANALYSIS,
        ActivityCategory.INFERENCE,
        timedelta(minutes=30),
        timedelta(seconds=30),
    ),
    Stage(
        "embed-scan",
        TaskQueue.EMBEDDING,
        ActivityCategory.STORAGE,
        timedelta(minutes=30),
        timedelta(seconds=30),
    ),
    _control("complete-scan"),
)
_DATASET_STAGES = (
    _control("prepare-dataset"),
    Stage(
        "build-dataset",
        TaskQueue.AI_ANALYSIS,
        ActivityCategory.STORAGE,
        timedelta(hours=1),
        timedelta(seconds=30),
    ),
    Stage(
        "embed-dataset",
        TaskQueue.EMBEDDING,
        ActivityCategory.STORAGE,
        timedelta(minutes=30),
        timedelta(seconds=30),
    ),
    _control("complete-dataset"),
)
_GENERATION_STAGES = (
    _control("prepare-generation"),
    Stage(
        "analyze-generation",
        TaskQueue.AI_ANALYSIS,
        ActivityCategory.INFERENCE,
        timedelta(minutes=30),
        timedelta(seconds=30),
    ),
    Stage(
        "generate-site-spec",
        TaskQueue.GENERATION,
        ActivityCategory.INFERENCE,
        timedelta(minutes=30),
        timedelta(seconds=30),
    ),
    Stage(
        "render-site",
        TaskQueue.RENDER,
        ActivityCategory.RENDER,
        timedelta(minutes=15),
        timedelta(seconds=30),
    ),
    Stage(
        "validate-site",
        TaskQueue.VALIDATION,
        ActivityCategory.VALIDATION,
        timedelta(minutes=30),
        timedelta(seconds=30),
    ),
    _control("complete-generation"),
)
_TRAINING_STAGES = (
    _control("prepare-training"),
    Stage(
        "run-training",
        TaskQueue.TRAINING,
        ActivityCategory.TRAINING,
        timedelta(hours=24),
        timedelta(seconds=30),
    ),
    Stage(
        "validate-training",
        TaskQueue.VALIDATION,
        ActivityCategory.VALIDATION,
        timedelta(hours=1),
        timedelta(seconds=30),
    ),
    _control("complete-training"),
)


@workflow.defn(name="ScanCampaignWorkflow")
class ScanCampaignWorkflow:
    """Skeleton for policy-aware crawl, browser, analysis, and embedding stages."""

    @workflow.run
    async def run(self, command: CompactWorkflowInput) -> WorkflowResult:
        return await _run_stages(command, _SCAN_STAGES)


@workflow.defn(name="DatasetBuildWorkflow")
class DatasetBuildWorkflow:
    """Skeleton for immutable dataset preparation and optional embeddings."""

    @workflow.run
    async def run(self, command: CompactWorkflowInput) -> WorkflowResult:
        return await _run_stages(command, _DATASET_STAGES)


@workflow.defn(name="SiteGenerationWorkflow")
class SiteGenerationWorkflow:
    """Skeleton for structured generation, deterministic render, and validation."""

    @workflow.run
    async def run(self, command: CompactWorkflowInput) -> WorkflowResult:
        return await _run_stages(command, _GENERATION_STAGES)


@workflow.defn(name="TrainingRunWorkflow")
class TrainingRunWorkflow:
    """Skeleton for explicitly authorized optional training and evaluation."""

    @workflow.run
    async def run(self, command: CompactWorkflowInput) -> WorkflowResult:
        return await _run_stages(command, _TRAINING_STAGES)


WORKFLOW_TYPES = (
    ScanCampaignWorkflow,
    DatasetBuildWorkflow,
    SiteGenerationWorkflow,
    TrainingRunWorkflow,
)
