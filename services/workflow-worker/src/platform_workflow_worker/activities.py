"""Restart-safe PostgreSQL control activities for scan orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar, cast
from uuid import UUID, uuid4

from platform_api.config import QdrantSettings
from platform_api.database import DatabaseManager
from platform_api.datasets.builder import BuildEvaluation, evaluate_dataset_build
from platform_api.datasets.repository import DatasetRepository
from platform_api.datasets.schemas import DatasetQualityPolicy, SelectionPolicy
from platform_api.persistence.json import JsonValue
from platform_api.persistence.models import (
    CrawlPage,
    Dataset,
    DatasetBuild,
    DatasetItem,
    DatasetQualityReport,
    DatasetVersion,
    EmbeddingRun,
    JobEvent,
    ScanCampaign,
    ScanFailure,
    ScanTarget,
    SectionPatternEmbedding,
)
from platform_workflows.commands import (
    ActivityResult,
    CompactWorkflowInput,
    DatasetBuildStageInput,
    DatasetBuildStageResult,
    ScanAggregationInput,
    ScanCampaignPlan,
    ScanIdentifierPage,
    ScanListInput,
    ScanProgressInput,
)
from platform_workflows.events import JobEvent as PublishedJobEvent
from platform_workflows.events import JobEventPublisher
from platform_workflows.heartbeat import ActivityHeartbeat
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio import activity
from temporalio.exceptions import ApplicationError


class ScanControlActivities:
    def __init__(
        self,
        database: DatabaseManager,
        qdrant: QdrantSettings,
        event_publisher: JobEventPublisher | None = None,
    ) -> None:
        self._database = database
        self._qdrant = qdrant
        self._event_publisher = event_publisher

    @activity.defn(name="validate-scan-campaign")
    async def validate(self, command: CompactWorkflowInput) -> ScanCampaignPlan:
        ActivityHeartbeat().report(stage="validate-scan-campaign", completed=0)
        campaign_id = UUID(command.job_id)
        async with self._database.transaction() as session:
            campaign = await session.get(ScanCampaign, campaign_id, with_for_update=True)
            if campaign is None or campaign.project_id != UUID(command.project_id):
                raise ApplicationError("campaign was not found", non_retryable=True)
            if not campaign.respect_robots_txt or campaign.authorization_attested_at is None:
                raise ApplicationError(
                    "campaign crawl policy is not authorized",
                    type="AuthorizationDenied",
                    non_retryable=True,
                )
            if campaign.status not in {"queued", "running", "pausing", "paused"}:
                raise ApplicationError("campaign state is not runnable", non_retryable=True)
            target = await session.scalar(
                select(ScanTarget.id).where(ScanTarget.campaign_id == campaign_id).limit(1)
            )
            if target is None:
                raise ApplicationError("campaign has no targets", non_retryable=True)
            campaign.status = "running"
            campaign.started_at = campaign.started_at or datetime.now(UTC)
            return ScanCampaignPlan(
                str(campaign.id),
                target_concurrency=campaign.overall_concurrency,
                browser_concurrency=min(campaign.overall_concurrency, 8),
                ai_concurrency=min(campaign.overall_concurrency, 4),
            )

    @activity.defn(name="list-scan-targets")
    async def targets(self, command: ScanListInput) -> ScanIdentifierPage:
        campaign_id = UUID(command.campaign_id)
        async with self._database.session() as session:
            campaign = await session.get(ScanCampaign, campaign_id)
            if campaign is None:
                raise ApplicationError("campaign was not found", non_retryable=True)
            statement = select(ScanTarget.id).where(ScanTarget.campaign_id == campaign_id)
            if command.failure_ids:
                statement = statement.join(
                    ScanFailure, ScanFailure.target_id == ScanTarget.id
                ).where(
                    ScanFailure.id.in_(tuple(UUID(value) for value in command.failure_ids)),
                    ScanFailure.retryable.is_(True),
                    ScanFailure.resolved_at.is_(None),
                )
            elif campaign.workflow_attempt > 1:
                statement = statement.join(
                    ScanFailure, ScanFailure.target_id == ScanTarget.id
                ).where(ScanFailure.retryable.is_(True), ScanFailure.resolved_at.is_(None))
            if command.cursor is not None:
                statement = statement.where(ScanTarget.id > UUID(command.cursor))
            identifiers = tuple(
                (
                    await session.scalars(
                        statement.distinct().order_by(ScanTarget.id).limit(command.limit + 1)
                    )
                ).all()
            )
        page = identifiers[: command.limit]
        return ScanIdentifierPage(
            tuple(str(value) for value in page),
            str(page[-1]) if len(identifiers) > command.limit and page else None,
        )

    @activity.defn(name="list-representative-pages")
    async def representatives(self, command: ScanListInput) -> ScanIdentifierPage:
        if command.target_id is None:
            raise ApplicationError("target ID is required", non_retryable=True)
        statement = select(CrawlPage.id).where(
            CrawlPage.campaign_id == UUID(command.campaign_id),
            CrawlPage.target_id == UUID(command.target_id),
            CrawlPage.status == "fetched",
            CrawlPage.representative_selected.is_(True),
        )
        if command.cursor is not None:
            statement = statement.where(CrawlPage.id > UUID(command.cursor))
        async with self._database.session() as session:
            identifiers = tuple(
                (
                    await session.scalars(statement.order_by(CrawlPage.id).limit(command.limit + 1))
                ).all()
            )
        page = identifiers[: command.limit]
        return ScanIdentifierPage(
            tuple(str(value) for value in page),
            str(page[-1]) if len(identifiers) > command.limit and page else None,
        )

    @activity.defn(name="persist-scan-progress")
    async def progress(self, command: ScanProgressInput) -> ActivityResult:
        campaign_id = UUID(command.campaign_id)
        async with self._database.transaction() as session:
            campaign = await session.get(ScanCampaign, campaign_id, with_for_update=True)
            if campaign is None:
                raise ApplicationError("campaign was not found", non_retryable=True)
            if command.status == "paused":
                campaign.status = "paused"
            elif campaign.status in {"queued", "pausing", "paused"}:
                campaign.status = "running"
            sequence = campaign.workflow_attempt * 1_000_000 + command.sequence
            existing = await session.scalar(
                select(JobEvent.id).where(
                    JobEvent.job_id == campaign_id, JobEvent.sequence == sequence
                )
            )
            if existing is None:
                session.add(
                    JobEvent(
                        job_id=campaign_id,
                        project_id=UUID(command.project_id),
                        sequence=sequence,
                        event_type=command.stage,
                        status="running" if command.status == "paused" else command.status,
                        payload={
                            "workflow_attempt": campaign.workflow_attempt,
                            "completed": command.completed,
                            "failed": command.failed,
                            "paused": command.status == "paused",
                        },
                    )
                )
        await self._publish_event(
            campaign_id=campaign_id,
            project_id=UUID(command.project_id),
            sequence=sequence,
            event_type=command.stage,
            status="running" if command.status == "paused" else command.status,
        )
        return ActivityResult(record_id=command.campaign_id)

    @activity.defn(name="prepare-scan-embedding")
    async def prepare_embedding(self, command: CompactWorkflowInput) -> ActivityResult:
        campaign_id = UUID(command.job_id)
        key = f"scan-{campaign_id}-attempt"
        async with self._database.transaction() as session:
            campaign = await session.get(ScanCampaign, campaign_id, with_for_update=True)
            if campaign is None:
                raise ApplicationError("campaign was not found", non_retryable=True)
            idempotency_key = f"{key}-{campaign.workflow_attempt}"
            run = await session.scalar(
                select(EmbeddingRun).where(
                    EmbeddingRun.project_id == campaign.project_id,
                    EmbeddingRun.idempotency_key == idempotency_key,
                )
            )
            if run is None:
                run = EmbeddingRun(
                    id=uuid4(),
                    project_id=campaign.project_id,
                    requested_by_user_id=UUID(command.requested_by_user_id),
                    kind="incremental",
                    status="queued",
                    idempotency_key=idempotency_key,
                    batch_size=64,
                    promote_alias=False,
                    collection_alias=self._qdrant.collection_alias,
                    serialization_schema_version=self._qdrant.serialization_schema_version,
                    vector_name=self._qdrant.vector_name,
                    total_patterns=0,
                    processed_patterns=0,
                    indexed_patterns=0,
                    deleted_patterns=0,
                    failed_patterns=0,
                )
                session.add(run)
                await session.flush()
            return ActivityResult(record_id=str(run.id))

    @activity.defn(name="aggregate-scan-campaign")
    async def aggregate(self, command: ScanAggregationInput) -> ActivityResult:
        campaign_id = UUID(command.campaign_id)
        async with self._database.transaction() as session:
            campaign = await session.get(ScanCampaign, campaign_id, with_for_update=True)
            if campaign is None:
                raise ApplicationError("campaign was not found", non_retryable=True)
            if command.cancelled:
                status = "cancelled"
            elif command.failed_targets and command.succeeded_targets:
                status = "partially_succeeded"
            elif command.failed_targets:
                status = "failed"
            else:
                status = "succeeded"
            campaign.status = status
            campaign.completed_at = datetime.now(UTC)
            sequence = campaign.workflow_attempt * 1_000_000 + 999_999
            existing = await session.scalar(
                select(JobEvent.id).where(
                    JobEvent.job_id == campaign_id, JobEvent.sequence == sequence
                )
            )
            if existing is None:
                session.add(
                    JobEvent(
                        job_id=campaign_id,
                        project_id=UUID(command.project_id),
                        sequence=sequence,
                        event_type="campaign.complete",
                        status=(
                            "cancelled"
                            if status == "cancelled"
                            else "failed"
                            if status == "failed"
                            else "succeeded"
                        ),
                        payload={
                            "campaign_status": status,
                            "succeeded_targets": command.succeeded_targets,
                            "failed_targets": command.failed_targets,
                        },
                    )
                )
        await self._publish_event(
            campaign_id=campaign_id,
            project_id=UUID(command.project_id),
            sequence=sequence,
            event_type="campaign.complete",
            status=(
                "cancelled"
                if status == "cancelled"
                else "failed"
                if status == "failed"
                else "succeeded"
            ),
        )
        return ActivityResult(record_id=command.campaign_id)

    async def _publish_event(
        self,
        *,
        campaign_id: UUID,
        project_id: UUID,
        sequence: int,
        event_type: str,
        status: str,
    ) -> None:
        """Wake subscribers only after the durable transaction has committed."""
        if self._event_publisher is None:
            return
        await self._event_publisher.publish(
            PublishedJobEvent.create(
                job_id=str(campaign_id),
                project_id=str(project_id),
                job_type="scan_campaign",
                sequence=sequence,
                event_type=event_type,
                status=status,
            )
        )

    def registered(self) -> tuple[Callable[..., Any], ...]:
        return (
            self.validate,
            self.targets,
            self.representatives,
            self.progress,
            self.prepare_embedding,
            self.aggregate,
        )


class DatasetBuildActivities:
    """Idempotent PostgreSQL activities for governed dataset construction."""

    _PASS_THROUGH_STAGES: ClassVar[set[str]] = {
        "validate-selection-policy",
        "resolve-candidate-patterns",
        "exclude-ineligible-patterns",
        "deduplicate-pattern-hashes",
        "check-provenance-authorization",
        "check-source-specific-copy",
        "compute-distributions",
        "create-domain-disjoint-splits",
    }

    def __init__(self, database: DatabaseManager, qdrant: QdrantSettings) -> None:
        self._database = database
        self._qdrant = qdrant

    @activity.defn(name="run-dataset-build-stage")
    async def run_stage(self, command: DatasetBuildStageInput) -> DatasetBuildStageResult:
        heartbeat = ActivityHeartbeat()
        heartbeat.report(stage=command.stage, completed=0)
        build_id = UUID(command.build_id)
        async with self._database.transaction() as session:
            build = await session.scalar(
                select(DatasetBuild).where(DatasetBuild.id == build_id).with_for_update()
            )
            if build is None or build.project_id != UUID(command.project_id):
                raise ApplicationError("dataset build was not found", non_retryable=True)
            if build.status == "succeeded":
                return DatasetBuildStageResult(command.build_id, "sealed")
            if (
                build.status in {"cancelled", "cancelling"}
                or command.stage == "cancel-dataset-build"
            ):
                build.status = "cancelled"
                build.stage = "cancelled"
                build.cancelled_at = datetime.now(UTC)
                build.completed_at = build.cancelled_at
                return DatasetBuildStageResult(command.build_id, "cancelled")
            if build.status == "failed":
                return DatasetBuildStageResult(command.build_id, "failed")
            if command.stage == "fail-dataset-build":
                build.status = "failed"
                build.stage = "failed"
                build.failure_code = "dataset_stage_failed"
                build.completed_at = datetime.now(UTC)
                return DatasetBuildStageResult(command.build_id, "failed")

            version = await session.get(DatasetVersion, build.dataset_version_id)
            dataset = await session.get(Dataset, build.dataset_id)
            if (
                version is None
                or dataset is None
                or version.dataset_id != build.dataset_id
                or dataset.project_id != build.project_id
            ):
                raise ApplicationError("dataset version was not found", non_retryable=True)
            if version.status != "draft" or dataset.status != "active":
                build.status = "failed"
                build.failure_code = "dataset_version_not_draft"
                build.completed_at = datetime.now(UTC)
                return DatasetBuildStageResult(command.build_id, "failed")

            build.status = "running"
            build.stage = command.stage
            build.started_at = build.started_at or datetime.now(UTC)
            selection = SelectionPolicy.model_validate(version.selection_config)
            quality = DatasetQualityPolicy.model_validate(build.quality_policy)
            if command.stage in self._PASS_THROUGH_STAGES:
                return DatasetBuildStageResult(command.build_id, "running")
            if command.stage == "produce-quality-report":
                evaluation = await self._evaluate(session, build, version, selection, quality)
                report = await session.scalar(
                    select(DatasetQualityReport).where(
                        DatasetQualityReport.dataset_build_id == build.id
                    )
                )
                if report is None:
                    report = DatasetQualityReport(
                        dataset_version_id=version.id,
                        dataset_build_id=build.id,
                        status="passed" if evaluation.passed else "failed",
                        item_count=len(evaluation.items),
                        statistics=evaluation.statistics,
                        findings=list(evaluation.findings),
                        report_version=2,
                    )
                    session.add(report)
                build.excluded_counts = evaluation.excluded_counts
                if not evaluation.passed:
                    build.status = "failed"
                    build.failure_code = "dataset_quality_checks_failed"
                    build.completed_at = datetime.now(UTC)
                    return DatasetBuildStageResult(command.build_id, "failed")
                return DatasetBuildStageResult(command.build_id, "passed")
            if command.stage == "materialize-version-manifest":
                evaluation = await self._evaluate(session, build, version, selection, quality)
                if not evaluation.passed:
                    build.status = "failed"
                    build.failure_code = "dataset_quality_checks_failed"
                    build.completed_at = datetime.now(UTC)
                    return DatasetBuildStageResult(command.build_id, "failed")
                await session.execute(
                    delete(DatasetItem).where(DatasetItem.dataset_version_id == version.id)
                )
                session.add_all(list(evaluation.items))
                version.selection_manifest = evaluation.manifest
                version.manifest_sha256 = evaluation.manifest_sha256
                version.analyzer_versions = cast(JsonValue, list(evaluation.analyzer_versions))
                version.statistics = evaluation.statistics
                return DatasetBuildStageResult(command.build_id, "passed")
            if command.stage == "enqueue-missing-embeddings":
                run_id = await self._enqueue_embeddings(session, build, version)
                return DatasetBuildStageResult(
                    command.build_id,
                    "passed",
                    None if run_id is None else str(run_id),
                )
            if command.stage == "seal-dataset-version":
                report = await session.scalar(
                    select(DatasetQualityReport).where(
                        DatasetQualityReport.dataset_build_id == build.id,
                        DatasetQualityReport.status == "passed",
                    )
                )
                evaluation = await self._evaluate(session, build, version, selection, quality)
                if (
                    report is None
                    or not evaluation.passed
                    or version.manifest_sha256 is None
                    or version.manifest_sha256 != evaluation.manifest_sha256
                ):
                    build.status = "failed"
                    build.failure_code = "dataset_required_checks_changed"
                    build.completed_at = datetime.now(UTC)
                    return DatasetBuildStageResult(command.build_id, "failed")
                now = datetime.now(UTC)
                version.status = "sealed"
                version.sealed_by_user_id = build.requested_by_user_id
                version.sealed_at = now
                build.status = "succeeded"
                build.stage = "sealed"
                build.completed_at = now
                build.failure_code = None
                return DatasetBuildStageResult(command.build_id, "sealed")
            raise ApplicationError("unknown dataset build stage", non_retryable=True)

    async def _evaluate(
        self,
        session: AsyncSession,
        build: DatasetBuild,
        version: DatasetVersion,
        selection: SelectionPolicy,
        quality: DatasetQualityPolicy,
    ) -> BuildEvaluation:
        candidates = await DatasetRepository(session).build_candidates(build.project_id, selection)
        return evaluate_dataset_build(
            version_id=version.id,
            candidates=candidates,
            selection=selection,
            quality=quality,
            schema_version=version.schema_version,
            now=datetime.now(UTC),
        )

    async def _enqueue_embeddings(
        self, session: AsyncSession, build: DatasetBuild, version: DatasetVersion
    ) -> UUID | None:
        if not build.enqueue_missing_embeddings:
            return None
        pattern_ids = tuple(
            (
                await session.scalars(
                    select(DatasetItem.source_record_id).where(
                        DatasetItem.dataset_version_id == version.id,
                        DatasetItem.item_type == "section_pattern",
                    )
                )
            ).all()
        )
        if not pattern_ids:
            return None
        indexed_ids = set(
            (
                await session.scalars(
                    select(SectionPatternEmbedding.section_pattern_id).where(
                        SectionPatternEmbedding.section_pattern_id.in_(pattern_ids),
                        SectionPatternEmbedding.status == "indexed",
                    )
                )
            ).all()
        )
        if all(pattern_id in indexed_ids for pattern_id in pattern_ids):
            return None
        key = f"dataset-{version.id}-attempt-{build.workflow_attempt}"
        existing = await session.scalar(
            select(EmbeddingRun).where(
                EmbeddingRun.project_id == build.project_id,
                EmbeddingRun.idempotency_key == key,
            )
        )
        if existing is not None:
            return existing.id
        run = EmbeddingRun(
            id=uuid4(),
            project_id=build.project_id,
            requested_by_user_id=build.requested_by_user_id,
            dataset_id=build.dataset_id,
            dataset_version_id=version.id,
            kind="incremental",
            status="queued",
            idempotency_key=key,
            batch_size=64,
            promote_alias=False,
            collection_alias=self._qdrant.collection_alias,
            serialization_schema_version=self._qdrant.serialization_schema_version,
            vector_name=self._qdrant.vector_name,
            total_patterns=0,
            processed_patterns=0,
            indexed_patterns=0,
            deleted_patterns=0,
            failed_patterns=0,
        )
        session.add(run)
        return run.id

    def registered(self) -> tuple[Callable[..., Any], ...]:
        return (self.run_stage,)
