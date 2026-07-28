"""Strict worker-local contracts for bounded visual page analysis."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from platform_schemas import (
    ANALYSIS_SCHEMA_VERSION,
    AccessibilityObservation,
    DesignTokens,
    PageProfile,
    PageType,
    ResponsiveBehavior,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PAGE_ANALYSIS_PROMPT_VERSION: Literal["page-analysis-v1"] = "page-analysis-v1"
PAGE_ANALYZER_VERSION: Literal["dspy-page-analyzer-v1"] = "dspy-page-analyzer-v1"
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"


class AnalysisContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ViewportMetadata(AnalysisContract):
    width: int = Field(ge=240, le=4096)
    height: int = Field(ge=240, le=2160)
    document_height: int = Field(ge=1, le=50_000)


class PageAnalysisSource(AnalysisContract):
    """Identifier-only source metadata; URLs, titles, and source copy are excluded."""

    project_id: UUID
    campaign_id: UUID
    source_website_id: UUID
    source_page_id: UUID
    desktop_page_scan_id: UUID
    mobile_page_scan_id: UUID | None = None
    page_type: PageType
    language: str | None = Field(default=None, max_length=35)
    scanner_version: str = Field(min_length=1, max_length=100)
    extractor_version: str = Field(min_length=1, max_length=100)
    desktop_viewport: ViewportMetadata
    mobile_viewport: ViewportMetadata | None = None

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        if value is not None and _LANGUAGE.fullmatch(value) is None:
            raise ValueError("language must be a bounded BCP 47-style tag")
        return value

    @model_validator(mode="after")
    def validate_mobile_pair(self) -> Self:
        if (self.mobile_page_scan_id is None) != (self.mobile_viewport is None):
            raise ValueError("mobile scan ID and viewport must be supplied together")
        return self


class PageAnalysisRequest(AnalysisContract):
    source: PageAnalysisSource
    compact_semantic_snapshot: dict[str, object]
    deterministic_style_summary: dict[str, object]
    structural_section_candidates: tuple[dict[str, object], ...] = Field(max_length=256)
    desktop_screenshot: bytes
    mobile_screenshot: bytes | None = None

    @field_validator("compact_semantic_snapshot")
    @classmethod
    def validate_snapshot_size(cls, value: dict[str, object]) -> dict[str, object]:
        _validate_json_size(value, maximum=2 * 1024 * 1024, label="semantic snapshot")
        return value

    @field_validator("deterministic_style_summary")
    @classmethod
    def validate_style_size(cls, value: dict[str, object]) -> dict[str, object]:
        _validate_json_size(value, maximum=512 * 1024, label="style summary")
        return value

    @field_validator("structural_section_candidates")
    @classmethod
    def validate_section_candidate_size(
        cls, value: tuple[dict[str, object], ...]
    ) -> tuple[dict[str, object], ...]:
        _validate_json_size(value, maximum=512 * 1024, label="section candidates")
        return value

    @field_validator("desktop_screenshot", "mobile_screenshot")
    @classmethod
    def validate_screenshot(cls, value: bytes | None) -> bytes | None:
        if value is None:
            return None
        if not value or len(value) > 10 * 1024 * 1024:
            raise ValueError("screenshot must be between 1 byte and 10 MiB")
        if not (value.startswith(_PNG) or value.startswith(_JPEG)):
            raise ValueError("screenshot must be PNG or JPEG data")
        return value

    @model_validator(mode="after")
    def validate_mobile_inputs(self) -> Self:
        if (self.source.mobile_page_scan_id is None) != (self.mobile_screenshot is None):
            raise ValueError("mobile screenshot must match the source mobile scan")
        total = len(self.desktop_screenshot) + len(self.mobile_screenshot or b"")
        if total > 20 * 1024 * 1024:
            raise ValueError("combined screenshots exceed 20 MiB")
        return self


class UncertaintyNote(AnalysisContract):
    """Controlled uncertainty signal that cannot contain copied source prose."""

    category: Literal[
        "structure", "design-tokens", "responsive", "accessibility", "image-evidence", "unknown"
    ]
    code: Literal[
        "insufficient-evidence",
        "conflicting-viewports",
        "ambiguous-section-boundary",
        "low-contrast-estimate",
        "cropped-content",
        "missing-mobile-capture",
        "deterministic-model-disagreement",
        "unknown",
    ]
    section_orders: tuple[int, ...] = Field(default=(), max_length=16)

    @field_validator("section_orders")
    @classmethod
    def validate_orders(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value < 0 or value > 255 for value in values):
            raise ValueError("uncertainty section orders are outside bounds")
        if tuple(sorted(set(values))) != values:
            raise ValueError("uncertainty section orders must be unique and ascending")
        return values


class PageAnalysisPayload(AnalysisContract):
    """Single schema-valid model result with consistent denormalized observations."""

    schema_version: Literal[1] = ANALYSIS_SCHEMA_VERSION
    page_profile: PageProfile
    design_tokens: DesignTokens
    responsive_observations: tuple[ResponsiveBehavior, ...] = Field(default=(), max_length=128)
    accessibility_observations: tuple[AccessibilityObservation, ...] = Field(
        default=(), max_length=100
    )
    uncertainty_notes: tuple[UncertaintyNote, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_projection_consistency(self) -> Self:
        responsive = tuple(
            observation
            for section in self.page_profile.sections
            for observation in section.responsive_behaviors
        )
        if responsive != self.responsive_observations:
            raise ValueError("responsive observations must match the ordered page sections")
        if self.page_profile.accessibility_observations != self.accessibility_observations:
            raise ValueError("accessibility observations must match the page profile")
        return self


class AnalyzerStrategy(StrEnum):
    DSPY = "dspy"
    DIRECT_OLLAMA = "direct-ollama"


class AnalysisRunMetadata(AnalysisContract):
    prompt_version: Literal["page-analysis-v1"] = PAGE_ANALYSIS_PROMPT_VERSION
    analyzer_version: Literal["dspy-page-analyzer-v1"] = PAGE_ANALYZER_VERSION
    schema_version: Literal[1] = ANALYSIS_SCHEMA_VERSION
    strategy: AnalyzerStrategy
    model_name: str = Field(min_length=1, max_length=200)
    model_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    latency_ms: float = Field(ge=0)
    attempts: int = Field(ge=1, le=5)
    fallback_reason: str | None = Field(default=None, max_length=160)


class PageAnalysisResult(AnalysisContract):
    payload: PageAnalysisPayload
    metadata: AnalysisRunMetadata


class DspyVisionCapability(AnalysisContract):
    model_installed: bool
    model_advertises_vision: bool
    dspy_image_api_available: bool
    structured_output_api_available: bool
    transport_verified: bool
    usable: bool
    reason: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_usable(self) -> Self:
        required = (
            self.model_installed,
            self.model_advertises_vision,
            self.dspy_image_api_available,
            self.structured_output_api_available,
            self.transport_verified,
        )
        if self.usable != all(required):
            raise ValueError("usable capability must reflect every required capability")
        if self.usable == (self.reason is not None):
            raise ValueError("capability reason must be present only when unusable")
        return self


class InputCompactionReport(AnalysisContract):
    semantic_nodes_received: int = Field(ge=0)
    semantic_nodes_retained: int = Field(ge=0)
    sections_received: int = Field(ge=0)
    sections_retained: int = Field(ge=0)
    prompt_bytes: int = Field(ge=1, le=196_608)
    truncated: bool


def _validate_json_size(value: object, *, maximum: int, label: str) -> None:
    try:
        encoded = json.dumps(
            value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must contain finite JSON data") from error
    if len(encoded) > maximum:
        raise ValueError(f"{label} exceeds its input byte limit")
