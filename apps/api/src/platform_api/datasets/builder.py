"""Deterministic dataset selection, quality evaluation, splitting, and manifest creation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from platform_schemas import SectionPattern as SectionPatternSchema
from platform_schemas import WebsiteProfile as WebsiteProfileSchema
from pydantic import ValidationError

from platform_api.persistence.json import JsonValue
from platform_api.persistence.models import DatasetItem

from .repository import DatasetCandidate
from .schemas import DatasetQualityPolicy, SelectionPolicy

_INVALID_TEXT = re.compile(r"(?:https?://|www\.|<[^>]+>|\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b)", re.I)
_MANIFEST_VERSION = 2
_SPLIT_ALGORITHM = "source-domain-balanced-sha256-v2"


@dataclass(frozen=True, slots=True)
class BuildEvaluation:
    items: tuple[DatasetItem, ...]
    manifest: dict[str, JsonValue]
    manifest_sha256: str
    statistics: dict[str, JsonValue]
    findings: tuple[dict[str, JsonValue], ...]
    excluded_counts: dict[str, JsonValue]
    analyzer_versions: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.findings


def evaluate_dataset_build(
    *,
    version_id: UUID,
    candidates: tuple[DatasetCandidate, ...],
    selection: SelectionPolicy,
    quality: DatasetQualityPolicy,
    schema_version: int,
    now: datetime,
) -> BuildEvaluation:
    """Apply every policy and quality gate without external I/O."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("dataset build timestamp must include a timezone")
    excluded: Counter[str] = Counter()
    eligible: list[DatasetCandidate] = []
    seen_hashes: set[str] = set()
    duplicate_count = 0
    for candidate in candidates:
        reason = _exclusion_reason(candidate, selection, now)
        if reason is not None:
            excluded[reason] += 1
            continue
        digest = candidate.pattern_hash or _sha256(candidate.content)
        if digest in seen_hashes:
            excluded["duplicate_hash"] += 1
            duplicate_count += 1
            continue
        seen_hashes.add(digest)
        eligible.append(candidate)

    findings: list[dict[str, JsonValue]] = []
    if not eligible:
        findings.append(_finding("selection_empty", "No eligible patterns remain after filtering."))

    split_by_domain = _domain_splits(item.source_domain for item in eligible)
    items = tuple(
        _item(version_id, candidate, split_by_domain[candidate.source_domain.casefold()])
        for candidate in eligible
    )
    distributions = _distributions(eligible, items)
    domain_counts = Counter(item.source_domain.casefold() for item in eligible)
    largest_domain_share = max(domain_counts.values(), default=0) / max(len(eligible), 1)
    if largest_domain_share > quality.max_domain_share:
        findings.append(
            _finding(
                "excessive_domain_dependence",
                "One source domain exceeds the configured dataset share.",
                actual=largest_domain_share,
                limit=quality.max_domain_share,
            )
        )
    categories = {item.category.casefold() for item in eligible}
    if len(categories) < quality.minimum_category_count:
        findings.append(
            _finding(
                "low_category_diversity",
                "The dataset does not contain enough distinct categories.",
                actual=len(categories),
                minimum=quality.minimum_category_count,
            )
        )
    if len(domain_counts) < 3:
        findings.append(
            _finding(
                "insufficient_domains_for_splits",
                "At least three source domains are required to create train, validation, and test splits.",
                actual=len(domain_counts),
                minimum=3,
            )
        )
    repeated_share = duplicate_count / max(len(eligible) + duplicate_count, 1)
    if repeated_share > quality.max_repeated_template_share:
        findings.append(
            _finding(
                "repeated_templates",
                "Repeated template hashes exceed the configured share.",
                actual=repeated_share,
                limit=quality.max_repeated_template_share,
            )
        )
    section_types = set(cast(dict[str, int], distributions["section_types"]))
    missing_sections = sorted(set(quality.required_section_types) - section_types)
    if missing_sections:
        findings.append(
            _finding(
                "missing_required_section_types",
                "Required section types are missing.",
                section_types=cast(JsonValue, missing_sections),
            )
        )

    for candidate in eligible:
        if candidate.schema_version != schema_version or not _schema_valid(candidate):
            findings.append(
                _finding(
                    "schema_mismatch",
                    "A candidate does not match the requested dataset schema.",
                    source_record_id=str(candidate.source_record_id),
                )
            )
        serialized = _canonical_json(candidate.content)
        if len(serialized) > quality.maximum_serialized_text_chars:
            findings.append(
                _finding(
                    "oversized_text",
                    "A candidate exceeds the configured serialized text limit.",
                    source_record_id=str(candidate.source_record_id),
                    actual=len(serialized),
                    limit=quality.maximum_serialized_text_chars,
                )
            )
        strings = tuple(_strings(candidate.content))
        if any(_INVALID_TEXT.search(value) for value in strings):
            findings.append(
                _finding(
                    "invalid_tokens",
                    "A candidate contains a URL, markup, or email token.",
                    source_record_id=str(candidate.source_record_id),
                )
            )
        brand = candidate.source_domain.casefold().split(".")[0].replace("-", " ")
        if len(brand) >= 4 and any(brand in value.casefold() for value in strings):
            findings.append(
                _finding(
                    "copied_branding",
                    "A candidate contains source-specific branding.",
                    source_record_id=str(candidate.source_record_id),
                )
            )
        if any(_looks_like_source_copy(value) for value in strings):
            findings.append(
                _finding(
                    "source_specific_copied_text",
                    "A candidate contains prose instead of controlled abstract tokens.",
                    source_record_id=str(candidate.source_record_id),
                )
            )

    leakage = _leakage_count(items)
    if leakage:
        findings.append(
            _finding(
                "split_leakage",
                "At least one source domain appears in multiple splits.",
                count=leakage,
            )
        )
    statistics: dict[str, JsonValue] = {
        **distributions,
        "excluded": dict(sorted(excluded.items())),
        "largest_domain_share": largest_domain_share,
        "repeated_template_share": repeated_share,
        "source_domain_leakage_count": leakage,
    }
    manifest: dict[str, JsonValue] = {
        "manifest_version": _MANIFEST_VERSION,
        "split_algorithm": _SPLIT_ALGORITHM,
        "selection_policy": selection.model_dump(mode="json"),
        "quality_policy": quality.model_dump(mode="json"),
        "source_domain_splits": dict(sorted(split_by_domain.items())),
        "items": [
            {
                "item_type": item.item_type,
                "source_record_id": str(item.source_record_id),
                "content_sha256": item.content_sha256,
                "split": item.split,
            }
            for item in items
        ],
    }
    manifest_sha256 = hashlib.sha256(_canonical_json(manifest).encode()).hexdigest()
    return BuildEvaluation(
        items,
        manifest,
        manifest_sha256,
        statistics,
        tuple(_deduplicate_findings(findings)),
        dict(sorted(excluded.items())),
        tuple(sorted({item.analyzer_version for item in eligible})),
    )


