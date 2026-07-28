"""Offline browser activity, idempotency, failure, and cancellation tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from platform_browser_worker.activities import BrowserActivities
from platform_browser_worker.extractor import validate_semantic_snapshot
from platform_browser_worker.models import (
    EXTRACTOR_VERSION,
    BrowserCapture,
    BrowserCaptureLimits,
    BrowserFailureCode,
    BrowserScanConfiguration,
    BrowserScanError,
    BrowserViewport,
    DocumentDimensions,
    PreparedPageScan,
    SemanticSnapshot,
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
        semantic_snapshot=semantic_snapshot(),
    )


def semantic_snapshot(*, tag_counts: dict[str, int] | None = None) -> SemanticSnapshot:
    return SemanticSnapshot.model_validate(
        {
            "extractor_version": EXTRACTOR_VERSION,
            "nodes": [
                {
                    "id": "n-1234abcd",
                    "tag": "main",
                    "role": "main",
                    "aria_label": None,
                    "text": "Synthetic fixture content.",
                    "bounds": {"x": 0, "y": 72, "width": 1440, "height": 900},
                    "visible": True,
                    "z_index": "auto",
                    "display": "block",
                    "position": "static",
                    "layout": {
                        "flex_direction": "row",
                        "flex_wrap": "nowrap",
                        "justify_content": "normal",
                        "align_items": "normal",
                        "gap": "normal",
                        "grid_template_columns": "none",
                        "grid_template_rows": "none",
                    },
                    "color": "rgb(24, 33, 47)",
                    "background_color": "rgba(0, 0, 0, 0)",
                    "font_family": "Inter, sans-serif",
                    "font_size": "16px",
                    "font_weight": "400",
                    "line_height": "24.8px",
                    "spacing": {
                        "margin_top": "0px",
                        "margin_right": "0px",
                        "margin_bottom": "0px",
                        "margin_left": "0px",
                        "padding_top": "0px",
                        "padding_right": "0px",
                        "padding_bottom": "0px",
                        "padding_left": "0px",
                    },
                    "border": "0px none rgb(24, 33, 47)",
                    "radius": "0px",
                    "shadow": "none",
                    "text_align": "start",
                    "image": None,
                    "parent_section_id": "n-1234abcd",
                }
            ],
            "sections": [
                {
                    "id": "n-1234abcd",
                    "tag": "main",
                    "kind": "semantic-main",
                    "bounds": {"x": 0, "y": 72, "width": 1440, "height": 900},
                    "parent_section_id": None,
                    "node_count": 1,
                }
            ],
            "style_frequencies": {
                "colors": [{"value": "rgb(24, 33, 47)", "count": 1}],
                "font_families": [],
                "font_sizes": [],
                "font_weights": [],
                "line_heights": [],
                "spacing": [],
                "radii": [],
                "shadows": [],
                "borders": [],
            },
            "design_tokens": [
                {
                    "category": "colors",
                    "name": "color-1",
                    "value": "rgb(24, 33, 47)",
                    "count": 1,
                }
            ],
            "summary": {
                "node_count": 1,
                "section_count": 1,
                "card_count": 0,
                "tag_counts": tag_counts or {"main": 1},
                "role_counts": {"main": 1},
                "layout_counts": {"block": 1},
                "heading_outline": [],
                "palette": ["rgb(24, 33, 47)"],
                "font_families": ["Inter, sans-serif"],
                "spacing_scale": [],
            },
            "truncated": False,
        }
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


def test_semantic_snapshot_validation_and_serialization_are_deterministic() -> None:
    first = semantic_snapshot(tag_counts={"main": 1, "body": 1})
    second = semantic_snapshot(tag_counts={"body": 1, "main": 1})
    validated = validate_semantic_snapshot(first.model_dump(mode="json"), BrowserCaptureLimits())

    assert validated.canonical_bytes() == second.canonical_bytes()
    assert len(validated.nodes) == 1
    assert validated.extractor_version == EXTRACTOR_VERSION


def test_semantic_snapshot_rejects_over_limit_browser_payload_with_typed_failure() -> None:
    snapshot = semantic_snapshot()
    node = snapshot.nodes[0]
    oversized = snapshot.model_copy(
        update={
            "nodes": tuple(node.model_copy(update={"id": f"n-{index:08x}"}) for index in range(51)),
            "summary": snapshot.summary.model_copy(update={"node_count": 51}),
        }
    )

    with pytest.raises(BrowserScanError) as caught:
        validate_semantic_snapshot(
            oversized.model_dump(mode="json"),
            BrowserCaptureLimits(maximum_extracted_nodes=50),
        )

    assert caught.value.code is BrowserFailureCode.EXTRACTION_TOO_LARGE


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
