"""Deterministic, privacy-preserving compaction before any model transport."""

from __future__ import annotations

import json
from dataclasses import dataclass

from platform_schemas import design_tokens_from_style_summary

from platform_ai_worker.page_analysis_models import InputCompactionReport, PageAnalysisRequest

MAX_SEMANTIC_NODES = 160
MAX_SECTIONS = 64
MAX_COUNT_ENTRIES = 64
MAX_PROMPT_BYTES = 196_608


@dataclass(frozen=True, slots=True)
class CompactedAnalysisInput:
    source_metadata: str
    semantic_snapshot: str
    design_token_baseline: str
    structural_section_candidates: str
    report: InputCompactionReport


def compact_analysis_input(request: PageAnalysisRequest) -> CompactedAnalysisInput:
    """Remove source prose/identity and bound every deterministic input collection."""

    snapshot = request.compact_semantic_snapshot
    nodes = _mapping_list(snapshot.get("nodes"))
    summary = _mapping(snapshot.get("summary"))
    semantic = {
        "extractor_version": request.source.extractor_version,
        "truncated_at_source": snapshot.get("truncated") is True,
        "summary": {
            "node_count": _count(summary.get("node_count")),
            "section_count": _count(summary.get("section_count")),
            "card_count": _count(summary.get("card_count")),
            "tag_counts": _count_map(summary.get("tag_counts")),
            "role_counts": _count_map(summary.get("role_counts")),
            "layout_counts": _count_map(summary.get("layout_counts")),
        },
        "nodes": [_compact_node(node) for node in nodes[:MAX_SEMANTIC_NODES]],
    }
    candidates = request.structural_section_candidates
    sections = [_compact_section(item) for item in candidates[:MAX_SECTIONS]]
    frequencies = _mapping(request.deterministic_style_summary.get("style_frequencies"))
    if not frequencies:
        frequencies = request.deterministic_style_summary
    baseline = design_tokens_from_style_summary(frequencies).model_dump(mode="json")
    source = request.source.model_dump(mode="json")

    source_json = _canonical(source)
    semantic_json = _canonical(semantic)
    baseline_json = _canonical(baseline)
    sections_json = _canonical(sections)
    prompt_bytes = sum(
        len(value.encode("utf-8"))
        for value in (source_json, semantic_json, baseline_json, sections_json)
    )
    if prompt_bytes > MAX_PROMPT_BYTES:
        raise ValueError("compacted deterministic analysis input exceeds 192 KiB")
    truncated = (
        len(nodes) > MAX_SEMANTIC_NODES
        or len(candidates) > MAX_SECTIONS
        or snapshot.get("truncated") is True
    )
    return CompactedAnalysisInput(
        source_metadata=source_json,
        semantic_snapshot=semantic_json,
        design_token_baseline=baseline_json,
        structural_section_candidates=sections_json,
        report=InputCompactionReport(
            semantic_nodes_received=len(nodes),
            semantic_nodes_retained=min(len(nodes), MAX_SEMANTIC_NODES),
            sections_received=len(candidates),
            sections_retained=min(len(candidates), MAX_SECTIONS),
            prompt_bytes=prompt_bytes,
            truncated=truncated,
        ),
    )


def _compact_node(node: dict[str, object]) -> dict[str, object]:
    # Deliberately omit text, aria labels, font family, image URLs, attributes, and source code.
    return _without_none(
        {
            "id": _bounded_string(node.get("id"), 32),
            "tag": _bounded_string(node.get("tag"), 16),
            "role": _bounded_string(node.get("role"), 64),
            "bounds": _bounds(node.get("bounds")),
            "visible": node.get("visible") is True,
            "display": _bounded_string(node.get("display"), 32),
            "position": _bounded_string(node.get("position"), 32),
            "layout": _layout(node.get("layout")),
            "parent_section_id": _bounded_string(node.get("parent_section_id"), 64),
            "has_image_geometry": isinstance(node.get("image"), dict),
        }
    )


def _compact_section(section: dict[str, object]) -> dict[str, object]:
    return _without_none(
        {
            "id": _bounded_string(section.get("id"), 64),
            "tag": _bounded_string(section.get("tag"), 16),
            "kind": _bounded_string(section.get("kind"), 64),
            "bounds": _bounds(section.get("bounds")),
            "parent_section_id": _bounded_string(section.get("parent_section_id"), 64),
            "node_count": _count(section.get("node_count")),
        }
    )


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items() if isinstance(key, str)}


def _mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_mapping(item) for item in value if isinstance(item, dict)]


def _count(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100_000
        else 0
    )


def _count_map(value: object) -> dict[str, int]:
    mapped = _mapping(value)
    pairs = ((key[:64], _count(item)) for key, item in mapped.items() if key and len(key) <= 128)
    return dict(sorted(pairs, key=lambda pair: pair[0])[:MAX_COUNT_ENTRIES])


def _bounds(value: object) -> dict[str, float]:
    mapped = _mapping(value)
    result: dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        item = mapped.get(key)
        if (
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and -100_000 <= item <= 100_000
        ):
            result[key] = round(float(item), 2)
    return result


def _layout(value: object) -> dict[str, str]:
    mapped = _mapping(value)
    allowed = (
        "flex_direction",
        "flex_wrap",
        "justify_content",
        "align_items",
        "gap",
        "grid_template_columns",
    )
    return {
        key: bounded
        for key in allowed
        if (bounded := _bounded_string(mapped.get(key), 96)) is not None
    }


def _bounded_string(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized[:maximum] if normalized else None


def _without_none(value: dict[str, object | None]) -> dict[str, object]:
    return {key: item for key, item in value.items() if item is not None}


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
