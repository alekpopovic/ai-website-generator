"""Activity-side job event publication to a bounded Redis stream."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class JobEvent:
    """Compact observable job event without workflow or artifact payloads."""

    event_id: str
    job_id: str
    project_id: str
    sequence: int
    event_type: str
    status: str
    occurred_at: str
    object_key: str | None = None

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        project_id: str,
        sequence: int,
        event_type: str,
        status: str,
        object_key: str | None = None,
    ) -> JobEvent:
        """Create an event inside an activity or other non-workflow process."""
        UUID(job_id)
        UUID(project_id)
        if sequence < 0:
            raise ValueError("sequence must not be negative")
        if not event_type or len(event_type) > 100:
            raise ValueError("event_type must contain at most 100 characters")
        if status not in {"queued", "running", "succeeded", "failed", "cancelled"}:
            raise ValueError("unsupported job event status")
        return cls(
            event_id=f"{job_id}:{sequence}",
            job_id=job_id,
            project_id=project_id,
            sequence=sequence,
            event_type=event_type,
            status=status,
            occurred_at=datetime.now(UTC).isoformat(),
            object_key=object_key,
        )

    def fields(self) -> Mapping[str, str]:
        """Return stable Redis Stream fields."""
        fields = {
            "event_id": self.event_id,
            "job_id": self.job_id,
            "project_id": self.project_id,
            "sequence": str(self.sequence),
            "event_type": self.event_type,
            "status": self.status,
            "occurred_at": self.occurred_at,
        }
        if self.object_key is not None:
            fields["object_key"] = self.object_key
        return fields


class JobEventPublisher(Protocol):
    """Activity-side event publication boundary."""

    async def publish(self, event: JobEvent) -> str: ...


class RedisStream(Protocol):
    """Narrow Redis capability required for bounded stream publication."""

    async def xadd(
        self,
        name: str,
        fields: Mapping[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str | bytes: ...


class RedisJobEventPublisher:
    """Publish ephemeral progress events; PostgreSQL remains the durable projection."""

    def __init__(
        self, redis: RedisStream, *, stream: str = "aiwg:job-events", maxlen: int = 10_000
    ) -> None:
        if not 100 <= maxlen <= 1_000_000:
            raise ValueError("job event stream maxlen must be between 100 and 1000000")
        self._redis = redis
        self._stream = stream
        self._maxlen = maxlen

    async def publish(self, event: JobEvent) -> str:
        """Append an event from an activity with bounded retention."""
        entry_id = await self._redis.xadd(
            self._stream,
            event.fields(),
            maxlen=self._maxlen,
            approximate=True,
        )
        return entry_id.decode() if isinstance(entry_id, bytes) else entry_id


class InMemoryJobEventPublisher:
    """Deterministic event publisher for unit tests."""

    def __init__(self) -> None:
        self.events: list[JobEvent] = []

    async def publish(self, event: JobEvent) -> str:
        self.events.append(event)
        return f"fake-{len(self.events)}"
