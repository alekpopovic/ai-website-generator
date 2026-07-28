"""Deterministic representative-page selection with explicit explanations."""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from platform_clients.page_classification.models import (
    ManualSelection,
    PageType,
    RepresentativeCandidate,
    RepresentativeDecision,
)

SELECTOR_NAME = "diverse-page-type-template-selector"
SELECTOR_VERSION = 1

_TYPE_PRIORITY = {
    PageType.HOMEPAGE: 1_000.0,
    PageType.PRICING: 900.0,
    PageType.PRODUCT: 850.0,
    PageType.SERVICES: 800.0,
    PageType.ABOUT: 750.0,
    PageType.CONTACT: 700.0,
    PageType.FEATURES: 650.0,
    PageType.CASE_STUDY: 610.0,
    PageType.ARTICLE: 600.0,
    PageType.BLOG_INDEX: 590.0,
    PageType.DOCUMENTATION: 550.0,
    PageType.CAREERS: 400.0,
    PageType.UNKNOWN: 100.0,
    PageType.LEGAL: 20.0,
    PageType.AUTHENTICATION: 10.0,
}
_IMPORTANT_ORDER = (
    PageType.HOMEPAGE,
    PageType.PRICING,
    PageType.PRODUCT,
    PageType.SERVICES,
    PageType.ABOUT,
    PageType.CONTACT,
    PageType.FEATURES,
)
_CONTENT_TYPES = frozenset({PageType.ARTICLE, PageType.CASE_STUDY, PageType.BLOG_INDEX})
_RESTRICTED_TYPES = frozenset({PageType.LEGAL, PageType.AUTHENTICATION})


def _score(candidate: RepresentativeCandidate) -> float:
    score = _TYPE_PRIORITY[candidate.page_type] + candidate.classification_score * 50
    score += min(candidate.normalized_text_length, 5_000) / 1_000
    if candidate.exact_duplicate:
        score -= 500
    if candidate.near_duplicate:
        score -= 250
    if candidate.manual_selection is ManualSelection.INCLUDE:
        score += 10_000
    if candidate.manual_selection is ManualSelection.EXCLUDE:
        score -= 10_000
    return round(score, 4)


def select_representative_pages(
    candidates: tuple[RepresentativeCandidate, ...],
    *,
    maximum_pages: int,
    include_restricted: bool = False,
) -> tuple[RepresentativeDecision, ...]:
    """Select a page-type and template-diverse bounded set deterministically."""
    ordered = tuple(
        sorted(candidates, key=lambda item: (-_score(item), item.normalized_url, str(item.page_id)))
    )
    selected: list[RepresentativeCandidate] = []
    selected_ids: set[UUID] = set()
    template_counts: Counter[str] = Counter()
    decisions: dict[UUID, tuple[bool, str]] = {}

    def choose(candidate: RepresentativeCandidate, reason: str) -> bool:
        if len(selected) >= maximum_pages or candidate.page_id in selected_ids:
            return False
        selected.append(candidate)
        selected_ids.add(candidate.page_id)
        if candidate.template_group_key:
            template_counts[candidate.template_group_key] += 1
        decisions[candidate.page_id] = (True, reason)
        return True

    if maximum_pages > 0:
        for candidate in ordered:
            if (
                candidate.page_type is PageType.HOMEPAGE
                and candidate.manual_selection is not ManualSelection.EXCLUDE
                and not candidate.exact_duplicate
                and not candidate.near_duplicate
                and choose(candidate, "priority_page_type:homepage")
            ):
                break
        for candidate in ordered:
            if candidate.manual_selection is ManualSelection.INCLUDE:
                choose(candidate, "manual_include")

        for page_type in _IMPORTANT_ORDER[1:]:
            for candidate in ordered:
                if (
                    candidate.page_type is page_type
                    and _eligible(candidate, include_restricted=include_restricted)
                    and choose(candidate, f"priority_page_type:{page_type.value}")
                ):
                    break

        for candidate in ordered:
            if (
                candidate.page_type in _CONTENT_TYPES
                and _eligible(candidate, include_restricted=include_restricted)
                and choose(candidate, "priority_content_page")
            ):
                break

        for candidate in ordered:
            if not _eligible(candidate, include_restricted=include_restricted):
                continue
            template = candidate.template_group_key
            if template is None or template_counts[template] == 0:
                choose(candidate, "diverse_template_fill")

        # A template cluster contributes at most one automatically selected page. It is
        # preferable to leave capacity unused than to schedule visually redundant work.
        for candidate in ordered:
            template = candidate.template_group_key
            if _eligible(candidate, include_restricted=include_restricted) and template is None:
                choose(candidate, "unclustered_capacity_fill")

    rank_by_id = {candidate.page_id: index for index, candidate in enumerate(selected, start=1)}
    output: list[RepresentativeDecision] = []
    for candidate in sorted(candidates, key=lambda item: (item.normalized_url, str(item.page_id))):
        selected_value, reason = decisions.get(
            candidate.page_id,
            (False, _rejection_reason(candidate, maximum_pages, include_restricted)),
        )
        output.append(
            RepresentativeDecision(
                page_id=candidate.page_id,
                selected=selected_value,
                rank=rank_by_id.get(candidate.page_id),
                score=_score(candidate),
                explanation=(reason, f"page_type:{candidate.page_type.value}"),
                selector=SELECTOR_NAME,
                version=SELECTOR_VERSION,
            )
        )
    return tuple(output)


def _eligible(candidate: RepresentativeCandidate, *, include_restricted: bool) -> bool:
    return (
        candidate.manual_selection is not ManualSelection.EXCLUDE
        and not candidate.exact_duplicate
        and not candidate.near_duplicate
        and (include_restricted or candidate.page_type not in _RESTRICTED_TYPES)
    )


def _rejection_reason(
    candidate: RepresentativeCandidate, maximum_pages: int, include_restricted: bool
) -> str:
    if candidate.manual_selection is ManualSelection.EXCLUDE:
        return "manual_exclude"
    if candidate.manual_selection is ManualSelection.INCLUDE and maximum_pages == 0:
        return "manual_include_blocked_by_zero_limit"
    if candidate.manual_selection is ManualSelection.INCLUDE:
        return "manual_include_displaced_by_limit"
    if candidate.exact_duplicate:
        return "exact_duplicate"
    if candidate.near_duplicate:
        return "near_duplicate"
    if not include_restricted and candidate.page_type in _RESTRICTED_TYPES:
        return "restricted_page_type"
    return "selection_limit_or_lower_priority"
