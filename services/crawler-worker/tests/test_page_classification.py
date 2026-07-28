"""Fixture classification and representative-selection policy tests."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from platform_clients.page_classification import (
    ManualSelection,
    PageType,
    RepresentativeCandidate,
    select_representative_pages,
)
from platform_crawler_worker.classification import (
    RuleBasedPageClassifier,
    extract_classification_features,
)

FIXTURE_SITE = Path(__file__).parents[3] / "tests" / "fixtures" / "websites" / "site"


@pytest.mark.parametrize(
    ("relative_path", "page_type"),
    [
        ("index.html", PageType.HOMEPAGE),
        ("about/index.html", PageType.ABOUT),
        ("services/index.html", PageType.SERVICES),
        ("pricing/index.html", PageType.PRICING),
        ("contact/index.html", PageType.CONTACT),
        ("blog/index.html", PageType.BLOG_INDEX),
    ],
)
def test_rule_classifier_matches_fixture_page_types(
    relative_path: str, page_type: PageType
) -> None:
    path = FIXTURE_SITE / relative_path
    url_path = (
        "/" if relative_path == "index.html" else f"/{relative_path.removesuffix('index.html')}"
    )
    features = extract_classification_features(
        path.read_bytes(), normalized_url=f"https://fixture.example{url_path}"
    )
    result = RuleBasedPageClassifier().classify(features)
    assert result.page_type is page_type
    assert 0 < result.score <= 1
    assert result.explanation


def test_repeated_fixture_articles_use_template_group_signal() -> None:
    classifier = RuleBasedPageClassifier()
    for path in sorted((FIXTURE_SITE / "blog").glob("*/index.html")):
        features = extract_classification_features(
            path.read_bytes(),
            normalized_url=f"https://fixture.example/blog/{path.parent.name}/",
        ).with_template_group_size(3)
        result = classifier.classify(features)
        assert result.page_type is PageType.ARTICLE
        assert any(reason.startswith("repeated_article_template:") for reason in result.explanation)


def _candidate(
    number: int,
    page_type: PageType,
    *,
    template: str | None = None,
    manual: ManualSelection = ManualSelection.AUTOMATIC,
) -> RepresentativeCandidate:
    return RepresentativeCandidate(
        page_id=UUID(int=number),
        normalized_url=f"https://fixture.example/{page_type.value}/{number}",
        page_type=page_type,
        classification_score=0.9,
        template_group_key=template,
        normalized_text_length=1_000,
        exact_duplicate=False,
        near_duplicate=False,
        manual_selection=manual,
    )


def test_selector_prioritizes_homepage_types_content_and_template_diversity() -> None:
    candidates = (
        _candidate(1, PageType.HOMEPAGE),
        _candidate(2, PageType.PRICING),
        _candidate(3, PageType.PRODUCT),
        _candidate(4, PageType.SERVICES),
        _candidate(5, PageType.ABOUT),
        _candidate(6, PageType.CONTACT),
        _candidate(7, PageType.ARTICLE, template="articles"),
        _candidate(8, PageType.ARTICLE, template="articles"),
        _candidate(9, PageType.LEGAL),
        _candidate(10, PageType.AUTHENTICATION),
    )
    decisions = select_representative_pages(candidates, maximum_pages=7)
    selected = {decision.page_id for decision in decisions if decision.selected}
    assert selected == {UUID(int=value) for value in range(1, 8)}
    assert next(item for item in decisions if item.page_id == UUID(int=1)).rank == 1
    assert all(decision.explanation and decision.score != 0 for decision in decisions)
    assert (
        "restricted_page_type"
        in next(item for item in decisions if item.page_id == UUID(int=9)).explanation
    )


def test_manual_include_can_select_restricted_page_but_not_displace_homepage() -> None:
    decisions = select_representative_pages(
        (
            _candidate(1, PageType.HOMEPAGE),
            _candidate(2, PageType.LEGAL, manual=ManualSelection.INCLUDE),
            _candidate(3, PageType.PRICING),
        ),
        maximum_pages=2,
    )
    selected = [item.page_id for item in decisions if item.selected]
    assert selected == [UUID(int=1), UUID(int=2)]


def test_selector_does_not_fill_capacity_from_the_same_template_cluster() -> None:
    decisions = select_representative_pages(
        tuple(
            _candidate(number, PageType.ARTICLE, template="repeated-articles")
            for number in range(1, 6)
        ),
        maximum_pages=5,
    )
    assert sum(item.selected for item in decisions) == 1
    assert all(item.explanation for item in decisions)


def test_schema_metadata_and_password_form_are_deterministic_signals() -> None:
    html = b"""
    <html><head><title>Member access</title>
      <script type="application/ld+json">{"@type":"Product","name":"Private"}</script>
    </head><body><main><h1>Sign in</h1><form><input type="password"></form></main></body></html>
    """
    features = extract_classification_features(html, normalized_url="https://fixture.example/login")
    result = RuleBasedPageClassifier().classify(features)
    assert "product" in features.schema_types
    assert features.has_password_field is True
    assert result.page_type is PageType.AUTHENTICATION
