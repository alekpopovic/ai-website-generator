"""Warm Playwright browser with a fresh hostile-content context for every capture."""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Protocol
from urllib.parse import urlsplit

from platform_clients.network_safety import (
    ApprovedUrl,
    NetworkRequestContext,
    NetworkSafetyError,
    PlaywrightRequestSafety,
)
from playwright.async_api import (
    Browser,
    BrowserContext,
    ConsoleMessage,
    Dialog,
    Download,
    Page,
    Playwright,
    Request,
    Route,
    WebSocketRoute,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from platform_browser_worker.models import (
    BrowserCapture,
    BrowserFailureCode,
    BrowserScanConfiguration,
    BrowserScanError,
    BrowserViewport,
    DocumentDimensions,
)

ProgressCallback = Callable[[str], Awaitable[None]]
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()
_SPACE = re.compile(r"\s+")
_TRACKER_HOST_PARTS = (
    "analytics",
    "doubleclick",
    "facebook.net",
    "googletagmanager",
    "google-analytics",
    "hotjar",
    "segment.io",
)
_LARGE_DOWNLOAD_SUFFIXES = (
    ".7z",
    ".avi",
    ".dmg",
    ".exe",
    ".iso",
    ".mov",
    ".mp4",
    ".mpeg",
    ".rar",
    ".tar",
    ".webm",
    ".zip",
)
_SAFE_RESPONSE_HEADERS = frozenset(
    {"cache-control", "content-length", "content-type", "etag", "last-modified"}
)


class BrowserRenderer(Protocol):
    async def capture(
        self,
        configuration: BrowserScanConfiguration,
        viewport: BrowserViewport,
        *,
        request_id: str,
        progress: ProgressCallback | None = None,
    ) -> BrowserCapture: ...

    async def close(self) -> None: ...


class PlaywrightBrowserRenderer:
    """Keep Chromium warm while isolating every page in a non-persistent context."""

    def __init__(
        self,
        request_safety: PlaywrightRequestSafety,
        *,
        maximum_concurrency: int = 2,
    ) -> None:
        if not 1 <= maximum_concurrency <= 16:
            raise ValueError("browser concurrency must be between 1 and 16")
        self._request_safety = request_safety
        self._semaphore = asyncio.Semaphore(maximum_concurrency)
        self._start_lock = asyncio.Lock()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def capture(
        self,
        configuration: BrowserScanConfiguration,
        viewport: BrowserViewport,
        *,
        request_id: str,
        progress: ProgressCallback | None = None,
    ) -> BrowserCapture:
        async with self._semaphore:
            browser = await self._browser_process()
            try:
                context = await browser.new_context(
                    viewport={"width": viewport.width, "height": viewport.height},
                    screen={"width": viewport.width, "height": viewport.height},
                    device_scale_factor=viewport.device_scale_factor,
                    is_mobile=viewport.is_mobile,
                    has_touch=viewport.is_mobile,
                    accept_downloads=False,
                    service_workers="block",
                    permissions=[],
                    java_script_enabled=True,
                    bypass_csp=False,
                    reduced_motion="reduce",
                )
            except PlaywrightError as error:
                if not browser.is_connected():
                    await self._discard_browser()
                    code = BrowserFailureCode.BROWSER_CRASHED
                else:
                    code = BrowserFailureCode.CAPTURE_FAILED
                raise BrowserScanError(
                    code,
                    "Playwright could not create an isolated browser context.",
                    retryable=True,
                ) from error
            context.set_default_navigation_timeout(
                configuration.limits.navigation_timeout_seconds * 1_000
            )
            context.set_default_timeout(configuration.limits.navigation_timeout_seconds * 1_000)
            await context.clear_permissions()
            try:
                operation = self._capture_context(
                    context,
                    configuration,
                    viewport,
                    request_id=request_id,
                    progress=progress,
                )
                return await asyncio.wait_for(
                    operation, timeout=configuration.limits.total_timeout_seconds
                )
            except TimeoutError as error:
                raise BrowserScanError(
                    BrowserFailureCode.NAVIGATION_TIMEOUT,
                    "Browser capture exceeded its total timeout.",
                    retryable=True,
                ) from error
            except PlaywrightTimeoutError as error:
                raise BrowserScanError(
                    BrowserFailureCode.NAVIGATION_TIMEOUT,
                    "Browser navigation exceeded its timeout.",
                    retryable=True,
                ) from error
            except NetworkSafetyError as error:
                raise BrowserScanError(
                    BrowserFailureCode.NAVIGATION_BLOCKED,
                    f"Browser navigation was blocked by outbound policy ({error.code.value}).",
                    retryable=error.retryable,
                ) from error
            except PlaywrightError as error:
                if not browser.is_connected():
                    await self._discard_browser()
                    code = BrowserFailureCode.BROWSER_CRASHED
                else:
                    code = BrowserFailureCode.NAVIGATION_FAILED
                raise BrowserScanError(
                    code,
                    "Playwright could not complete the bounded page capture.",
                    retryable=True,
                ) from error
            finally:
                with contextlib.suppress(PlaywrightError):
                    await context.close(reason="isolated page capture completed")

    async def _capture_context(
        self,
        context: BrowserContext,
        configuration: BrowserScanConfiguration,
        viewport: BrowserViewport,
        *,
        request_id: str,
        progress: ProgressCallback | None,
    ) -> BrowserCapture:
        errors = _CaptureEvents(configuration.url)
        safety_context = self._request_safety.context(
            request_id=request_id, project_id=str(configuration.project_id)
        )
        approved_by_request: dict[int, ApprovedUrl] = {}

        async def block_websocket(socket: WebSocketRoute) -> None:
            with contextlib.suppress(NetworkSafetyError):
                await self._request_safety.initial(socket.url, safety_context)
            await socket.close(code=1008, reason="WebSocket egress is not permitted")

        await context.route_web_socket("**/*", block_websocket)
        page = await context.new_page()
        page.on("console", errors.console)
        page.on("pageerror", errors.page_error)
        page.on("requestfailed", errors.request_failed)
        page.on("popup", lambda popup: _schedule(popup.close()))
        page.on("dialog", lambda dialog: _schedule(_dismiss_dialog(dialog)))
        page.on("download", lambda download: _schedule(_cancel_download(download)))
        context.on("page", lambda opened: _close_extra_page(page, opened))

        async def route_request(route: Route, request: Request) -> None:
            await self._route(
                route,
                request,
                safety_context,
                approved_by_request,
                errors,
                errors.external_hosts,
            )

        await context.route("**/*", route_request)
        initial = await self._request_safety.initial(configuration.url, safety_context)
        await self._request_safety.before_connection(initial, safety_context)
        if progress is not None:
            await progress(f"navigate-{viewport.name.value}")
        try:
            response = await page.goto(
                initial.url,
                wait_until="domcontentloaded",
                timeout=configuration.limits.navigation_timeout_seconds * 1_000,
            )
        except PlaywrightError as error:
            if errors.primary_blocked is not None:
                raise errors.primary_blocked from error
            raise
        if response is None:
            raise BrowserScanError(
                BrowserFailureCode.NAVIGATION_FAILED,
                "The primary document produced no HTTP response.",
                retryable=True,
            )
        final_approved = await self._request_safety.initial(response.url, safety_context)
        validated_headers = await self._request_safety.html_response(
            final_approved, await response.all_headers(), safety_context
        )
        if progress is not None:
            await progress(f"stabilize-{viewport.name.value}")
        await self._stabilize(page, configuration.limits.stabilization_seconds)
        observations = await page.evaluate(_OBSERVATION_SCRIPT)
        if not isinstance(observations, dict):
            raise BrowserScanError(
                BrowserFailureCode.CAPTURE_FAILED,
                "Browser metadata extraction returned an invalid result.",
            )
        html_bytes = _bounded_integer(observations.get("htmlBytes"))
        if html_bytes > configuration.limits.maximum_html_bytes:
            raise BrowserScanError(
                BrowserFailureCode.RENDERED_HTML_TOO_LARGE,
                "Rendered HTML exceeded the configured byte limit.",
            )
        rendered_html = await page.content()
        if len(rendered_html.encode("utf-8")) > configuration.limits.maximum_html_bytes:
            raise BrowserScanError(
                BrowserFailureCode.RENDERED_HTML_TOO_LARGE,
                "Rendered HTML changed beyond the configured byte limit.",
            )
        document_width = _bounded_integer(observations.get("width"))
        document_height = _bounded_integer(observations.get("height"))
        screenshot_width = min(document_width, configuration.limits.maximum_page_width)
        screenshot_height = min(document_height, configuration.limits.maximum_page_height)
        truncated = (
            document_width > configuration.limits.maximum_page_width
            or document_height > configuration.limits.maximum_page_height
        )
        if progress is not None:
            await progress(f"screenshots-{viewport.name.value}")
        viewport_screenshot = await page.screenshot(
            full_page=False, animations="disabled", type="png"
        )
        if truncated:
            full_page_screenshot = await page.screenshot(
                clip={
                    "x": 0,
                    "y": 0,
                    "width": max(1, screenshot_width),
                    "height": max(1, screenshot_height),
                },
                animations="disabled",
                type="png",
            )
        else:
            full_page_screenshot = await page.screenshot(
                full_page=True, animations="disabled", type="png"
            )
        for screenshot in (viewport_screenshot, full_page_screenshot):
            if len(screenshot) > configuration.limits.maximum_screenshot_bytes:
                raise BrowserScanError(
                    BrowserFailureCode.SCREENSHOT_TOO_LARGE,
                    "A browser screenshot exceeded the configured byte limit.",
                )
        raw_headers = await response.all_headers()
        response_metadata: dict[str, str | int | bool | None] = {
            "status": response.status,
            "status_text": response.status_text[:100],
            "from_service_worker": response.from_service_worker,
            "content_type": validated_headers.content_type,
            "content_length": validated_headers.content_length,
        }
        for name in _SAFE_RESPONSE_HEADERS:
            if name in raw_headers:
                response_metadata[f"header_{name.replace('-', '_')}"] = raw_headers[name][:500]
        return BrowserCapture(
            final_url=response.url,
            rendered_html=rendered_html,
            full_page_screenshot=full_page_screenshot,
            viewport_screenshot=viewport_screenshot,
            response_metadata=response_metadata,
            title=_bounded_text(observations.get("title"), 500),
            meta_description=_optional_text(observations.get("description"), 1_000),
            canonical_url=_optional_text(observations.get("canonical"), 2_048),
            language=_optional_text(observations.get("language"), 35),
            visible_text_summary=_bounded_text(observations.get("visibleText"), 4_000),
            console_errors=tuple(errors.console_errors),
            page_errors=tuple(errors.page_errors),
            failed_requests=tuple(errors.failed_requests),
            external_hosts=tuple(sorted(errors.external_hosts)),
            dimensions=DocumentDimensions(
                width=document_width,
                height=document_height,
                screenshot_width=screenshot_width,
                screenshot_height=screenshot_height,
                full_page_truncated=truncated,
            ),
            browser_version=(await self._browser_process()).version,
        )

    async def _route(
        self,
        route: Route,
        request: Request,
        context: NetworkRequestContext,
        approved_by_request: dict[int, ApprovedUrl],
        errors: _CaptureEvents,
        external_hosts: set[str],
    ) -> None:
        parsed = urlsplit(request.url)
        hostname = (parsed.hostname or "").casefold()
        try:
            redirected_from = request.redirected_from
            if redirected_from is not None:
                previous = approved_by_request.get(id(redirected_from))
                if previous is None:
                    previous = await self._request_safety.initial(redirected_from.url, context)
                approved = await self._request_safety.redirect(
                    previous,
                    request.url,
                    max(0, _redirect_count(request) - 1),
                    context,
                )
            else:
                approved = await self._request_safety.initial(request.url, context)
            approved_by_request[id(request)] = approved
            page_host = urlsplit(request.frame.url).hostname if request.frame else None
            if page_host is not None and approved.hostname != page_host.casefold():
                external_hosts.add(approved.hostname)
            if request.resource_type == "media" or parsed.path.casefold().endswith(
                _LARGE_DOWNLOAD_SUFFIXES
            ):
                await route.abort("blockedbyclient")
                return
            if any(part in hostname for part in _TRACKER_HOST_PARTS):
                await route.abort("blockedbyclient")
                return
            await self._request_safety.before_connection(approved, context)
            await route.continue_()
        except NetworkSafetyError as error:
            await route.abort("blockedbyclient")
            if request.is_navigation_request() and request.frame.parent_frame is None:
                errors.primary_blocked = error

    @staticmethod
    async def _stabilize(page: Page, maximum_seconds: float) -> None:
        with contextlib.suppress(TimeoutError, PlaywrightError):
            await asyncio.wait_for(
                page.evaluate("() => document.fonts ? document.fonts.ready : Promise.resolve()"),
                timeout=min(2.0, maximum_seconds),
            )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + maximum_seconds
        previous: tuple[int, int] | None = None
        stable_samples = 0
        while loop.time() < deadline and stable_samples < 3:
            dimensions = await page.evaluate(
                "() => [document.documentElement.scrollWidth, document.documentElement.scrollHeight]"
            )
            current = (
                _bounded_integer(dimensions[0]),
                _bounded_integer(dimensions[1]),
            )
            stable_samples = stable_samples + 1 if current == previous else 0
            previous = current
            await asyncio.sleep(0.2)

    async def _browser_process(self) -> Browser:
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        async with self._start_lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            await self._discard_browser()
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                chromium_sandbox=True,
                # Do not inherit database, object-storage, Temporal, proxy, or cloud credentials.
                env={"LANG": "C.UTF-8", "TZ": "UTC"},
                args=[
                    "--disable-background-networking",
                    "--disable-breakpad",
                    "--disable-component-update",
                    "--disable-default-apps",
                    "--disable-domain-reliability",
                    "--disable-extensions",
                    "--disable-features=MediaRouter,OptimizationHints,Translate",
                    "--disable-quic",
                    "--disable-sync",
                    "--deny-permission-prompts",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    "--metrics-recording-only",
                    "--no-first-run",
                    "--no-pings",
                    "--no-proxy-server",
                ],
            )
            return self._browser

    async def start(self) -> None:
        """Start the reusable browser before worker readiness is advertised."""
        await self._browser_process()

    async def _discard_browser(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._browser = None
        self._playwright = None
        if browser is not None:
            with contextlib.suppress(PlaywrightError):
                await browser.close(reason="browser worker shutdown")
        if playwright is not None:
            with contextlib.suppress(PlaywrightError):
                await playwright.stop()

    async def close(self) -> None:
        async with self._start_lock:
            await self._discard_browser()


class _CaptureEvents:
    def __init__(self, page_url: str) -> None:
        self._page_host = (urlsplit(page_url).hostname or "").casefold()
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []
        self.failed_requests: list[dict[str, str]] = []
        self.external_hosts: set[str] = set()
        self.primary_blocked: NetworkSafetyError | None = None

    def console(self, message: ConsoleMessage) -> None:
        if message.type == "error" and len(self.console_errors) < 100:
            self.console_errors.append(_bounded_text(message.text, 1_000))

    def page_error(self, error: Exception) -> None:
        if len(self.page_errors) < 100:
            self.page_errors.append(_bounded_text(str(error), 1_000))

    def request_failed(self, request: Request) -> None:
        if len(self.failed_requests) >= 200:
            return
        parsed = urlsplit(request.url)
        hostname = (parsed.hostname or "").casefold()
        if hostname and hostname != self._page_host:
            self.external_hosts.add(hostname)
        failure = request.failure or "request_failed"
        self.failed_requests.append(
            {
                "host": hostname[:253],
                "resource_type": request.resource_type[:50],
                "error": _bounded_text(failure, 200),
            }
        )


def _redirect_count(request: Request) -> int:
    count = 0
    current = request.redirected_from
    while current is not None:
        count += 1
        current = current.redirected_from
    return count


def _bounded_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1
    return max(1, min(int(value), 1_000_000))


def _bounded_text(value: object, limit: int) -> str:
    return _SPACE.sub(" ", value if isinstance(value, str) else "").strip()[:limit]


def _optional_text(value: object, limit: int) -> str | None:
    normalized = _bounded_text(value, limit)
    return normalized or None


async def _dismiss_dialog(dialog: Dialog) -> None:
    with contextlib.suppress(PlaywrightError):
        await dialog.dismiss()


async def _cancel_download(download: Download) -> None:
    with contextlib.suppress(PlaywrightError):
        await download.cancel()


def _close_extra_page(primary: Page, opened: Page) -> None:
    if opened is not primary:
        _schedule(opened.close(reason="new windows are denied"))


def _schedule(operation: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(operation)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


_OBSERVATION_SCRIPT = r"""
() => {
  const root = document.documentElement;
  const body = document.body;
  const width = Math.max(root?.scrollWidth || 0, body?.scrollWidth || 0, root?.clientWidth || 0);
  const height = Math.max(root?.scrollHeight || 0, body?.scrollHeight || 0, root?.clientHeight || 0);
  return {
    width,
    height,
    title: document.title || '',
    description: document.querySelector('meta[name="description" i]')?.getAttribute('content') || null,
    canonical: document.querySelector('link[rel~="canonical" i]')?.href || null,
    language: root?.lang || null,
    visibleText: (body?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 4000),
    htmlBytes: new TextEncoder().encode(root?.outerHTML || '').byteLength,
  };
}
"""
