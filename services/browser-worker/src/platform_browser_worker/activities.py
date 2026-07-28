"""Temporal browser activity with compact input, heartbeat, and cancellation."""

from platform_workflows.commands import ActivityResult, RenderPageInput
from platform_workflows.heartbeat import ActivityHeartbeat
from temporalio import activity

from platform_browser_worker.runner import BrowserScanRunner


class BrowserActivities:
    def __init__(self, runner: BrowserScanRunner) -> None:
        self._runner = runner

    @activity.defn(name="render-representative-page")
    async def render_representative_page(self, command: RenderPageInput) -> ActivityResult:
        heartbeat = ActivityHeartbeat()

        async def progress(stage: str, completed: int) -> None:
            heartbeat.report(stage=stage, completed=completed)

        await heartbeat.while_running(
            self._runner.scan(command, progress), stage="render-representative-page"
        )
        return ActivityResult(record_id=command.crawl_page_id)
