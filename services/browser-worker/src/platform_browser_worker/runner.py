"""Cancellable orchestration of idempotent viewport captures."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from platform_workflows.commands import RenderPageInput

from platform_browser_worker.models import (
    BrowserCapture,
    BrowserFailureCode,
    BrowserScanConfiguration,
    BrowserScanError,
    BrowserViewport,
    PreparedPageScan,
)
from platform_browser_worker.renderer import BrowserRenderer

ProgressCallback = Callable[[str, int], Awaitable[None]]


class BrowserRepository(Protocol):
    async def load_configuration(
        self, campaign_id: UUID, crawl_page_id: UUID
    ) -> BrowserScanConfiguration: ...

    async def prepare(
        self, configuration: BrowserScanConfiguration, viewport: BrowserViewport
    ) -> PreparedPageScan: ...

    async def complete(
        self,
        configuration: BrowserScanConfiguration,
        prepared: PreparedPageScan,
        capture: BrowserCapture,
    ) -> None: ...

    async def fail(
        self,
        configuration: BrowserScanConfiguration,
        prepared: PreparedPageScan | None,
        error: BrowserScanError,
    ) -> None: ...

    async def cancel(
        self, configuration: BrowserScanConfiguration, prepared: PreparedPageScan | None
    ) -> None: ...


class BrowserScanRunner:
    def __init__(self, repository: BrowserRepository, renderer: BrowserRenderer) -> None:
        self._repository = repository
        self._renderer = renderer

    async def scan(
        self, command: RenderPageInput, progress: ProgressCallback | None = None
    ) -> None:
        configuration = await self._repository.load_configuration(
            UUID(command.campaign_id), UUID(command.crawl_page_id)
        )
        completed = 0
        for viewport in configuration.viewports:
            prepared: PreparedPageScan | None = None
            try:
                prepared = await self._repository.prepare(configuration, viewport)
                if prepared.already_succeeded:
                    completed += 1
                    if progress is not None:
                        await progress(f"skip-{viewport.name.value}", completed)
                    continue

                completed_before_capture = completed

                async def render_progress(
                    stage: str, completed_value: int = completed_before_capture
                ) -> None:
                    if progress is not None:
                        await progress(stage, completed_value)

                capture = await self._renderer.capture(
                    configuration,
                    viewport,
                    request_id=str(prepared.id),
                    progress=render_progress,
                )
                await self._repository.complete(configuration, prepared, capture)
                completed += 1
                if progress is not None:
                    await progress(f"complete-{viewport.name.value}", completed)
            except asyncio.CancelledError:
                await self._repository.cancel(configuration, prepared)
                raise
            except BrowserScanError as error:
                await self._repository.fail(configuration, prepared, error)
                raise
            except Exception as error:
                sanitized = BrowserScanError(
                    BrowserFailureCode.CAPTURE_FAILED,
                    "Browser capture failed unexpectedly.",
                    retryable=True,
                )
                await self._repository.fail(configuration, prepared, sanitized)
                raise sanitized from error


class FakeBrowserRenderer:
    """Deterministic, no-browser renderer used by default unit tests."""

    def __init__(self, captures: dict[str, BrowserCapture], error: Exception | None = None) -> None:
        self.captures = captures
        self.error = error
        self.calls: list[tuple[UUID, str]] = []
        self.closed = False

    async def capture(
        self,
        configuration: BrowserScanConfiguration,
        viewport: BrowserViewport,
        *,
        request_id: str,
        progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> BrowserCapture:
        del request_id
        self.calls.append((configuration.crawl_page_id, viewport.name.value))
        if progress is not None:
            await progress(f"fake-{viewport.name.value}")
        if self.error is not None:
            raise self.error
        return self.captures[viewport.name.value]

    async def close(self) -> None:
        self.closed = True
