"""Public, bounded contracts for workflow progress events."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from platform_api.persistence.json import JsonValue

JobType = Literal["scan_campaign", "dataset_build", "generation", "validation", "training"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class JobEventResponse(BaseModel):
    """One sanitized event from the durable PostgreSQL projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    job_id: UUID
    job_type: JobType
    sequence: int = Field(ge=0)
    event_type: str = Field(min_length=1, max_length=100)
    status: JobStatus
    payload: dict[str, JsonValue]
    created_at: datetime


class JobEventPollResponse(BaseModel):
    """Bounded polling fallback with an SSE-compatible cursor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    events: tuple[JobEventResponse, ...]
    next_event_id: int = Field(ge=0)
    terminal: bool
