"""Restart-safe PostgreSQL control activities for scan orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from platform_api.config import QdrantSettings
from platform_api.database import DatabaseManager
from platform_api.persistence.models import (
    CrawlPage,
    EmbeddingRun,
    JobEvent,
    ScanCampaign,
    ScanFailure,
    ScanTarget,
)
from platform_workflows.commands import (
    ActivityResult,
    CompactWorkflowInput,
    ScanAggregationInput,
    ScanCampaignPlan,
    ScanIdentifierPage,
    ScanListInput,
    ScanProgressInput,
)
from platform_workflows.heartbeat import ActivityHeartbeat
from sqlalchemy import select
from temporalio import activity
from temporalio.exceptions import ApplicationError


class ScanControlActivities:
    def __init__(self, database: DatabaseManager, qdrant: QdrantSettings) -> None:
        self._database = database
        self._qdrant = qdrant

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
        return ActivityResult(record_id=command.campaign_id)

    def registered(self) -> tuple[Callable[..., Any], ...]:
        return (
            self.validate,
            self.targets,
            self.representatives,
            self.progress,
            self.prepare_embedding,
            self.aggregate,
        )
