"""Typed browser capture configuration, observations, and failures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from uuid import UUID

CAPTURE_SCHEMA_VERSION = 1


class ViewportName(StrEnum):
    DESKTOP = "desktop"
    MOBILE = "mobile"


class BrowserFailureCode(StrEnum):
    PAGE_NOT_ELIGIBLE = "page_not_eligible"
    NAVIGATION_BLOCKED = "navigation_blocked"
    NAVIGATION_TIMEOUT = "navigation_timeout"
    NAVIGATION_FAILED = "navigation_failed"
    CONTENT_TYPE_BLOCKED = "content_type_blocked"
    RENDERED_HTML_TOO_LARGE = "rendered_html_too_large"
    PAGE_DIMENSIONS_TOO_LARGE = "page_dimensions_too_large"
    SCREENSHOT_TOO_LARGE = "screenshot_too_large"
    BROWSER_CRASHED = "browser_crashed"
    ARTIFACT_PERSISTENCE_FAILED = "artifact_persistence_failed"
    CAPTURE_FAILED = "capture_failed"


class BrowserScanError(RuntimeError):
    """Sanitized typed error safe to persist without hostile page content."""

    def __init__(self, code: BrowserFailureCode, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class BrowserViewport:
    name: ViewportName
    width: int
    height: int
    is_mobile: bool
    device_scale_factor: float = 1.0

    def __post_init__(self) -> None:
        if not 240 <= self.width <= 3_840 or not 240 <= self.height <= 2_160:
            raise ValueError("browser viewport dimensions are outside safe bounds")
        if not 1 <= self.device_scale_factor <= 2:
            raise ValueError("device scale factor must be between 1 and 2")


@dataclass(frozen=True, slots=True)
class BrowserCaptureLimits:
    navigation_timeout_seconds: float = 45.0
    total_timeout_seconds: float = 60.0
    stabilization_seconds: float = 3.0
    maximum_page_height: int = 16_000
    maximum_page_width: int = 4_096
    maximum_html_bytes: int = 5 * 1_024 * 1_024
    maximum_screenshot_bytes: int = 32 * 1_024 * 1_024
    maximum_resource_bytes: int = 10 * 1_024 * 1_024

    def __post_init__(self) -> None:
        if not 5 <= self.navigation_timeout_seconds <= 300:
            raise ValueError("navigation timeout must be between 5 and 300 seconds")
        if not self.navigation_timeout_seconds <= self.total_timeout_seconds <= 300:
            raise ValueError("total timeout must cover navigation and be at most 300 seconds")
        if not 0.25 <= self.stabilization_seconds <= 10:
            raise ValueError("stabilization timeout must be between 0.25 and 10 seconds")
        if not 1_000 <= self.maximum_page_height <= 50_000:
            raise ValueError("maximum page height is outside safe bounds")
        if not 320 <= self.maximum_page_width <= 8_192:
            raise ValueError("maximum page width is outside safe bounds")


@dataclass(frozen=True, slots=True)
class BrowserScanConfiguration:
    campaign_id: UUID
    project_id: UUID
    target_id: UUID
    crawl_page_id: UUID
    url: str
    source_content_sha256: str | None
    retention_days: int
    viewports: tuple[BrowserViewport, ...]
    limits: BrowserCaptureLimits

    def configuration_hash(self, viewport: BrowserViewport) -> str:
        body = {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "campaign_id": str(self.campaign_id),
            "crawl_page_id": str(self.crawl_page_id),
            "url": self.url,
            "source_content_sha256": self.source_content_sha256,
            "viewport": asdict(viewport),
            "limits": asdict(self.limits),
        }
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DocumentDimensions:
    width: int
    height: int
    screenshot_width: int
    screenshot_height: int
    full_page_truncated: bool


@dataclass(frozen=True, slots=True)
class BrowserCapture:
    final_url: str
    rendered_html: str
    full_page_screenshot: bytes
    viewport_screenshot: bytes
    response_metadata: dict[str, str | int | bool | None]
    title: str
    meta_description: str | None
    canonical_url: str | None
    language: str | None
    visible_text_summary: str
    console_errors: tuple[str, ...]
    page_errors: tuple[str, ...]
    failed_requests: tuple[dict[str, str], ...]
    external_hosts: tuple[str, ...]
    dimensions: DocumentDimensions
    browser_version: str


@dataclass(frozen=True, slots=True)
class PreparedPageScan:
    id: UUID
    viewport: BrowserViewport
    configuration_hash: str
    already_succeeded: bool
