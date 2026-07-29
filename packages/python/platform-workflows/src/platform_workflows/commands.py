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
    resource_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_uuid("job_id", self.job_id)
        _validate_uuid("project_id", self.project_id)
        _validate_uuid("requested_by_user_id", self.requested_by_user_id)
        if not _IDEMPOTENCY_KEY.fullmatch(self.idempotency_key):
            raise ValueError("idempotency_key must be a bounded URL-safe identifier")
        _validate_object_key("input_object_key", self.input_object_key)
        if len(self.resource_ids) > 100 or len(self.resource_ids) != len(set(self.resource_ids)):
            raise ValueError("resource_ids must contain at most 100 unique UUIDs")
        for resource_id in self.resource_ids:
            _validate_uuid("resource_id", resource_id)


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
class DatasetBuildStageInput:
    """Identifier-only command for one deterministic dataset build stage."""

    build_id: str
    project_id: str
    stage: str

    def __post_init__(self) -> None:
        _validate_uuid("build_id", self.build_id)
        _validate_uuid("project_id", self.project_id)
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", self.stage):
            raise ValueError("stage must be a bounded stable identifier")


@dataclass(frozen=True, slots=True)
class DatasetBuildStageResult:
    """Compact stage outcome; dataset bodies never enter workflow history."""

    build_id: str
    status: str
    embedding_run_id: str | None = None

    def __post_init__(self) -> None:
        _validate_uuid("build_id", self.build_id)
        if self.status not in {"running", "passed", "failed", "cancelled", "sealed"}:
            raise ValueError("unsupported dataset build stage status")
        if self.embedding_run_id is not None:
            _validate_uuid("embedding_run_id", self.embedding_run_id)


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
        if self.status not in {"completed", "partially_completed", "failed", "cancelled"}:
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


@dataclass(frozen=True, slots=True)
class EmbeddingIndexInput:
    """Identifier-only command for an incremental index or full reindex run."""

    embedding_run_id: str

    def __post_init__(self) -> None:
        _validate_uuid("embedding_run_id", self.embedding_run_id)


@dataclass(frozen=True, slots=True)
class ScanCampaignPlan:
    campaign_id: str
    target_concurrency: int
    browser_concurrency: int
    ai_concurrency: int
    page_size: int = 100

    def __post_init__(self) -> None:
        _validate_uuid("campaign_id", self.campaign_id)
        if not 1 <= self.target_concurrency <= 128:
            raise ValueError("target_concurrency must be between 1 and 128")
        if not 1 <= self.browser_concurrency <= 32:
            raise ValueError("browser_concurrency must be between 1 and 32")
        if not 1 <= self.ai_concurrency <= 16:
            raise ValueError("ai_concurrency must be between 1 and 16")
        if not 1 <= self.page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class ScanIdentifierPage:
    identifiers: tuple[str, ...]
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if len(self.identifiers) > 100 or len(self.identifiers) != len(set(self.identifiers)):
            raise ValueError("identifier page must contain at most 100 unique UUIDs")
        for value in self.identifiers:
            _validate_uuid("identifier", value)
        if self.next_cursor is not None:
            _validate_uuid("next_cursor", self.next_cursor)


@dataclass(frozen=True, slots=True)
class ScanListInput:
    campaign_id: str
    cursor: str | None = None
    limit: int = 100
    target_id: str | None = None
    failure_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_uuid("campaign_id", self.campaign_id)
        if self.cursor is not None:
            _validate_uuid("cursor", self.cursor)
        if self.target_id is not None:
            _validate_uuid("target_id", self.target_id)
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if len(self.failure_ids) > 100:
            raise ValueError("failure_ids must contain at most 100 UUIDs")
        for value in self.failure_ids:
            _validate_uuid("failure_id", value)


@dataclass(frozen=True, slots=True)
class ScanTargetWorkflowInput:
    campaign_id: str
    project_id: str
    target_id: str
    browser_concurrency: int
    ai_concurrency: int

    def __post_init__(self) -> None:
        _validate_uuid("campaign_id", self.campaign_id)
        _validate_uuid("project_id", self.project_id)
        _validate_uuid("target_id", self.target_id)
        if not 1 <= self.browser_concurrency <= 32:
            raise ValueError("browser_concurrency must be between 1 and 32")
        if not 1 <= self.ai_concurrency <= 16:
            raise ValueError("ai_concurrency must be between 1 and 16")


@dataclass(frozen=True, slots=True)
class ScanPageInput:
    campaign_id: str
    crawl_page_id: str

    def __post_init__(self) -> None:
        _validate_uuid("campaign_id", self.campaign_id)
        _validate_uuid("crawl_page_id", self.crawl_page_id)


@dataclass(frozen=True, slots=True)
class ScanProgressInput:
    campaign_id: str
    project_id: str
    stage: str
    status: str
    sequence: int
    target_id: str | None = None
    completed: int = 0
    failed: int = 0

    def __post_init__(self) -> None:
        _validate_uuid("campaign_id", self.campaign_id)
        _validate_uuid("project_id", self.project_id)
        if self.target_id is not None:
            _validate_uuid("target_id", self.target_id)
        if not re.fullmatch(r"[a-z][a-z0-9.-]{0,99}", self.stage):
            raise ValueError("stage must be a bounded stable identifier")
        if self.status not in {"queued", "running", "paused", "succeeded", "failed", "cancelled"}:
            raise ValueError("unsupported scan progress status")
        if self.sequence < 0 or self.completed < 0 or self.failed < 0:
            raise ValueError("scan progress counts must not be negative")


@dataclass(frozen=True, slots=True)
class ScanAggregationInput:
    campaign_id: str
    project_id: str
    succeeded_targets: int
    failed_targets: int
    cancelled: bool = False

    def __post_init__(self) -> None:
        _validate_uuid("campaign_id", self.campaign_id)
        _validate_uuid("project_id", self.project_id)
        if self.succeeded_targets < 0 or self.failed_targets < 0:
            raise ValueError("aggregation counts must not be negative")


@dataclass(frozen=True, slots=True)
class ScanTargetResult:
    target_id: str
    status: str
    rendered_pages: int = 0
    analyzed_pages: int = 0
    failed_pages: int = 0

    def __post_init__(self) -> None:
        _validate_uuid("target_id", self.target_id)
        if self.status not in {"succeeded", "partially_succeeded", "failed", "cancelled"}:
            raise ValueError("unsupported target result status")
        if min(self.rendered_pages, self.analyzed_pages, self.failed_pages) < 0:
            raise ValueError("target result counts must not be negative")