def _exclusion_reason(
    candidate: DatasetCandidate, selection: SelectionPolicy, now: datetime
) -> str | None:
    if candidate.approval_state == "rejected" or (
        selection.require_approved and candidate.approval_state != "approved"
    ):
        return "rejected_or_unapproved"
    if candidate.confidence < selection.minimum_confidence:
        return "insufficient_confidence"
    if candidate.removed:
        return "removed"
    if candidate.suppressed:
        return "suppressed"
    if isinstance(candidate.expires_at, datetime) and candidate.expires_at <= now:
        return "expired"
    if candidate.provenance_state not in selection.provenance_requirements:
        return "unauthorized_provenance"
    return None


def _schema_valid(candidate: DatasetCandidate) -> bool:
    try:
        if candidate.item_type == "section_pattern":
            content = cast(dict[str, JsonValue], candidate.content)
            SectionPatternSchema.model_validate(content.get("pattern"))
        else:
            content = cast(dict[str, JsonValue], candidate.content)
            WebsiteProfileSchema.model_validate(content.get("site_profile"))
    except (ValidationError, TypeError, ValueError):
        return False
    return True


def _item(version_id: UUID, candidate: DatasetCandidate, split: str) -> DatasetItem:
    return DatasetItem(
        dataset_version_id=version_id,
        item_type=candidate.item_type,
        source_record_id=candidate.source_record_id,
        source_campaign_id=candidate.campaign_id,
        source_website_id=candidate.website_id,
        source_page_id=candidate.page_id,
        source_domain=candidate.source_domain.casefold(),
        split=split,
        category=candidate.category,
        language=candidate.language,
        confidence=candidate.confidence,
        schema_version=candidate.schema_version,
        analyzer_version=candidate.analyzer_version,
        content_snapshot=candidate.content,
        source_reference={
            "source_record_id": str(candidate.source_record_id),
            "campaign_id": str(candidate.campaign_id),
            "website_id": str(candidate.website_id),
            "page_id": None if candidate.page_id is None else str(candidate.page_id),
            "source_domain": candidate.source_domain.casefold(),
            "prompt_default": "excluded",
        },
        content_sha256=_sha256(candidate.content),
        availability_status="active",
    )


