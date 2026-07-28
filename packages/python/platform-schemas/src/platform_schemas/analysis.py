"""Strict v1 contracts for abstract, non-source-reproducing website analysis."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

ANALYSIS_SCHEMA_VERSION: Literal[1] = 1
_TOKEN_NAME = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")
_FUNCTION_COLOR = re.compile(r"^(?:rgb|rgba|hsl|hsla)\([0-9.,%+\-\s]+\)$", re.IGNORECASE)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

TokenName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
    ),
]


class AnalysisModel(BaseModel):
    """Strict immutable base used at the model-output trust boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class VersionedAnalysisModel(AnalysisModel):
    """Shared v1 marker for every public normalized-analysis schema."""

    schema_version: Literal[1] = Field(
        default=ANALYSIS_SCHEMA_VERSION, description="Normalized analysis schema version."
    )


class SectionType(StrEnum):
    """Controlled section registry accepted by deterministic rendering and retrieval."""

    HEADER = "header"
    NAVIGATION = "navigation"
    HERO = "hero"
    LOGO_CLOUD = "logo-cloud"
    FEATURES = "features"
    SERVICES = "services"
    STATS = "stats"
    CONTENT = "content"
    GALLERY = "gallery"
    TESTIMONIALS = "testimonials"
    CASE_STUDIES = "case-studies"
    PRICING = "pricing"
    COMPARISON = "comparison"
    FAQ = "faq"
    CTA = "cta"
    CONTACT = "contact"
    FOOTER = "footer"
    UNKNOWN = "unknown"


class ComponentName(StrEnum):
    """Controlled abstract component vocabulary; never executable component source."""

    NAV_LINK = "nav-link"
    HEADING = "heading"
    BODY_COPY = "body-copy"
    BUTTON = "button"
    BADGE = "badge"
    CARD = "card"
    STATISTIC = "statistic"
    FEATURE_ITEM = "feature-item"
    SERVICE_ITEM = "service-item"
    MEDIA_PLACEHOLDER = "media-placeholder"
    GALLERY_GRID = "gallery-grid"
    TESTIMONIAL_CARD = "testimonial-card"
    CASE_STUDY_CARD = "case-study-card"
    PRICING_TIER = "pricing-tier"
    COMPARISON_TABLE = "comparison-table"
    ACCORDION = "accordion"
    CONTACT_FORM = "contact-form"
    LINK_LIST = "link-list"
    UNKNOWN = "unknown"


class CopyPurpose(StrEnum):
    """Abstract communication goal used instead of source website text."""

    IDENTITY = "identity"
    NAVIGATION = "navigation"
    VALUE_PROPOSITION = "value-proposition"
    BUILD_TRUST = "build-trust"
    EXPLAIN_BENEFITS = "explain-benefits"
    DESCRIBE_SERVICES = "describe-services"
    QUANTIFY_OUTCOMES = "quantify-outcomes"
    EDITORIAL_CONTENT = "editorial-content"
    SHOWCASE_WORK = "showcase-work"
    SOCIAL_PROOF = "social-proof"
    COMPARE_OPTIONS = "compare-options"
    ANSWER_OBJECTIONS = "answer-objections"
    CONVERSION = "conversion"
    CONTACT = "contact"
    LEGAL_NAVIGATION = "legal-navigation"
    UNKNOWN = "unknown"


class PageType(StrEnum):
    HOMEPAGE = "homepage"
    ABOUT = "about"
    SERVICES = "services"
    PRODUCT = "product"
    FEATURES = "features"
    PRICING = "pricing"
    CONTACT = "contact"
    DOCUMENTATION = "documentation"
    BLOG_INDEX = "blog-index"
    ARTICLE = "article"
    CASE_STUDY = "case-study"
    CAREERS = "careers"
    LEGAL = "legal"
    AUTHENTICATION = "authentication"
    UNKNOWN = "unknown"


