"""Strict scan campaign API and configuration contracts."""

from __future__ import annotations

import ipaddress
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import UUID

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from platform_api.models.common import PaginationParams

ScanCampaignStatus = Literal[
    "draft",
    "queued",
    "running",
    "pausing",
    "paused",
    "cancelling",
    "cancelled",
    "succeeded",
    "partially_succeeded",
    "failed",
]
ScanTargetStatus = Literal["pending", "accepted", "rejected", "completed", "failed"]
CrawlPageStatus = Literal["discovered", "blocked", "fetching", "fetched", "failed"]
PageScanStatus = Literal["pending", "rendering", "succeeded", "failed", "cancelled"]
FailureStage = Literal["control", "crawl", "browser", "analysis", "embedding"]
CampaignSort = Literal["created_at", "name", "updated_at"]
SortOrder = Literal["asc", "desc"]
TargetImportSource = Literal["paste", "text", "csv"]
TargetImportStatus = Literal["validating", "completed", "committed", "failed"]
TargetImportOutcome = Literal["accepted", "duplicate", "invalid", "blocked", "already_present"]


class ScanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Viewport(ScanModel):
    width: int = Field(ge=320, le=7_680)
    height: int = Field(ge=480, le=8_640)


class ScanTimeoutLimits(ScanModel):
    connect_seconds: float = Field(default=10, ge=1, le=60)
    response_seconds: float = Field(default=30, ge=1, le=300)
    browser_page_seconds: float = Field(default=45, ge=5, le=300)
    campaign_seconds: int = Field(default=7_200, ge=60, le=86_400)


class ArtifactRetentionPolicy(ScanModel):
    retention_days: int = Field(default=30, ge=1, le=3_650)
    retain_failures: bool = True
    legal_hold: bool = False


