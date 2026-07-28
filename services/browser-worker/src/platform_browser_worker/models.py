"""Typed browser capture configuration, observations, and failures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CAPTURE_SCHEMA_VERSION = 2
EXTRACTOR_VERSION = "browser-semantic-v1"


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
    EXTRACTION_FAILED = "extraction_failed"
    EXTRACTION_TOO_LARGE = "extraction_too_large"
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
    maximum_extracted_nodes: int = 500
    maximum_extraction_bytes: int = 1 * 1_024 * 1_024
    maximum_node_text_characters: int = 240

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
        if not 50 <= self.maximum_extracted_nodes <= 2_000:
            raise ValueError("maximum extracted nodes must be between 50 and 2000")
        if not 64 * 1_024 <= self.maximum_extraction_bytes <= 4 * 1_024 * 1_024:
            raise ValueError("maximum extraction bytes must be between 64 KiB and 4 MiB")
        if not 40 <= self.maximum_node_text_characters <= 500:
            raise ValueError("maximum node text characters must be between 40 and 500")


@dataclass(frozen=True, slots=True)
class BrowserScanConfiguration:
    campaign_id: UUID
    project_id: UUID
    target_id: UUID
    crawl_page_id: UUID
    url: str
    source_content_sha256: str | None
    raw_response_artifact_key: str | None
    retention_days: int
    legal_hold: bool
    viewports: tuple[BrowserViewport, ...]
    limits: BrowserCaptureLimits

    def configuration_hash(self, viewport: BrowserViewport) -> str:
        body = {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "extractor_version": EXTRACTOR_VERSION,
            "campaign_id": str(self.campaign_id),
            "crawl_page_id": str(self.crawl_page_id),
            "url": self.url,
            "source_content_sha256": self.source_content_sha256,
            "raw_response_artifact_key": self.raw_response_artifact_key,
            "legal_hold": self.legal_hold,
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


class SnapshotModel(BaseModel):
    """Strict base for browser-originated data before it crosses storage boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NodeBounds(SnapshotModel):
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class NodeSpacing(SnapshotModel):
    margin_top: str
    margin_right: str
    margin_bottom: str
    margin_left: str
    padding_top: str
    padding_right: str
    padding_bottom: str
    padding_left: str


class NodeLayout(SnapshotModel):
    flex_direction: str
    flex_wrap: str
    justify_content: str
    align_items: str
    gap: str
    grid_template_columns: str
    grid_template_rows: str


class ImageDimensions(SnapshotModel):
    rendered_width: float = Field(ge=0)
    rendered_height: float = Field(ge=0)
    intrinsic_width: int = Field(ge=0)
    intrinsic_height: int = Field(ge=0)


class ExtractedNode(SnapshotModel):
    id: str = Field(pattern=r"^n-[0-9a-f]{8}(?:-[0-9]+)?$")
    tag: str = Field(max_length=16)
    role: str | None = Field(default=None, max_length=64)
    aria_label: str | None = Field(default=None, max_length=240)
    text: str = Field(max_length=500)
    bounds: NodeBounds
    visible: bool
    z_index: str = Field(max_length=32)
    display: str = Field(max_length=64)
    position: str = Field(max_length=32)
    layout: NodeLayout
    color: str = Field(max_length=64)
    background_color: str = Field(max_length=128)
    font_family: str = Field(max_length=240)
    font_size: str = Field(max_length=32)
    font_weight: str = Field(max_length=32)
    line_height: str = Field(max_length=32)
    spacing: NodeSpacing
    border: str = Field(max_length=240)
    radius: str = Field(max_length=128)
    shadow: str = Field(max_length=240)
    text_align: str = Field(max_length=32)
    image: ImageDimensions | None = None
    parent_section_id: str | None = None


class ExtractedSection(SnapshotModel):
    id: str
    tag: str = Field(max_length=16)
    kind: str = Field(max_length=64)
    bounds: NodeBounds
    parent_section_id: str | None = None
    node_count: int = Field(ge=1)


class StyleFrequency(SnapshotModel):
    value: str = Field(max_length=240)
    count: int = Field(ge=1)


class StyleFrequencies(SnapshotModel):
    colors: tuple[StyleFrequency, ...]
    font_families: tuple[StyleFrequency, ...]
    font_sizes: tuple[StyleFrequency, ...]
    font_weights: tuple[StyleFrequency, ...]
    line_heights: tuple[StyleFrequency, ...]
    spacing: tuple[StyleFrequency, ...]
    radii: tuple[StyleFrequency, ...]
    shadows: tuple[StyleFrequency, ...]
    borders: tuple[StyleFrequency, ...]


class DesignTokenCandidate(SnapshotModel):
    category: str = Field(max_length=64)
    name: str = Field(max_length=64)
    value: str = Field(max_length=240)
    count: int = Field(ge=1)


class HeadingOutlineItem(SnapshotModel):
    level: str = Field(pattern=r"^h[1-6]$")
    text: str = Field(max_length=80)


class SemanticSnapshotSummary(SnapshotModel):
    node_count: int = Field(ge=0)
    section_count: int = Field(ge=0)
    card_count: int = Field(ge=0)
    tag_counts: dict[str, int]
    role_counts: dict[str, int]
    layout_counts: dict[str, int]
    heading_outline: tuple[HeadingOutlineItem, ...]
    palette: tuple[str, ...]
    font_families: tuple[str, ...]
    spacing_scale: tuple[str, ...]


class SemanticSnapshot(SnapshotModel):
    extractor_version: str
    nodes: tuple[ExtractedNode, ...]
    sections: tuple[ExtractedSection, ...]
    style_frequencies: StyleFrequencies
    design_tokens: tuple[DesignTokenCandidate, ...]
    summary: SemanticSnapshotSummary
    truncated: bool

    @model_validator(mode="after")
    def validate_summary_counts(self) -> Self:
        if self.summary.node_count != len(self.nodes):
            raise ValueError("semantic summary node count does not match nodes")
        if self.summary.section_count != len(self.sections):
            raise ValueError("semantic summary section count does not match sections")
        if self.summary.card_count != sum(node.role == "card" for node in self.nodes):
            raise ValueError("semantic summary card count does not match nodes")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


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
    semantic_snapshot: SemanticSnapshot


@dataclass(frozen=True, slots=True)
class PreparedPageScan:
    id: UUID
    viewport: BrowserViewport
    configuration_hash: str
    already_succeeded: bool
    scan_timestamp: datetime