class StyleTag(StrEnum):
    """Controlled non-brand visual character vocabulary."""

    MINIMALIST = "minimalist"
    MAXIMALIST = "maximalist"
    CORPORATE = "corporate"
    EDITORIAL = "editorial"
    PLAYFUL = "playful"
    LUXURY = "luxury"
    TECHNICAL = "technical"
    ORGANIC = "organic"
    GEOMETRIC = "geometric"
    MONOCHROME = "monochrome"
    COLORFUL = "colorful"
    HIGH_CONTRAST = "high-contrast"
    MUTED = "muted"
    SPACIOUS = "spacious"
    DENSE = "dense"
    ROUNDED = "rounded"
    SHARP = "sharp"
    FLAT = "flat"
    LAYERED = "layered"
    UNKNOWN = "unknown"


class FontCategory(StrEnum):
    """Abstract font classification that cannot carry a source-specific family name."""

    SYSTEM_SANS = "system-sans"
    SANS_SERIF = "sans-serif"
    SERIF = "serif"
    MONOSPACE = "monospace"
    CURSIVE = "cursive"
    DISPLAY = "display"
    UNKNOWN = "unknown"


class ColorToken(AnalysisModel):
    """One normalized color candidate with a registry-safe token name."""

    name: TokenName = Field(description="Stable kebab-case token name, never a brand label.")
    value: str = Field(
        min_length=4,
        max_length=64,
        description="Validated hexadecimal, RGB(A), or HSL(A) CSS color value.",
    )
    frequency: int = Field(
        default=1,
        ge=1,
        le=100_000,
        description="Number of deterministic extraction observations supporting the token.",
    )

    @field_validator("value")
    @classmethod
    def validate_color(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not (
            _HEX_COLOR.fullmatch(normalized)
            or (_FUNCTION_COLOR.fullmatch(normalized) and _function_color_in_range(normalized))
        ):
            raise ValueError("color must be hexadecimal, RGB(A), or HSL(A)")
        return normalized.casefold() if normalized.startswith("#") else normalized


class ColorTokens(VersionedAnalysisModel):
    """Bounded palette inferred from rendered style frequencies."""

    palette: tuple[ColorToken, ...] = Field(
        default=(), max_length=24, description="Ordered palette candidates, most frequent first."
    )

    @model_validator(mode="after")
    def validate_unique_ordered_palette(self) -> Self:
        _unique_names(item.name for item in self.palette)
        _nonincreasing((item.frequency for item in self.palette), "color frequency")
        return self


class TypographyTokens(VersionedAnalysisModel):
    """Abstract typography scale without copied text or brand identity."""

    font_families: tuple[FontCategory, ...] = Field(
        default=(),
        max_length=8,
        description="Ordered generic font categories inferred from computed styles.",
    )
    font_sizes_px: tuple[float, ...] = Field(
        default=(),
        max_length=20,
        description="Unique positive font sizes in ascending CSS-pixel order.",
    )
    font_weights: tuple[int, ...] = Field(
        default=(),
        max_length=12,
        description="Unique numeric font weights in ascending order.",
    )
    line_heights_px: tuple[float, ...] = Field(
        default=(),
        max_length=20,
        description="Unique positive line heights in ascending CSS-pixel order.",
    )

    @field_validator("font_families")
    @classmethod
    def validate_families(cls, values: tuple[FontCategory, ...]) -> tuple[FontCategory, ...]:
        if len(values) != len(set(values)):
            raise ValueError("font categories must be unique")
        return values

    @field_validator("font_sizes_px", "line_heights_px")
    @classmethod
    def validate_dimensions(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        _bounded_ascending(values, minimum=1, maximum=512, label="typography dimension")
        return values

    @field_validator("font_weights")
    @classmethod
    def validate_weights(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        _bounded_ascending(values, minimum=1, maximum=1000, label="font weight")
        return values


class SpacingTokens(VersionedAnalysisModel):
    """Positive spacing and shape dimensions normalized to CSS pixels."""

    scale_px: tuple[float, ...] = Field(
        default=(), max_length=24, description="Unique ascending spacing values in CSS pixels."
    )
    radius_px: tuple[float, ...] = Field(
        default=(), max_length=16, description="Unique ascending border radii in CSS pixels."
    )

    @field_validator("scale_px")
    @classmethod
    def validate_scale(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        _bounded_ascending(values, minimum=0, maximum=2048, label="spacing")
        return values

    @field_validator("radius_px")
    @classmethod
    def validate_radii(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        _bounded_ascending(values, minimum=0, maximum=1024, label="radius")
        return values


class DesignTokens(VersionedAnalysisModel):
    """Deterministic visual token projection shared across analyzed pages."""

    colors: ColorTokens = Field(description="Normalized color palette candidates.")
    typography: TypographyTokens = Field(description="Normalized typography scale.")
    spacing: SpacingTokens = Field(description="Normalized spacing and radius scales.")
    style_tags: tuple[StyleTag, ...] = Field(
        default=(), max_length=24, description="Abstract, non-brand visual style categories."
    )

    @field_validator("style_tags")
    @classmethod
    def validate_style_tags(cls, values: tuple[StyleTag, ...]) -> tuple[StyleTag, ...]:
        if len(values) != len(set(values)):
            raise ValueError("style tag values must be unique")
        return values


class ComponentPattern(VersionedAnalysisModel):
    """Abstract registered component occurrence, never source code or executable markup."""

    component_name: ComponentName = Field(description="Controlled component registry name.")
    order: int = Field(ge=0, le=255, description="Zero-based order within its parent section.")
    copy_purpose: CopyPurpose = Field(description="Communication purpose instead of source copy.")
    repeat_count: int = Field(
        default=1, ge=1, le=100, description="Observed bounded repetition count."
    )
    layout: Literal["block", "inline", "flex-row", "flex-column", "grid", "overlay", "unknown"] = (
        Field(default="unknown", description="Controlled abstract layout mode.")
    )


class ResponsiveBehavior(VersionedAnalysisModel):
    """Observed layout changes across bounded viewport ranges."""

    minimum_width_px: int = Field(
        ge=240, le=7680, description="Inclusive lower viewport width for this behavior."
    )
    maximum_width_px: int = Field(
        ge=240, le=7680, description="Inclusive upper viewport width for this behavior."
    )
    behavior: Literal[
        "stack-columns",
        "collapse-navigation",
        "wrap-items",
        "reduce-spacing",
        "resize-type",
        "hide-secondary-content",
        "preserve-layout",
        "unknown",
    ] = Field(description="Controlled responsive transformation category.")
    affected_components: tuple[ComponentName, ...] = Field(
        default=(), max_length=24, description="Controlled components affected by the change."
    )

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.minimum_width_px > self.maximum_width_px:
            raise ValueError("responsive width range must be ordered")
        if len(self.affected_components) != len(set(self.affected_components)):
            raise ValueError("affected components must be unique")
        return self


class AccessibilityObservation(VersionedAnalysisModel):
    """Sanitized accessibility finding described through controlled codes."""

    category: Literal[
        "landmarks", "headings", "contrast", "forms", "images", "keyboard", "motion", "unknown"
    ] = Field(description="Controlled accessibility review category.")
    code: Literal[
        "missing-landmark",
        "heading-order",
        "contrast-risk",
        "missing-form-label",
        "missing-alt-purpose",
        "focus-risk",
        "motion-risk",
        "positive-observation",
        "unknown",
    ] = Field(description="Stable observation code without copied page content.")
    severity: Literal["positive", "info", "warning", "error"] = Field(
        description="Review severity; it is not a conformance certification."
    )
    affected_count: int = Field(
        default=1, ge=1, le=10_000, description="Number of deterministic observations."
    )
    confidence: float = Field(
        ge=0, le=1, description="Confidence from zero to one for this observation."
    )


class SectionPattern(VersionedAnalysisModel):
    """Ordered abstract page section using only controlled pattern vocabularies."""

    section_type: SectionType = Field(description="Controlled section registry type.")
    order: int = Field(ge=0, le=255, description="Zero-based page section order.")
    copy_purpose: CopyPurpose = Field(description="Abstract copy goal, never copied source text.")
    layout: Literal[
        "single-column",
        "two-column",
        "three-column",
        "multi-column",
        "grid",
        "split",
        "overlay",
        "unknown",
    ] = Field(description="Controlled high-level section layout.")
    components: tuple[ComponentPattern, ...] = Field(
        default=(), max_length=64, description="Ordered controlled component patterns."
    )
    responsive_behaviors: tuple[ResponsiveBehavior, ...] = Field(
        default=(), max_length=16, description="Ordered non-overlapping responsive behaviors."
    )

    @model_validator(mode="after")
    def validate_ordering(self) -> Self:
        _contiguous_order((item.order for item in self.components), "component")
        previous_max = 0
        for index, behavior in enumerate(self.responsive_behaviors):
            if index and behavior.minimum_width_px <= previous_max:
                raise ValueError("responsive behavior ranges must be ordered and non-overlapping")
            previous_max = behavior.maximum_width_px
        return self


class AnalysisConfidence(VersionedAnalysisModel):
    """Explicit confidence values for independently reviewable analysis dimensions."""

    overall: float = Field(ge=0, le=1, description="Overall normalized confidence.")
    structure: float = Field(ge=0, le=1, description="Section and component confidence.")
    design_tokens: float = Field(ge=0, le=1, description="Visual token confidence.")
    responsive_behavior: float = Field(ge=0, le=1, description="Responsive inference confidence.")
    accessibility: float = Field(ge=0, le=1, description="Accessibility observation confidence.")

    @model_validator(mode="after")
    def validate_overall(self) -> Self:
        dimensions = (
            self.structure,
            self.design_tokens,
            self.responsive_behavior,
            self.accessibility,
        )
        if self.overall > max(dimensions):
            raise ValueError("overall confidence cannot exceed every dimension confidence")
        return self


class AnalysisProvenance(VersionedAnalysisModel):
    """Identifier-only lineage for the deterministic and model analysis inputs."""

    source_website_id: UUID = Field(description="Database ID of the authorized source website.")
    campaign_id: UUID = Field(description="Database ID of the owning scan campaign.")
    page_scan_ids: tuple[UUID, ...] = Field(
        min_length=1,
        max_length=100,
        description="Ordered page-scan IDs used as inputs; no binary payloads are embedded.",
    )
    artifact_sha256: dict[TokenName, str] = Field(
        default_factory=dict,
        max_length=500,
        description="Artifact role to SHA-256 mapping without bucket names, keys, or URLs.",
    )
    scanner_version: str = Field(
        min_length=1, max_length=100, description="Bounded browser scanner implementation version."
    )
    extractor_version: str = Field(
        min_length=1, max_length=100, description="Bounded deterministic extractor version."
    )
    analyzer_version: str = Field(
        min_length=1, max_length=100, description="Bounded structured analyzer version."
    )
    analyzed_at: datetime = Field(description="Timezone-aware analysis completion timestamp.")
    deterministic_only: bool = Field(
        description="True when the profile was created without model inference."
    )

    @field_validator("artifact_sha256")
    @classmethod
    def validate_checksums(cls, values: dict[str, str]) -> dict[str, str]:
        if any(
            not _TOKEN_NAME.fullmatch(key) or not _SHA256.fullmatch(value)
            for key, value in values.items()
        ):
            raise ValueError("artifact checksums must use token names and lowercase SHA-256 values")
        return values

    @field_validator("analyzed_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("analysis timestamp must include a timezone")
        return value

    @field_validator("page_scan_ids")
    @classmethod
    def validate_page_scan_ids(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("page scan IDs must be unique")
        return values


class PageProfile(VersionedAnalysisModel):
    """AI-normalized page structure containing no source copy or source assets."""

    source_page_id: UUID = Field(description="Database ID of the normalized crawl page.")
    page_type: PageType = Field(description="Controlled deterministic page classification.")
    sections: tuple[SectionPattern, ...] = Field(
        min_length=1, max_length=64, description="Ordered abstract section patterns."
    )
    accessibility_observations: tuple[AccessibilityObservation, ...] = Field(
        default=(), max_length=100, description="Sanitized deterministic accessibility findings."
    )
    confidence: AnalysisConfidence = Field(description="Per-dimension page analysis confidence.")

    @model_validator(mode="after")
    def validate_section_order(self) -> Self:
        _contiguous_order((section.order for section in self.sections), "section")
        return self


class WebsiteProfile(VersionedAnalysisModel):
    """Versioned normalized website profile and structured model-output contract."""

    design_tokens: DesignTokens = Field(description="Cross-page normalized design tokens.")
    pages: tuple[PageProfile, ...] = Field(
        min_length=1, max_length=100, description="Bounded normalized representative pages."
    )
    confidence: AnalysisConfidence = Field(description="Aggregate website analysis confidence.")
    provenance: AnalysisProvenance = Field(
        description="Identifier-only source and artifact lineage."
    )

    @model_validator(mode="after")
    def validate_pages(self) -> Self:
        page_ids = tuple(page.source_page_id for page in self.pages)
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("website profile pages must be unique")
        if sum(page.page_type is PageType.HOMEPAGE for page in self.pages) > 1:
            raise ValueError("website profile may contain at most one homepage")
        return self


def _unique_names(values: Iterable[str]) -> None:
    names = tuple(values)
    if len(names) != len(set(names)):
        raise ValueError("token names must be unique")


def _nonincreasing(values: Iterable[int], label: str) -> None:
    items = tuple(values)
    if any(left < right for left, right in pairwise(items)):
        raise ValueError(f"{label} values must be nonincreasing")


def _bounded_ascending(
    values: tuple[float, ...] | tuple[int, ...], *, minimum: float, maximum: float, label: str
) -> None:
    if any(value < minimum or value > maximum for value in values):
        raise ValueError(f"{label} values are outside safe bounds")
    if any(left >= right for left, right in pairwise(values)):
        raise ValueError(f"{label} values must be unique and ascending")


def _contiguous_order(values: Iterable[int], label: str) -> None:
    order = tuple(values)
    if order != tuple(range(len(order))):
        raise ValueError(f"{label} order must be contiguous and zero-based")


def _function_color_in_range(value: str) -> bool:
    name, arguments = value.split("(", 1)
    parts = tuple(part.strip() for part in arguments[:-1].split(","))
    expected = 4 if name.casefold() in {"rgba", "hsla"} else 3
    if len(parts) != expected:
        return False
    try:
        if name.casefold().startswith("rgb"):
            channels = tuple(_percent_or_number(part, 255) for part in parts[:3])
        else:
            hue = float(parts[0])
            channels = (
                hue if 0 <= hue <= 360 else -1,
                _required_percent(parts[1]),
                _required_percent(parts[2]),
            )
        if any(channel < 0 for channel in channels):
            return False
        return expected == 3 or _alpha(parts[3]) >= 0
    except ValueError:
        return False


def _percent_or_number(value: str, maximum: float) -> float:
    if value.endswith("%"):
        percentage = float(value[:-1])
        return percentage if 0 <= percentage <= 100 else -1
    number = float(value)
    return number if 0 <= number <= maximum else -1


def _required_percent(value: str) -> float:
    if not value.endswith("%"):
        return -1
    percentage = float(value[:-1])
    return percentage if 0 <= percentage <= 100 else -1


def _alpha(value: str) -> float:
    if value.endswith("%"):
        percentage = float(value[:-1])
        return percentage if 0 <= percentage <= 100 else -1
    number = float(value)
    return number if 0 <= number <= 1 else -1