def _distributions(
    candidates: list[DatasetCandidate], items: tuple[DatasetItem, ...]
) -> dict[str, JsonValue]:
    section_types: Counter[str] = Counter()
    layouts: Counter[str] = Counter()
    styles: Counter[str] = Counter()
    for candidate in candidates:
        if candidate.item_type == "section_pattern":
            if candidate.section_type:
                section_types[candidate.section_type] += 1
            if candidate.layout:
                layouts[candidate.layout] += 1
            styles.update(candidate.style_tags)
        else:
            for key, value in _keyed_strings(candidate.content):
                if key == "section_type":
                    section_types[value] += 1
                elif key == "layout":
                    layouts[value] += 1
                elif key == "style_tags":
                    styles[value] += 1
    return {
        "item_count": len(items),
        "source_domain_count": len({item.source_domain.casefold() for item in items}),
        "splits": dict(Counter(item.split for item in items)),
        "item_types": dict(Counter(item.item_type for item in items)),
        "categories": dict(Counter(item.category for item in items)),
        "languages": dict(Counter(item.language for item in items)),
        "section_types": dict(section_types),
        "layouts": dict(layouts),
        "styles": dict(styles),
    }


def _keyed_strings(value: JsonValue, key: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for child_key, child in value.items():
            found.extend(_keyed_strings(child, child_key))
    elif isinstance(value, list):
        for child in value:
            found.extend(_keyed_strings(child, key))
    elif isinstance(value, str):
        found.append((key, value.casefold()))
    return found


def _strings(value: JsonValue) -> list[str]:
    return [item for _, item in _keyed_strings(value)]


def _looks_like_source_copy(value: str) -> bool:
    words = value.split()
    return len(words) >= 8 or len(value) > 160


def _leakage_count(items: tuple[DatasetItem, ...]) -> int:
    splits: dict[str, set[str]] = defaultdict(set)
    for item in items:
        splits[item.source_domain.casefold()].add(item.split)
    return sum(len(values) > 1 for values in splits.values())


def _domain_splits(domains: Iterable[str]) -> dict[str, str]:
    canonical = sorted(
        {value.casefold() for value in domains},
        key=lambda value: (hashlib.sha256(value.encode()).digest(), value),
    )
    count = len(canonical)
    if count == 0:
        return {}
    if count == 1:
        return {canonical[0]: "train"}
    if count == 2:
        return {canonical[0]: "train", canonical[1]: "validation"}
    test_count = max(1, count // 10)
    validation_count = max(1, count // 10)
    train_count = count - validation_count - test_count
    return {
        domain: (
            "train"
            if index < train_count
            else "validation"
            if index < train_count + validation_count
            else "test"
        )
        for index, domain in enumerate(canonical)
    }


def _finding(code: str, message: str, **details: JsonValue) -> dict[str, JsonValue]:
    return {"code": code, "message": message, **details}


def _deduplicate_findings(
    findings: list[dict[str, JsonValue]],
) -> list[dict[str, JsonValue]]:
    seen: set[str] = set()
    result: list[dict[str, JsonValue]] = []
    for finding in findings:
        key = _canonical_json(finding)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result


def _sha256(value: JsonValue) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _canonical_json(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
