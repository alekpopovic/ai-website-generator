"""Offline-safe helpers for Temporal workflow integration tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from temporalio.testing import WorkflowEnvironment


@dataclass(frozen=True, slots=True)
class TemporalTestServerConfig:
    """Explicit local test-server binary configuration; never auto-download in CI."""

    executable: str

    @classmethod
    def from_environment(cls) -> TemporalTestServerConfig | None:
        value = os.environ.get("TEMPORAL_TEST_SERVER_PATH")
        return None if not value else cls(executable=value)


@asynccontextmanager
async def temporal_test_environment(
    config: TemporalTestServerConfig,
) -> AsyncIterator[WorkflowEnvironment]:
    """Start time-skipping with an explicit binary and no network download."""
    async with await WorkflowEnvironment.start_time_skipping(
        test_server_existing_path=config.executable
    ) as environment:
        yield environment
