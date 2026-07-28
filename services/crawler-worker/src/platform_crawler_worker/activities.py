"""Temporal crawl and deterministic post-processing activities."""

from uuid import UUID

from platform_api.database import DatabaseManager
from platform_api.persistence.models import ScanCampaign
from platform_workflows.commands import ActivityResult, CrawlTargetInput
from platform_workflows.heartbeat import ActivityHeartbeat
from temporalio import activity

from platform_crawler_worker.repository import CrawlRepository
from platform_crawler_worker.runner import CrawlerRunner


class CrawlActivities:
    def __init__(self, runner: CrawlerRunner, database: DatabaseManager | None = None) -> None:
        self._runner = runner
        self._database = database

    @activity.defn(name="crawl-scan-target")
    async def crawl_scan_target(self, command: CrawlTargetInput) -> ActivityResult:
        heartbeat = ActivityHeartbeat()

        async def progress(completed: int) -> None:
            heartbeat.report(stage="crawl-scan-target", completed=completed)

        await heartbeat.while_running(
            self._runner.crawl(command, progress), stage="crawl-scan-target"
        )
        return ActivityResult(record_id=command.scan_target_id)

    @activity.defn(name="fingerprint-scan-target")
    async def fingerprint_scan_target(self, command: CrawlTargetInput) -> ActivityResult:
        repository = self._repository()
        heartbeat = ActivityHeartbeat()
        heartbeat.report(stage="fingerprint-scan-target", completed=0)
        await repository.recalculate_deduplication(UUID(command.campaign_id))
        heartbeat.report(stage="fingerprint-scan-target", completed=1)
        return ActivityResult(record_id=command.scan_target_id)

    @activity.defn(name="classify-scan-target")
    async def classify_scan_target(self, command: CrawlTargetInput) -> ActivityResult:
        await self._classify_and_select(command, "classify-scan-target")
        return ActivityResult(record_id=command.scan_target_id)

    @activity.defn(name="select-scan-representatives")
    async def select_scan_representatives(self, command: CrawlTargetInput) -> ActivityResult:
        await self._classify_and_select(command, "select-scan-representatives")
        return ActivityResult(record_id=command.scan_target_id)

    async def _classify_and_select(self, command: CrawlTargetInput, stage: str) -> None:
        repository = self._repository()
        database = self._required_database()
        async with database.session() as session:
            campaign = await session.get(ScanCampaign, UUID(command.campaign_id))
        if campaign is None:
            raise LookupError("scan campaign was not found")
        heartbeat = ActivityHeartbeat()
        heartbeat.report(stage=stage, completed=0)
        await repository.recalculate_classification_and_selection(
            campaign.id,
            maximum_pages=campaign.max_visual_pages_per_domain,
            include_restricted=campaign.include_restricted_representatives,
        )
        heartbeat.report(stage=stage, completed=1)

    def _repository(self) -> CrawlRepository:
        return CrawlRepository(self._required_database())

    def _required_database(self) -> DatabaseManager:
        if self._database is None:
            raise RuntimeError("database is required for post-processing activities")
        return self._database
