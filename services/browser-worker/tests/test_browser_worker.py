"""Offline browser activity, idempotency, failure, and cancellation tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from platform_browser_worker.activities import BrowserActivities
from platform_browser_worker.models import (
    BrowserCapture,
    BrowserCaptureLimits,
    BrowserFailureCode,
    BrowserScanConfiguration,
    BrowserScanError,
    BrowserViewport,
    DocumentDimensions,
    PreparedPageScan,
    ViewportName,
)
from platform_browser_worker.renderer import PlaywrightBrowserRenderer
from platform_browser_worker.runner import BrowserScanRunner, FakeBrowserRenderer
from platform_clients.network_safety import (
    NetworkSafetySubsystem,
    PlaywrightRequestSafety,
)
from platform_clients.network_safety.resolver import SequenceDnsResolver
from platform_workflows.commands import RenderPageInput
from temporalio.testing import ActivityEnvironment

pytestmark = pytest.mark.anyio


def configuration() -> BrowserScanConfiguration:
    return BrowserScanConfiguration(
        campaign_id=uuid4(),
        project_id=uuid4(),
        target_id=uuid4(),
        crawl_page_id=uuid4(),
        url="https://fixture.example/",
        source_content_sha256="a" * 64,
        retention_days=30,
        viewports=(
            BrowserViewport(ViewportName.DESKTOP, 1440, 1000, False),
            BrowserViewport(ViewportName.MOBILE, 390, 844, True),
        ),
        limits=BrowserCaptureLimits(),
    )


def capture(viewport: str) -> BrowserCapture:
    return BrowserCapture(
        final_url="https://fixture.example/",
        rendered_html=f"<html><title>{viewport}</title></html>",
        full_page_screenshot=b"full-" + viewport.encode(),
        viewport_screenshot=b"viewport-" + viewport.encode(),
        response_metadata={"status": 200, "content_type": "text/html"},
        title="Northstar Studio Fixture",
        meta_description=None,
        canonical_url="https://fixture.example/",
        language="en",
        visible_text_summary="Synthetic fixture content.",
        console_errors=(),
        page_errors=(),
        failed_requests=(),
        external_hosts=(),
        dimensions=DocumentDimensions(1440, 1200, 1440, 1200, False),
        browser_version="fixture-browser/1",
    )


class FakeRepository:
    def __init__(self, config: BrowserScanConfiguration) -> None:
        self.configuration = config
        self.prepared: dict[str, PreparedPageScan] = {}
        self.completed: list[str] = []
        self.failures: list[BrowserScanError] = []
        self.cancelled: list[str] = []

    async def load_configuration(
        self, campaign_id: UUID, crawl_page_id: UUID
    ) -> BrowserScanConfiguration:
        assert campaign_id == self.configuration.campaign_id
        assert crawl_page_id == self.configuration.crawl_page_id
        return self.configuration

    async def prepare(
        self, config: BrowserScanConfiguration, viewport: BrowserViewport
    ) -> PreparedPageScan:
        existing = self.prepared.get(viewport.name.value)
        if existing is not None and viewport.name.value in self.completed:
            return PreparedPageScan(
                existing.id, viewport, existing.configuration_hash, already_succeeded=True
            )
        prepared = existing or PreparedPageScan(
            uuid4(), viewport, config.configuration_hash(viewport), already_succeeded=False
        )
        self.prepared[viewport.name.value] = prepared
        return prepared

    async def complete(
        self,
        config: BrowserScanConfiguration,
        prepared: PreparedPageScan,
        result: BrowserCapture,
    ) -> None:
        del config, result
        self.completed.append(prepared.viewport.name.value)

    async def fail(
        self,
        config: BrowserScanConfiguration,
        prepared: PreparedPageScan | None,
        error: BrowserScanError,
    ) -> None:
        del config, prepared
        self.failures.append(error)

    async def cancel(
        self, config: BrowserScanConfiguration, prepared: PreparedPageScan | None
    ) -> None:
        del config
        if prepared is not None:
            self.cancelled.append(prepared.viewport.name.value)


async def test_activity_captures_both_viewports_and_heartbeats_without_payloads() -> None:
    config = configuration()
    repository = FakeRepository(config)
    renderer = FakeBrowserRenderer({"desktop": capture("desktop"), "mobile": capture("mobile")})
    environment = ActivityEnvironment()
    heartbeats: list[tuple[object, ...]] = []
    environment.on_heartbeat = lambda *details: heartbeats.append(details)
    command = RenderPageInput(str(config.campaign_id), str(config.crawl_page_id))

    result = await environment.run(
        BrowserActivities(BrowserScanRunner(repository, renderer)).render_representative_page,
        command,
    )

    assert result.record_id == str(config.crawl_page_id)
    assert repository.completed == ["desktop", "mobile"]
    assert [viewport for _, viewport in renderer.calls] == ["desktop", "mobile"]
    assert heartbeats[-1] == ({"stage": "complete-mobile", "completed": 2},)
    assert all("html" not in str(details).casefold() for details in heartbeats)


async def test_configuration_hash_and_successful_retries_are_deterministic() -> None:
    config = configuration()
    desktop, mobile = config.viewports
    assert config.configuration_hash(desktop) == config.configuration_hash(desktop)
    assert config.configuration_hash(desktop) != config.configuration_hash(mobile)
    repository = FakeRepository(config)
    renderer = FakeBrowserRenderer({"desktop": capture("desktop"), "mobile": capture("mobile")})
    runner = BrowserScanRunner(repository, renderer)
    command = RenderPageInput(str(config.campaign_id), str(config.crawl_page_id))
    await runner.scan(command)
    await runner.scan(command)
    assert len(renderer.calls) == 2
    assert repository.completed == ["desktop", "mobile"]


async def test_typed_renderer_failure_is_persisted() -> None:
    config = configuration()
    error = BrowserScanError(
        BrowserFailureCode.NAVIGATION_BLOCKED,
        "Browser navigation was blocked by outbound policy.",
    )
    repository = FakeRepository(config)
    renderer = FakeBrowserRenderer({}, error=error)
    with pytest.raises(BrowserScanError) as caught:
        await BrowserScanRunner(repository, renderer).scan(
            RenderPageInput(str(config.campaign_id), str(config.crawl_page_id))
        )
    assert caught.value.code is BrowserFailureCode.NAVIGATION_BLOCKED
    assert repository.failures == [error]


async def test_cancellation_marks_the_in_progress_viewport() -> None:
    config = configuration()
    repository = FakeRepository(config)

    class BlockingRenderer:
        async def capture(
            self,
            config: BrowserScanConfiguration,
            viewport: BrowserViewport,
            *,
            request_id: str,
            progress: Callable[[str], Awaitable[None]] | None = None,
        ) -> BrowserCapture:
            del config, viewport, request_id, progress
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def close(self) -> None:
            return None

    task = asyncio.create_task(
        BrowserScanRunner(repository, BlockingRenderer()).scan(
            RenderPageInput(str(config.campaign_id), str(config.crawl_page_id))
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert repository.cancelled == ["desktop"]


async def test_playwright_route_blocks_private_subresources_before_connection() -> None:
    class FakeRoute:
        aborted = False
        continued = False

        async def abort(self, error_code: str) -> None:
            assert error_code == "blockedbyclient"
            self.aborted = True

        async def continue_(self) -> None:
            self.continued = True

    class FakeFrame:
        url = "https://fixture.example/"
        parent_frame = object()

    class FakeRequest:
        url = "http://127.0.0.1/internal.css"
        resource_type = "stylesheet"
        redirected_from = None
        frame = FakeFrame()

        @staticmethod
        def is_navigation_request() -> bool:
            return False

    class FakeEvents:
        primary_blocked = None

    route = FakeRoute()
    renderer = PlaywrightBrowserRenderer(
        PlaywrightRequestSafety(NetworkSafetySubsystem(SequenceDnsResolver({})))
    )
    await renderer._route(
        route,  # type: ignore[arg-type]
        FakeRequest(),  # type: ignore[arg-type]
        renderer._request_safety.context(),
        {},
        FakeEvents(),  # type: ignore[arg-type]
        set(),
    )
    assert route.aborted
    assert not route.continued
