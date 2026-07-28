"""Deterministic durable orchestration with identifier-only history payloads."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError
from temporalio.workflow import ActivityCancellationType

from platform_workflows.commands import (
    ActivityCommand,
    ActivityResult,
    CompactWorkflowInput,
    CrawlTargetInput,
    EmbeddingIndexInput,
    ModelWarmupInput,
    RenderPageInput,
    ScanAggregationInput,
    ScanCampaignPlan,
    ScanIdentifierPage,
    ScanListInput,
    ScanPageInput,
    ScanProgressInput,
    ScanTargetResult,
    ScanTargetWorkflowInput,
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
    """Page targets and durably coordinate bounded child workflows."""

    def __init__(self) -> None:
        self._paused = False
        self._cancel_requested = False
        self._running = False

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
        if self._paused:
            return "paused"
        return "running" if self._running else "queued"

    @workflow.run
    async def run(self, command: CompactWorkflowInput) -> WorkflowResult:
        plan = await workflow.execute_activity(
            "validate-scan-campaign",
            command,
            result_type=ScanCampaignPlan,
            task_queue=TaskQueue.CONTROL.value,
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=timedelta(seconds=20),
            retry_policy=retry_policy(ActivityCategory.CONTROL),
        )
        self._running = True
        await self._progress(command, "campaign.validate", "running", 1)
        cursor: str | None = None
        succeeded = failed = sequence = 0
        while not self._cancel_requested:
            await self._pause_checkpoint(command, sequence + 2)
            page = await workflow.execute_activity(
                "list-scan-targets",
                ScanListInput(
                    command.job_id,
                    cursor=cursor,
                    limit=plan.page_size,
                    failure_ids=command.resource_ids,
                ),
                result_type=ScanIdentifierPage,
                task_queue=TaskQueue.CONTROL.value,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy(ActivityCategory.CONTROL),
            )
            for offset in range(0, len(page.identifiers), plan.target_concurrency):
                batch = page.identifiers[offset : offset + plan.target_concurrency]
                child_tasks = [
                    asyncio.create_task(
                        workflow.execute_child_workflow(
                            ScanTargetWorkflow.run,
                            ScanTargetWorkflowInput(
                                command.job_id,
                                command.project_id,
                                target_id,
                                plan.browser_concurrency,
                                plan.ai_concurrency,
                            ),
                            id=f"{workflow.info().workflow_id}:target:{target_id}",
                            task_queue=TaskQueue.CONTROL.value,
                        )
                    )
                    for target_id in batch
                ]
                batch_task = asyncio.gather(*child_tasks, return_exceptions=True)
                cancel_task = asyncio.create_task(
                    workflow.wait_condition(lambda: self._cancel_requested)
                )
                done, _ = await asyncio.wait(
                    (batch_task, cancel_task), return_when=asyncio.FIRST_COMPLETED
                )
                if cancel_task in done:
                    for child_task in child_tasks:
                        child_task.cancel()
                    results = await batch_task
                else:
                    cancel_task.cancel()
                    await asyncio.gather(cancel_task, return_exceptions=True)
                    results = await batch_task
                for result in results:
                    if isinstance(result, ScanTargetResult):
                        if result.status in {"succeeded", "partially_succeeded"}:
                            succeeded += 1
                        if result.status != "succeeded":
                            failed += 1
                    else:
                        failed += 1
                sequence += 1
                await self._progress(
                    command,
                    "campaign.targets",
                    "running",
                    sequence + 1,
                    completed=succeeded,
                    failed=failed,
                )
                await self._pause_checkpoint(command, sequence + 2)
            cursor = page.next_cursor
            if cursor is None:
                break

        if self._cancel_requested:
            await self._aggregate(command, succeeded, failed, cancelled=True)
            return WorkflowResult(job_id=command.job_id, status="cancelled")

        embedding = await workflow.execute_activity(
            "prepare-scan-embedding",
            command,
            result_type=ActivityResult,
            task_queue=TaskQueue.CONTROL.value,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry_policy(ActivityCategory.CONTROL),
        )
        try:
            await workflow.execute_activity(
                "index-section-patterns",
                EmbeddingIndexInput(embedding.record_id),
                result_type=ActivityResult,
                task_queue=TaskQueue.EMBEDDING.value,
                start_to_close_timeout=timedelta(hours=4),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=retry_policy(ActivityCategory.INFERENCE),
                cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
        except ActivityError:
            failed += 1
        await self._aggregate(command, succeeded, failed)
        return WorkflowResult(
            job_id=command.job_id,
            status="partially_completed" if failed else "completed",
        )

    async def _pause_checkpoint(self, command: CompactWorkflowInput, sequence: int) -> None:
        if not self._paused:
            return
        await self._progress(command, "campaign.paused", "paused", sequence)
        await workflow.wait_condition(lambda: not self._paused or self._cancel_requested)
        if not self._cancel_requested:
            await self._progress(command, "campaign.resumed", "running", sequence + 1)

    @staticmethod
    async def _progress(
        command: CompactWorkflowInput,
        stage: str,
        status: str,
        sequence: int,
        *,
        completed: int = 0,
        failed: int = 0,
    ) -> None:
        await workflow.execute_activity(
            "persist-scan-progress",
            ScanProgressInput(
                command.job_id,
                command.project_id,
                stage,
                status,
                sequence,
                completed=completed,
                failed=failed,
            ),
            result_type=ActivityResult,
            task_queue=TaskQueue.CONTROL.value,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=retry_policy(ActivityCategory.CONTROL),
        )

    @staticmethod
    async def _aggregate(
        command: CompactWorkflowInput, succeeded: int, failed: int, *, cancelled: bool = False
    ) -> None:
        await workflow.execute_activity(
            "aggregate-scan-campaign",
            ScanAggregationInput(command.job_id, command.project_id, succeeded, failed, cancelled),
            result_type=ActivityResult,
            task_queue=TaskQueue.CONTROL.value,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry_policy(ActivityCategory.CONTROL),
        )


@workflow.defn(name="ScanTargetWorkflow")
class ScanTargetWorkflow:
    """Restart-safe target pipeline; artifacts never enter workflow history."""

    @workflow.run
    async def run(self, command: ScanTargetWorkflowInput) -> ScanTargetResult:
        for name, category in (
            ("crawl-scan-target", ActivityCategory.NETWORK),
            ("fingerprint-scan-target", ActivityCategory.STORAGE),
            ("classify-scan-target", ActivityCategory.CONTROL),
            ("select-scan-representatives", ActivityCategory.CONTROL),
        ):
            try:
                await self._target_activity(name, command, category)
            except ActivityError:
                return ScanTargetResult(command.target_id, "failed", failed_pages=1)

        cursor: str | None = None
        rendered = analyzed = failed = 0
        while True:
            pages = await workflow.execute_activity(
                "list-representative-pages",
                ScanListInput(
                    command.campaign_id,
                    cursor=cursor,
                    limit=100,
                    target_id=command.target_id,
                ),
                result_type=ScanIdentifierPage,
                task_queue=TaskQueue.CONTROL.value,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy(ActivityCategory.CONTROL),
            )
            for offset in range(0, len(pages.identifiers), command.browser_concurrency):
                batch = pages.identifiers[offset : offset + command.browser_concurrency]
                render_results = await asyncio.gather(
                    *(self._render(command.campaign_id, page_id) for page_id in batch),
                    return_exceptions=True,
                )
                ready = [
                    page_id
                    for page_id, result in zip(batch, render_results, strict=True)
                    if result is True
                ]
                rendered += len(ready)
                failed += len(batch) - len(ready)
                for ai_offset in range(0, len(ready), command.ai_concurrency):
                    ai_batch = ready[ai_offset : ai_offset + command.ai_concurrency]
                    results = await asyncio.gather(
                        *(self._analyze(command.campaign_id, page_id) for page_id in ai_batch),
                        return_exceptions=True,
                    )
                    analyzed += sum(result is True for result in results)
                    failed += sum(result is not True for result in results)
            cursor = pages.next_cursor
            if cursor is None:
                break
        return ScanTargetResult(
            command.target_id,
            "succeeded" if failed == 0 else "partially_succeeded",
            rendered,
            analyzed,
            failed,
        )

    @staticmethod
    async def _target_activity(
        name: str, command: ScanTargetWorkflowInput, category: ActivityCategory
    ) -> None:
        await workflow.execute_activity(
            name,
            CrawlTargetInput(command.campaign_id, command.target_id),
            result_type=ActivityResult,
            task_queue=TaskQueue.CRAWL.value,
            start_to_close_timeout=timedelta(hours=2),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=retry_policy(category),
            cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            activity_id=f"{command.target_id}:{name}",
        )

    @staticmethod
    async def _render(campaign_id: str, page_id: str) -> bool:
        try:
            await workflow.execute_activity(
                "render-representative-page",
                RenderPageInput(campaign_id, page_id),
                result_type=ActivityResult,
                task_queue=TaskQueue.BROWSER.value,
                start_to_close_timeout=timedelta(minutes=15),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=retry_policy(ActivityCategory.BROWSER),
                cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                activity_id=f"{page_id}:browser",
            )
            return True
        except ActivityError:
            return False

    @staticmethod
    async def _analyze(campaign_id: str, page_id: str) -> bool:
        try:
            await workflow.execute_activity(
                "analyze-and-persist-page-profile",
                ScanPageInput(campaign_id, page_id),
                result_type=ActivityResult,
                task_queue=TaskQueue.AI_ANALYSIS.value,
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=retry_policy(ActivityCategory.INFERENCE),
                cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                activity_id=f"{page_id}:analysis",
            )
            return True
        except ActivityError:
            return False


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
    ScanTargetWorkflow,
    DatasetBuildWorkflow,
    SiteGenerationWorkflow,
    TrainingRunWorkflow,
    ModelWarmupWorkflow,
    ArtifactDeletionWorkflow,
    EmbeddingIndexWorkflow,
)
