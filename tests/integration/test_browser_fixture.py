"""Opt-in real Chromium capture against the synthetic local fixture website."""

from __future__ import annotations

import ipaddress
import os
from typing import Any, cast
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import pytest
from platform_browser_worker.models import (
    BrowserCaptureLimits,
    BrowserScanConfiguration,
    BrowserViewport,
    ViewportName,
)
from platform_browser_worker.renderer import PlaywrightBrowserRenderer
from platform_clients.network_safety import (
    ApprovedUrl,
    NetworkRequestContext,
    NetworkSafetyPolicy,
    NetworkSafetySubsystem,
    PlaywrightRequestSafety,
    ValidatedResponseHeaders,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


class FixtureSafety:
    """Explicit integration-only loopback exception; never used by production workers."""

    policy = NetworkSafetyPolicy()

    async def prepare(self, value: str, context: NetworkRequestContext) -> ApprovedUrl:
        del context
        parsed = urlsplit(value)
        return ApprovedUrl(
            url=value,
            scheme=parsed.scheme,
            hostname=parsed.hostname or "127.0.0.1",
            port=parsed.port or 80,
            addresses=frozenset({ipaddress.ip_address("127.0.0.1")}),
        )

    async def prepare_redirect(
        self,
        previous: ApprovedUrl,
        location: str,
        *,
        redirect_count: int,
        context: NetworkRequestContext,
    ) -> ApprovedUrl:
        del redirect_count
        return await self.prepare(urljoin(previous.url, location), context)

    async def revalidate_before_connection(
        self,
        approved: ApprovedUrl,
        context: NetworkRequestContext,
        *,
        peer_address: str | None = None,
    ) -> ApprovedUrl:
        del context, peer_address
        return approved

    async def validate_html_response(
        self, approved: ApprovedUrl, headers: Any, context: NetworkRequestContext
    ) -> ValidatedResponseHeaders:
        del approved, headers, context
        return ValidatedResponseHeaders("text/html", None, 0)


async def test_real_browser_captures_desktop_and_mobile_fixture() -> None:
    base_url = os.environ.get("INTEGRATION_FIXTURE_WEBSITE_URL")
    if base_url is None:
        pytest.skip("INTEGRATION_FIXTURE_WEBSITE_URL is not configured")
    configuration = BrowserScanConfiguration(
        campaign_id=uuid4(),
        project_id=uuid4(),
        target_id=uuid4(),
        crawl_page_id=uuid4(),
        url=base_url.rstrip("/") + "/",
        source_content_sha256=None,
        retention_days=1,
        viewports=(
            BrowserViewport(ViewportName.DESKTOP, 1440, 1000, False),
            BrowserViewport(ViewportName.MOBILE, 390, 844, True),
        ),
        limits=BrowserCaptureLimits(
            navigation_timeout_seconds=15,
            total_timeout_seconds=25,
            stabilization_seconds=1,
        ),
    )
    renderer = PlaywrightBrowserRenderer(
        PlaywrightRequestSafety(cast(NetworkSafetySubsystem, FixtureSafety())),
        maximum_concurrency=1,
    )
    try:
        captures = [
            await renderer.capture(configuration, viewport, request_id=str(uuid4()))
            for viewport in configuration.viewports
        ]
    finally:
        await renderer.close()
    assert all(capture.title == "Northstar Studio Fixture" for capture in captures)
    assert all(capture.full_page_screenshot.startswith(b"\x89PNG") for capture in captures)
    assert all(capture.viewport_screenshot.startswith(b"\x89PNG") for capture in captures)
    assert all("Northstar" in capture.visible_text_summary for capture in captures)
    assert captures[0].dimensions.screenshot_width >= captures[1].dimensions.screenshot_width
    assert all("<html" in capture.rendered_html.casefold() for capture in captures)
