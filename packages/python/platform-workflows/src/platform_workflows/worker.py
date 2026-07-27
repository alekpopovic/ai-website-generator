"""Shared worker limits and readiness indicators."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from platform_workflows.queues import TaskQueue


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Bound concurrency and shutdown behavior for one task queue worker."""

    task_queue: TaskQueue
    max_concurrent_activities: int = 10
    max_concurrent_workflow_tasks: int = 20
    graceful_shutdown_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_concurrent_activities <= 100:
            raise ValueError("max_concurrent_activities must be between 1 and 100")
        if not 1 <= self.max_concurrent_workflow_tasks <= 100:
            raise ValueError("max_concurrent_workflow_tasks must be between 1 and 100")
        if not 0 <= self.graceful_shutdown_seconds <= 300:
            raise ValueError("graceful_shutdown_seconds must be between 0 and 300")


def create_worker(
    client: Client,
    config: WorkerConfig,
    *,
    workflows: Sequence[type[Any]] = (),
    activities: Sequence[Callable[..., Any]] = (),
) -> Worker:
    """Create a bounded worker without starting its poll loop."""
    return Worker(
        client,
        task_queue=config.task_queue.value,
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=config.max_concurrent_activities,
        max_concurrent_workflow_tasks=config.max_concurrent_workflow_tasks,
        graceful_shutdown_timeout=timedelta(seconds=config.graceful_shutdown_seconds),
    )


class WorkerState(StrEnum):
    """Process lifecycle states suitable for health reporting."""

    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WorkerHealthSnapshot:
    """Serializable worker process health state."""

    service: str
    task_queue: str
    state: WorkerState
    changed_at: str
    detail: str | None = None

    @property
    def ready(self) -> bool:
        return self.state is WorkerState.READY


class WorkerHealthIndicator:
    """Track process readiness without adding an HTTP server to every worker."""

    def __init__(self, service: str, task_queue: TaskQueue) -> None:
        self._service = service
        self._task_queue = task_queue
        self._state = WorkerState.STARTING
        self._changed_at = datetime.now(UTC)
        self._detail: str | None = None

    def transition(self, state: WorkerState, *, detail: str | None = None) -> None:
        """Record an explicit lifecycle transition for logs or process probes."""
        self._state = state
        self._detail = detail
        self._changed_at = datetime.now(UTC)

    def snapshot(self) -> WorkerHealthSnapshot:
        """Return the current immutable process indicator."""
        return WorkerHealthSnapshot(
            service=self._service,
            task_queue=self._task_queue.value,
            state=self._state,
            changed_at=self._changed_at.isoformat(),
            detail=self._detail,
        )
