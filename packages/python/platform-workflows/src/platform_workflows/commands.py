"""Compact workflow and activity payload contracts."""

import re
from dataclasses import dataclass
from uuid import UUID

from platform_workflows.identifiers import ModelRole

_OBJECT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!_.*'()/=-]{0,1023}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_uuid(name: str, value: str) -> None:
    try:
        UUID(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a UUID") from error


def _validate_object_key(name: str, value: str | None) -> None:
    if value is not None and not _OBJECT_KEY.fullmatch(value):
        raise ValueError(f"{name} must be a bounded object-storage key")


@dataclass(frozen=True, slots=True)
class CompactWorkflowInput:
    """Common workflow input containing only identifiers and object keys."""

    job_id: str
    project_id: str
    requested_by_user_id: str
    idempotency_key: str
    input_object_key: str | None = None

    def __post_init__(self) -> None:
        _validate_uuid("job_id", self.job_id)
        _validate_uuid("project_id", self.project_id)
        _validate_uuid("requested_by_user_id", self.requested_by_user_id)
        if not _IDEMPOTENCY_KEY.fullmatch(self.idempotency_key):
            raise ValueError("idempotency_key must be a bounded URL-safe identifier")
        _validate_object_key("input_object_key", self.input_object_key)


@dataclass(frozen=True, slots=True)
class ActivityCommand:
    """One idempotent activity stage request with no artifact body."""

    job_id: str
    project_id: str
    stage: str
    input_object_key: str | None = None

    def __post_init__(self) -> None:
        _validate_uuid("job_id", self.job_id)
        _validate_uuid("project_id", self.project_id)
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", self.stage):
            raise ValueError("stage must be a stable lowercase identifier")
        _validate_object_key("input_object_key", self.input_object_key)


@dataclass(frozen=True, slots=True)
class ActivityResult:
    """Compact activity result referencing durable state or an artifact."""

    record_id: str
    output_object_key: str | None = None

    def __post_init__(self) -> None:
        _validate_uuid("record_id", self.record_id)
        _validate_object_key("output_object_key", self.output_object_key)


@dataclass(frozen=True, slots=True)
class CrawlTargetInput:
    """Minimal crawl subprocess command; configuration remains database-owned."""

    campaign_id: str
    scan_target_id: str

    def __post_init__(self) -> None:
        _validate_uuid("campaign_id", self.campaign_id)
        _validate_uuid("scan_target_id", self.scan_target_id)


@dataclass(frozen=True, slots=True)
class RenderPageInput:
    """Minimal browser-render command; PostgreSQL owns URL and capture configuration."""

    campaign_id: str
    crawl_page_id: str

    def __post_init__(self) -> None:
        _validate_uuid("campaign_id", self.campaign_id)
        _validate_uuid("crawl_page_id", self.crawl_page_id)


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """Terminal compact workflow result."""

    job_id: str
    status: str
    output_object_key: str | None = None

    def __post_init__(self) -> None:
        _validate_uuid("job_id", self.job_id)
        if self.status not in {"completed", "cancelled"}:
            raise ValueError("unsupported workflow result status")
        _validate_object_key("output_object_key", self.output_object_key)


@dataclass(frozen=True, slots=True)
class ModelWarmupInput:
    """Compact administrator-approved model warm-up request."""

    job_id: str
    requested_by_user_id: str
    idempotency_key: str
    model_role: ModelRole

    def __post_init__(self) -> None:
        _validate_uuid("job_id", self.job_id)
        _validate_uuid("requested_by_user_id", self.requested_by_user_id)
        if not _IDEMPOTENCY_KEY.fullmatch(self.idempotency_key):
            raise ValueError("idempotency_key must be a bounded URL-safe identifier")
