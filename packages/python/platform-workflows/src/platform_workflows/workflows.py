"""Deterministic orchestration skeletons with no external calls."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.workflow import ActivityCancellationType

from platform_workflows.commands import (
    ActivityCommand,
    ActivityResult,
    CompactWorkflowInput,
    EmbeddingIndexInput,
    ModelWarmupInput,
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
    """Control-only scan skeleton; no crawl activity exists in this prompt."""

    def __init__(self) -> None:
        self._paused = False
        self._cancel_requested = False

    @workflow.signal(name="pause")
    async def pause(self) -> None:
        self._paused = True

    @workflow.signal(name="resume")
    async def resume(self) -> None:
        self._paused = False

    @workflow.signal(name="cancel")
    async def cancel(self) -> None:
        self._cancel_requested = True

    @workflow.query(name="control-state")
    def control_state(self) -> str:
        if self._cancel_requested:
            return "cancelling"
        return "paused" if self._paused else "queued"

    @workflow.run
    async def run(self, command: CompactWorkflowInput) -> WorkflowResult:
        await workflow.wait_condition(lambda: self._cancel_requested)
        return WorkflowResult(job_id=command.job_id, status="cancelled")


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


@workflow.defn(name="ModelWarmupWorkflow")
class ModelWarmupWorkflow:
    """Dispatch model loading to the AI worker without inference in FastAPI."""

    @workflow.run
    async def run(self, command: ModelWarmupInput) -> WorkflowResult:
        await workflow.execute_activity(
            "warm-up-model",
            command,
            result_type=ActivityResult,
            task_queue=TaskQueue.AI_ANALYSIS.value,
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=retry_policy(ActivityCategory.INFERENCE),
            cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            activity_id=f"{command.job_id}:warm-up-model:{command.model_role.value}",
        )
        return WorkflowResult(job_id=command.job_id, status="completed")


@workflow.defn(name="ArtifactDeletionWorkflow")
class ArtifactDeletionWorkflow:
    """Acknowledge removal intent until policy-aware deletion activities are implemented."""

    @workflow.run
    async def run(self, command: CompactWorkflowInput) -> WorkflowResult:
        return WorkflowResult(
            job_id=command.job_id,
            status="completed",
            output_object_key=command.input_object_key,
        )


@workflow.defn(name="EmbeddingIndexWorkflow")
class EmbeddingIndexWorkflow:
    """Run heavy embedding and Qdrant mutation only on the embedding queue."""

    @workflow.run
    async def run(self, command: EmbeddingIndexInput) -> WorkflowResult:
        await workflow.execute_activity(
            "index-section-patterns",
            command,
            result_type=ActivityResult,
            task_queue=TaskQueue.EMBEDDING.value,
            start_to_close_timeout=timedelta(hours=4),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=retry_policy(ActivityCategory.INFERENCE),
            cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            activity_id=f"{command.embedding_run_id}:index-section-patterns",
        )
        return WorkflowResult(job_id=command.embedding_run_id, status="completed")


WORKFLOW_TYPES = (
    ScanCampaignWorkflow,
    DatasetBuildWorkflow,
    SiteGenerationWorkflow,
    TrainingRunWorkflow,
    ModelWarmupWorkflow,
    ArtifactDeletionWorkflow,
    EmbeddingIndexWorkflow,
)
