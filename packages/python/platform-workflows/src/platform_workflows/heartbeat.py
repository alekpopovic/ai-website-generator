"""Heartbeat primitives for long-running asynchronous activities."""

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TypeVar

from temporalio import activity

ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class HeartbeatConfig:
    """Bounded activity heartbeat cadence."""

    interval_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not 1 <= self.interval_seconds <= 60:
            raise ValueError("heartbeat interval must be between 1 and 60 seconds")


class ActivityHeartbeat:
    """Report progress manually or while awaiting one cancellable operation."""

    def __init__(self, config: HeartbeatConfig | None = None) -> None:
        self._config = config or HeartbeatConfig()

    def report(self, *, stage: str, completed: int | None = None) -> None:
        """Emit compact progress details; never include payload bodies or secrets."""
        details: dict[str, str | int] = {"stage": stage}
        if completed is not None:
            details["completed"] = completed
        activity.heartbeat(details)

    async def while_running(
        self,
        operation: Awaitable[ResultT],
        *,
        stage: str,
    ) -> ResultT:
        """Heartbeat until the operation finishes and propagate cancellation."""
        operation_task = asyncio.ensure_future(operation)
        try:
            while True:
                done, _ = await asyncio.wait(
                    {operation_task}, timeout=self._config.interval_seconds
                )
                if done:
                    return await operation_task
                self.report(stage=stage)
        except asyncio.CancelledError:
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            raise
