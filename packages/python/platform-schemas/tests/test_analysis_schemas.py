"""Versioned analysis contract, adversarial validation, and conversion tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

import pytest
from platform_schemas.analysis import (
    ANALYSIS_SCHEMA_VERSION,
    AccessibilityObservation,
    AnalysisConfidence,
    AnalysisProvenance,
    ColorToken,
    ColorTokens,
    ComponentName,
    ComponentPattern,
    CopyPurpose,
    DesignTokens,
    FontCategory,
    PageProfile,
    PageType,
    ResponsiveBehavior,
    SectionPattern,
    SectionType,
    SpacingTokens,
    StyleTag,
    TypographyTokens,
    WebsiteProfile,
)
from platform_schemas.conversion import design_tokens_from_style_summary
from platform_schemas.migrations import migrate_website_profile
from pydantic import BaseModel, ValidationError

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def confidence() -> AnalysisConfidence:
    return AnalysisConfidence(
        overall=0.8,
        structure=0.9,
        design_tokens=0.85,
        responsive_behavior=0.8,
        accessibility=0.8,
    )


def section(order: int = 0) -> SectionPattern:
    return SectionPattern(
        section_type=SectionType.HERO,
        order=order,
        copy_purpose=CopyPurpose.VALUE_PROPOSITION,
        layout="split",
        components=(
            ComponentPattern(
                component_name=ComponentName.HEADING,
                order=0,
                copy_purpose=CopyPurpose.VALUE_PROPOSITION,
                layout="block",
            ),
            ComponentPattern(
                component_name=ComponentName.BUTTON,
                order=1,
                copy_purpose=CopyPurpose.CONVERSION,
                layout="inline",
            ),
        ),
        responsive_behaviors=(
            ResponsiveBehavior(
                minimum_width_px=240,
                maximum_width_px=767,
                behavior="stack-columns",
                affected_components=(ComponentName.HEADING, ComponentName.BUTTON),
            ),
        ),
    )


def valid_profile() -> WebsiteProfile:
    page_scan_id = UUID("01941f10-7b2c-7000-8000-000000000001")
    return WebsiteProfile(
        design_tokens=DesignTokens(
            colors=ColorTokens(
                palette=(ColorToken(name="color-1", value="rgb(20, 30, 40)", frequency=20),)
            ),
            typography=TypographyTokens(
                font_families=(FontCategory.SANS_SERIF,),
                font_sizes_px=(14, 16, 32),
                font_weights=(400, 700),
                line_heights_px=(20, 24, 40),
            ),
            spacing=SpacingTokens(scale_px=(0, 8, 16, 32), radius_px=(0, 8)),
            style_tags=(StyleTag.HIGH_CONTRAST, StyleTag.SPACIOUS),
        ),
        pages=(
            PageProfile(
                source_page_id=UUID("01941f10-7b2c-7000-8000-000000000002"),
                page_type=PageType.HOMEPAGE,
                sections=(section(),),
                accessibility_observations=(
                    AccessibilityObservation(
                        category="landmarks",
                        code="positive-observation",
                        severity="positive",
                        affected_count=3,
                        confidence=0.9,
                    ),
                ),
                confidence=confidence(),
            ),
        ),
        confidence=confidence(),
        provenance=AnalysisProvenance(
            source_website_id=UUID("01941f10-7b2c-7000-8000-000000000003"),
            campaign_id=UUID("01941f10-7b2c-7000-8000-000000000004"),
            page_scan_ids=(page_scan_id,),
            artifact_sha256={"style-summary": "a" * 64},
            scanner_version="browser-worker/1",
            extractor_version="browser-semantic-v1",
            analyzer_version="analysis-schema-v1",
            analyzed_at=NOW,
            deterministic_only=True,
        ),
    )


def test_valid_profile_is_versioned_and_contains_only_abstract_patterns() -> None:
    profile = valid_profile()

    assert profile.schema_version == ANALYSIS_SCHEMA_VERSION
    assert profile.pages[0].sections[0].copy_purpose is CopyPurpose.VALUE_PROPOSITION
    dumped = profile.model_dump(mode="json")
    assert not (
        {"brand_name", "customer_names", "logo_data", "source_assets", "source_copy"} & set(dumped)
    )


def test_section_registry_is_closed_and_contains_the_initial_supported_types() -> None:
    assert {item.value for item in SectionType} == {
        "header",
        "navigation",
        "hero",
        "logo-cloud",
        "features",
        "services",
        "stats",
        "content",
        "gallery",
        "testimonials",
        "case-studies",
        "pricing",
        "comparison",
        "faq",
        "cta",
        "contact",
        "footer",
        "unknown",
    }


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ColorToken, {"name": "Primary Brand", "value": "url(javascript:alert(1))"}),
        (ColorToken, {"name": "color-1", "value": "rgb(999, 0, 0)"}),
        (
            ComponentPattern,
            {"component_name": "script", "order": 0, "copy_purpose": "conversion"},
        ),
        (
            ResponsiveBehavior,
            {
                "minimum_width_px": 1200,
                "maximum_width_px": 400,
                "behavior": "stack-columns",
            },
        ),
        (
            AnalysisConfidence,
            {
                "overall": 1.1,
                "structure": 1,
                "design_tokens": 1,
                "responsive_behavior": 1,
                "accessibility": 1,
            },
        ),
    ],
)
def test_invalid_colors_dimensions_confidence_and_components_are_rejected(
    model: type[BaseModel], payload: dict[str, object]
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        model.model_validate(payload)


def test_oversized_and_noncontiguous_results_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ColorTokens(
            palette=tuple(
                ColorToken(name=f"color-{index}", value="#112233") for index in range(1, 26)
            )
        )
    with pytest.raises(ValidationError, match="contiguous"):
        PageProfile(
            source_page_id=UUID(int=1),
            page_type=PageType.ABOUT,
            sections=(section(order=1),),
            confidence=confidence(),
        )
    page = valid_profile().pages[0]
    with pytest.raises(ValidationError):
        WebsiteProfile(
            design_tokens=valid_profile().design_tokens,
            pages=tuple(
                page.model_copy(update={"source_page_id": UUID(int=index + 1)})
                for index in range(101)
            ),
            confidence=confidence(),
            provenance=valid_profile().provenance,
        )


@pytest.mark.parametrize(
    "forbidden_field", ["brand_name", "logo_data", "source_assets", "source_copy"]
)
def test_adversarial_source_identity_and_copy_fields_are_forbidden(forbidden_field: str) -> None:
    payload = valid_profile().model_dump(mode="json")
    payload[forbidden_field] = "ACME customer quote <script>alert(1)</script>"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WebsiteProfile.model_validate(payload)


def test_arbitrary_brand_like_style_tags_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DesignTokens.model_validate(
            {
                "colors": {"palette": []},
                "typography": {},
                "spacing": {},
                "style_tags": ["acme-signature-style"],
            }
        )


def test_style_summary_conversion_is_deterministic_bounded_and_filters_hostile_values() -> None:
    summary = {
        "colors": [
            {"value": "url(javascript:alert(1))", "count": 100},
            {"value": "rgb(10, 20, 30)", "count": 8},
            {"value": "#ffffff", "count": 20},
            {"value": "transparent", "count": 30},
        ],
        "font_families": [{"value": "Inter, sans-serif", "count": 10}],
        "font_sizes": [{"value": "32px", "count": 2}, {"value": "16px", "count": 8}],
        "font_weights": [{"value": "700", "count": 2}, {"value": "400", "count": 8}],
        "line_heights": [{"value": "24px", "count": 8}],
        "spacing": [{"value": "16px", "count": 10}, {"value": "8px", "count": 5}],
        "radii": [{"value": "8px", "count": 4}],
    }

    first = design_tokens_from_style_summary(summary)
    second = design_tokens_from_style_summary(deepcopy(summary))

    assert first == second
    assert [token.value for token in first.colors.palette] == ["#ffffff", "rgb(10, 20, 30)"]
    assert first.typography.font_families == (FontCategory.SANS_SERIF,)
    assert "Inter" not in first.model_dump_json()
    assert list(first.typography.font_sizes_px) == [16, 32]
    assert list(first.spacing.scale_px) == [8, 16]


def test_current_migration_helper_validates_without_mutating_input() -> None:
    payload = valid_profile().model_dump(mode="json")
    original = deepcopy(payload)

    migrated = migrate_website_profile(payload)

    assert migrated == valid_profile()
    assert payload == original


@pytest.mark.parametrize(
    "model",
    [
        WebsiteProfile,
        PageProfile,
        DesignTokens,
        TypographyTokens,
        ColorTokens,
        SpacingTokens,
        SectionPattern,
        ComponentPattern,
        ResponsiveBehavior,
        AccessibilityObservation,
        AnalysisConfidence,
        AnalysisProvenance,
    ],
)
def test_every_public_schema_field_has_json_schema_documentation(
    model: type[BaseModel],
) -> None:
    fields = model.model_fields
    assert fields
    assert fields["schema_version"].default == ANALYSIS_SCHEMA_VERSION
    assert all(field.description for field in fields.values())
