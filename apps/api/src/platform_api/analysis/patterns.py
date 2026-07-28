"""Deterministic, source-independent section retrieval projections."""

from __future__ import annotations

import hashlib
import json

from platform_schemas import SectionPattern, StyleTag

PATTERN_HASH_VERSION = "section-pattern-v1"
RETRIEVAL_DOCUMENT_VERSION = "section-retrieval-v1"


def pattern_hash(pattern: SectionPattern, style_tags: tuple[StyleTag, ...]) -> str:
    """Hash controlled structure only; order and source identity intentionally do not participate."""
    value = {
        "version": PATTERN_HASH_VERSION,
        "section_type": pattern.section_type.value,
        "copy_purpose": pattern.copy_purpose.value,
        "layout": pattern.layout,
        "components": [
            {
                "name": component.component_name.value,
                "copy_purpose": component.copy_purpose.value,
                "repeat_count": component.repeat_count,
                "layout": component.layout,
            }
            for component in pattern.components
        ],
        "responsive": [
            {
                "min": item.minimum_width_px,
                "max": item.maximum_width_px,
                "behavior": item.behavior,
                "components": sorted(value.value for value in item.affected_components),
            }
            for item in pattern.responsive_behaviors
        ],
        "style_tags": sorted(tag.value for tag in style_tags),
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def retrieval_document(
    pattern: SectionPattern,
    *,
    category: str,
    language: str,
    style_tags: tuple[StyleTag, ...],
) -> str:
    """Build compact retrieval text exclusively from controlled schema values."""
    components = (
        ", ".join(
            f"{item.component_name.value}:{item.layout}:{item.copy_purpose.value}:x{item.repeat_count}"
            for item in pattern.components
        )
        or "none"
    )
    responsive = (
        ", ".join(
            f"{item.behavior}@{item.minimum_width_px}-{item.maximum_width_px}"
            for item in pattern.responsive_behaviors
        )
        or "none"
    )
    tags = ", ".join(tag.value for tag in style_tags) or "unknown"
    return (
        f"{RETRIEVAL_DOCUMENT_VERSION}; section={pattern.section_type.value}; "
        f"purpose={pattern.copy_purpose.value}; layout={pattern.layout}; category={category}; "
        f"language={language}; styles={tags}; components={components}; responsive={responsive}"
    )
