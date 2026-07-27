"""Temporal activities delegating all Twisted work to isolated subprocesses."""

from platform_workflows.commands import ActivityResult, CrawlTargetInput
from platform_workflows.heartbeat import ActivityHeartbeat
from temporalio import activity

from platform_crawler_worker.runner import CrawlerRunner


class CrawlActivities:
    def __init__(self, runner: CrawlerRunner) -> None:
        self._runner = runner

    @activity.defn(name="crawl-scan-target")
    async def crawl_scan_target(self, command: CrawlTargetInput) -> ActivityResult:
        heartbeat = ActivityHeartbeat()

        async def progress(completed: int) -> None:
            heartbeat.report(stage="crawl-scan-target", completed=completed)

        await heartbeat.while_running(
            self._runner.crawl(command, progress), stage="crawl-scan-target"
        )
        return ActivityResult(record_id=command.scan_target_id)
