"""Cancellable subprocess boundary that keeps Twisted out of Temporal workers."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from platform_workflows.commands import CrawlTargetInput

ProgressCallback = Callable[[int], Awaitable[None]]


class CrawlerProcessError(RuntimeError):
    """Sanitized subprocess failure without captured page content or URLs."""


class CrawlerRunner(Protocol):
    async def crawl(
        self, command: CrawlTargetInput, progress: ProgressCallback | None = None
    ) -> None: ...


@dataclass(slots=True)
class SubprocessCrawlerRunner:
    terminate_timeout_seconds: float = 10.0
    maximum_line_bytes: int = 4_096
    module: str = "platform_crawler_worker.subprocess_main"

    async def crawl(
        self, command: CrawlTargetInput, progress: ProgressCallback | None = None
    ) -> None:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            self.module,
            "--campaign-id",
            command.campaign_id,
            "--scan-target-id",
            command.scan_target_id,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdout is None or process.stderr is None:
            process.kill()
            raise CrawlerProcessError("crawler subprocess pipes were not created")
        stdout_task = asyncio.create_task(self._read_progress(process.stdout, progress))
        stderr_task = asyncio.create_task(self._drain(process.stderr))
        try:
            return_code = await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
        except asyncio.CancelledError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=self.terminate_timeout_seconds)
            except TimeoutError:
                process.kill()
                await process.wait()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        if return_code != 0:
            raise CrawlerProcessError(f"crawler subprocess exited with status {return_code}")

    async def _read_progress(
        self, stream: asyncio.StreamReader, callback: ProgressCallback | None
    ) -> None:
        while line := await stream.readline():
            if len(line) > self.maximum_line_bytes:
                continue
            try:
                event = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (
                callback is not None
                and isinstance(event, dict)
                and event.get("event") == "progress"
                and isinstance(event.get("completed"), int)
            ):
                await callback(event["completed"])

    async def _drain(self, stream: asyncio.StreamReader) -> None:
        """Drain but never log subprocess stderr, which may contain hostile content."""
        while chunk := await stream.read(8_192):
            del chunk


class FakeCrawlerRunner:
    """Deterministic no-network crawler used by activity unit tests."""

    def __init__(self, *, progress_values: tuple[int, ...] = (1,), error: Exception | None = None):
        self.progress_values = progress_values
        self.error = error
        self.commands: list[CrawlTargetInput] = []

    async def crawl(
        self, command: CrawlTargetInput, progress: ProgressCallback | None = None
    ) -> None:
        self.commands.append(command)
        for completed in self.progress_values:
            if progress is not None:
                await progress(completed)
        if self.error is not None:
            raise self.error