class CampaignConfiguration(ScanModel):
    authorization_attested_at: datetime
    respect_robots_txt: bool = True
    max_discovered_pages_per_domain: int = Field(default=100, ge=1, le=10_000)
    max_visual_pages_per_domain: int = Field(default=20, ge=0, le=1_000)
    maximum_crawl_depth: int = Field(default=5, ge=0, le=20)
    per_domain_concurrency: int = Field(default=2, ge=1, le=32)
    crawl_delay_seconds: float = Field(default=1.0, ge=0, le=60)
    overall_concurrency: int = Field(default=4, ge=1, le=128)
    desktop_viewport: Viewport = Viewport(width=1440, height=900)
    mobile_viewport: Viewport = Viewport(width=390, height=844)
    allowed_content_types: tuple[str, ...] = ("text/html", "application/xhtml+xml")
    include_url_patterns: tuple[str, ...] = ()
    exclude_url_patterns: tuple[str, ...] = ()
    timeout_limits: ScanTimeoutLimits = ScanTimeoutLimits()
    artifact_retention_policy: ArtifactRetentionPolicy = ArtifactRetentionPolicy()

    @field_validator("authorization_attested_at")
    @classmethod
    def validate_attestation(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Authorization attestation timestamp must include a timezone.")
        normalized = value.astimezone(UTC)
        if normalized > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("Authorization attestation timestamp must not be in the future.")
        return normalized

    @field_validator("allowed_content_types")
    @classmethod
    def validate_content_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip().casefold() for value in values)
        if (
            not normalized
            or len(normalized) > 20
            or len(normalized) != len(set(normalized))
            or any(
                re.fullmatch(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*", value)
                is None
                for value in normalized
            )
        ):
            raise ValueError("Allowed content types must be unique concrete MIME types.")
        return normalized

    @field_validator("include_url_patterns", "exclude_url_patterns")
    @classmethod
    def validate_url_globs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if len(normalized) > 100 or len(normalized) != len(set(normalized)):
            raise ValueError("URL patterns must be unique and contain at most 100 entries.")
        if any(
            not value
            or len(value) > 500
            or "\x00" in value
            or "\\" in value
            or value.count("*") > 10
            for value in normalized
        ):
            raise ValueError("URL patterns must be bounded forward-slash glob patterns.")
        return normalized

    @model_validator(mode="after")
    def validate_concurrency(self) -> Self:
        if self.per_domain_concurrency > self.overall_concurrency:
            raise ValueError("Per-domain concurrency cannot exceed overall concurrency.")
        if self.max_visual_pages_per_domain > self.max_discovered_pages_per_domain:
            raise ValueError("Visual page limit cannot exceed the discovery limit.")
        return self


class ScanCampaignCreateRequest(CampaignConfiguration):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Campaign name must not be blank.")
        return normalized


class ScanCampaignUpdateRequest(ScanModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    authorization_attested_at: datetime | None = None
    respect_robots_txt: bool | None = None
    max_discovered_pages_per_domain: int | None = Field(default=None, ge=1, le=10_000)
    max_visual_pages_per_domain: int | None = Field(default=None, ge=0, le=1_000)
    maximum_crawl_depth: int | None = Field(default=None, ge=0, le=20)
    per_domain_concurrency: int | None = Field(default=None, ge=1, le=32)
    crawl_delay_seconds: float | None = Field(default=None, ge=0, le=60)
    overall_concurrency: int | None = Field(default=None, ge=1, le=128)
    desktop_viewport: Viewport | None = None
    mobile_viewport: Viewport | None = None
    allowed_content_types: tuple[str, ...] | None = None
    include_url_patterns: tuple[str, ...] | None = None
    exclude_url_patterns: tuple[str, ...] | None = None
    timeout_limits: ScanTimeoutLimits | None = None
    artifact_retention_policy: ArtifactRetentionPolicy | None = None

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        return None if value is None else ScanCampaignCreateRequest.strip_name(value)

    @field_validator("authorization_attested_at")
    @classmethod
    def validate_optional_attestation(cls, value: datetime | None) -> datetime | None:
        return None if value is None else CampaignConfiguration.validate_attestation(value)

    @field_validator("allowed_content_types")
    @classmethod
    def validate_optional_types(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return None if value is None else CampaignConfiguration.validate_content_types(value)

    @field_validator("include_url_patterns", "exclude_url_patterns")
    @classmethod
    def validate_optional_globs(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return None if value is None else CampaignConfiguration.validate_url_globs(value)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.model_fields_set == {"version"}:
            raise ValueError("At least one campaign field must be supplied.")
        if any(
            field != "version" and getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("Updated campaign fields must not be null.")
        return self


class CampaignActionRequest(ScanModel):
    version: int = Field(ge=1)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class CampaignVersionRequest(ScanModel):
    version: int = Field(ge=1)


class ScanCampaignResponse(CampaignConfiguration):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    status: ScanCampaignStatus
    workflow_id: str | None
    workflow_run_id: str | None
    workflow_attempt: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class ScanTargetCreateRequest(ScanModel):
    url: str = Field(min_length=1, max_length=2_048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        normalized, _ = normalize_public_scan_url(value)
        return normalized


class ScanTargetResponse(ScanModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    campaign_id: UUID
    url: str
    normalized_url: str
    source_domain: str
    status: ScanTargetStatus
    created_at: datetime
    updated_at: datetime
    version: int


class ScanTargetImportResponse(ScanModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    campaign_id: UUID
    source_type: TargetImportSource
    filename: str | None
    media_type: str
    dry_run: bool
    authorization_attested_at: datetime
    allow_ip_literals: bool
    status: TargetImportStatus
    total_rows: int
    processed_rows: int
    accepted_count: int
    duplicate_count: int
    invalid_count: int
    blocked_count: int
    already_present_count: int
    committed_count: int
    committed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class ScanTargetImportRowResponse(ScanModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    import_id: UUID
    row_number: int
    raw_value: str
    normalized_url: str | None
    source_domain: str | None
    metadata: dict[str, object] = Field(validation_alias="row_metadata")
    outcome: TargetImportOutcome
    reason_code: str | None
    reason_message: str | None
    target_id: UUID | None
    created_at: datetime


class ScanTargetImportCommitRequest(ScanModel):
    version: int = Field(ge=1)
    authorization_attested: Literal[True]


class CrawlPageResponse(ScanModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    campaign_id: UUID
    target_id: UUID
    parent_page_id: UUID | None
    url: str
    normalized_url: str
    source_domain: str
    depth: int
    status: CrawlPageStatus
    robots_allowed: bool | None
    http_status: int | None
    content_type: str | None
    content_sha256: str | None
    discovered_at: datetime
    fetched_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class PageScanResponse(ScanModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    crawl_page_id: UUID
    viewport: Literal["desktop", "mobile"]
    viewport_width: int
    viewport_height: int
    attempt: int
    status: PageScanStatus
    started_at: datetime | None
    completed_at: datetime | None


class CrawlPageWithScansResponse(CrawlPageResponse):
    page_scans: tuple[PageScanResponse, ...] = ()


class ScanFailureResponse(ScanModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    campaign_id: UUID
    target_id: UUID | None
    crawl_page_id: UUID | None
    page_scan_id: UUID | None
    stage: FailureStage
    error_code: str
    message: str
    retryable: bool
    attempt: int
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class ScanCampaignSummaryResponse(ScanModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign: ScanCampaignResponse
    target_counts: dict[str, int]
    page_counts: dict[str, int]
    page_scan_counts: dict[str, int]
    failure_count: int
    retryable_failure_count: int
    unresolved_failure_count: int


class CampaignListParams(PaginationParams):
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None
    status: Annotated[ScanCampaignStatus | None, Query()] = None
    sort_by: Annotated[CampaignSort, Query()] = "updated_at"
    sort_order: Annotated[SortOrder, Query()] = "desc"


class ScanItemListParams(PaginationParams):
    status: str | None = None


class FailureListParams(PaginationParams):
    stage: FailureStage | None = None
    retryable: bool | None = None
    unresolved_only: bool = False


def normalize_public_scan_url(value: str) -> tuple[str, str]:
    """Normalize a seed URL and reject statically identifiable SSRF destinations."""
    if any(ord(character) < 32 for character in value) or "\\" in value:
        raise ValueError("Scan URL contains forbidden characters.")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("Scan URL must be a credential-free HTTP(S) URL without a fragment.")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Scan URL port is invalid.") from error
    if port is not None and port not in {80, 443}:
        raise ValueError("Scan URL port is not allowed.")
    hostname = parsed.hostname.rstrip(".").casefold()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise ValueError("Scan URL hostname is invalid.") from error
        if (
            hostname == "localhost"
            or hostname.endswith((".localhost", ".local", ".internal"))
            or "." not in hostname
            or any(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                for label in hostname.split(".")
            )
        ):
            raise ValueError("Scan URL hostname is not publicly routable.") from None
    else:
        if not address.is_global:
            raise ValueError("Scan URL IP address is not publicly routable.")
        hostname = address.compressed
    rendered_hostname = f"[{hostname}]" if ":" in hostname else hostname
    default_port = (parsed.scheme == "http" and port in {None, 80}) or (
        parsed.scheme == "https" and port in {None, 443}
    )
    netloc = rendered_hostname if default_port else f"{rendered_hostname}:{port}"
    path = parsed.path or "/"
    normalized = urlunsplit(SplitResult(parsed.scheme, netloc, path, parsed.query, ""))
    if len(normalized) > 2_048:
        raise ValueError("Scan URL exceeds the maximum normalized length.")
    return normalized, hostname
