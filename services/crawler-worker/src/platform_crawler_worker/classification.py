"""Replaceable deterministic page classifier and bounded HTML feature extraction."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from urllib.parse import urljoin, urlsplit

from parsel import Selector
from platform_clients.page_classification import (
    PageClassification,
    PageClassificationFeatures,
    PageClassifier,
    PageType,
)

CLASSIFIER_NAME = "rule-based-page-type"
CLASSIFIER_VERSION = 1
_SPACE = re.compile(r"\s+")


def _text(value: str) -> str:
    return _SPACE.sub(" ", value).strip().casefold()


def _schema_types(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        schema_type = value.get("@type")
        if isinstance(schema_type, str):
            found.add(schema_type.casefold())
        elif isinstance(schema_type, list):
            found.update(str(item).casefold() for item in schema_type[:20])
        for child in value.values():
            found.update(_schema_types(child))
    elif isinstance(value, list):
        for child in value[:100]:
            found.update(_schema_types(child))
    return found


def extract_classification_features(
    body: bytes, *, normalized_url: str
) -> PageClassificationFeatures:
    selector = Selector(body=body, type="html", base_url=normalized_url)
    title = _text(selector.css("title::text").get() or "")[:500]
    headings = tuple(
        _text(value)[:500]
        for value in selector.xpath("//h1//text()|//h2//text()|//h3//text()").getall()[:100]
        if _text(value)
    )
    navigation_labels = tuple(
        _text(" ".join(element.xpath(".//text()").getall()))[:200]
        for element in selector.xpath("//nav//a|//header//a")[:100]
        if _text(" ".join(element.xpath(".//text()").getall()))
    )
    schema_types: set[str] = set()
    for raw in selector.xpath(
        '//script[translate(@type,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")='
        '"application/ld+json"]/text()'
    ).getall()[:20]:
        if len(raw) > 100_000:
            continue
        try:
            schema_types.update(_schema_types(json.loads(raw)))
        except (json.JSONDecodeError, RecursionError):
            continue
    for itemtype in selector.css("[itemtype]::attr(itemtype)").getall()[:100]:
        schema_types.add(itemtype.rstrip("/").rsplit("/", 1)[-1].casefold())
    visible_text = _text(" ".join(selector.xpath("//body//text()[not(ancestor::script)]").getall()))
    links = selector.css("a[href]")[:2_000]
    link_text_length = sum(
        len(_text(" ".join(element.xpath(".//text()").getall()))) for element in links
    )
    origin = urlsplit(normalized_url)
    internal_links = 0
    for href in selector.css("a[href]::attr(href)").getall()[:2_000]:
        parsed = urlsplit(urljoin(normalized_url, href))
        if parsed.hostname == origin.hostname:
            internal_links += 1
    return PageClassificationFeatures(
        normalized_path=origin.path or "/",
        title=title,
        headings=headings,
        navigation_labels=navigation_labels,
        schema_types=tuple(sorted(schema_types))[:100],
        link_count=len(links),
        internal_link_count=internal_links,
        link_text_length=link_text_length,
        visible_text_length=len(visible_text),
        form_count=len(selector.css("form")),
        has_password_field=bool(selector.css('input[type="password"]')),
        article_count=len(selector.css("article")),
        section_count=len(selector.css("section")),
        main_count=len(selector.css("main")),
    )


class RuleBasedPageClassifier(PageClassifier):
    """Versioned scorer whose contract can later be implemented by a learned classifier."""

    name = CLASSIFIER_NAME
    version = CLASSIFIER_VERSION

    def classify(self, features: PageClassificationFeatures) -> PageClassification:
        scores: dict[PageType, float] = defaultdict(float)
        reasons: dict[PageType, list[str]] = defaultdict(list)

        def add(page_type: PageType, points: float, reason: str) -> None:
            scores[page_type] += points
            reasons[page_type].append(f"{reason}:{points:g}")

        path = features.normalized_path.casefold().strip("/")
        combined = " ".join((features.title, *features.headings, *features.navigation_labels))
        if not path:
            add(PageType.HOMEPAGE, 20, "root_path")
        keyword_rules = {
            PageType.ABOUT: ("about", "company", "our story", "who we are"),
            PageType.SERVICES: ("service", "solutions", "what we do"),
            PageType.PRODUCT: ("product", "platform"),
            PageType.FEATURES: ("feature", "capabilities"),
            PageType.PRICING: ("pricing", "plans", "packages"),
            PageType.CONTACT: ("contact", "get in touch", "talk to us"),
            PageType.DOCUMENTATION: ("docs", "documentation", "api reference", "guide"),
            PageType.BLOG_INDEX: ("blog", "journal", "news", "insights"),
            PageType.ARTICLE: ("article", "post", "field note"),
            PageType.CASE_STUDY: ("case study", "customer story", "success story"),
            PageType.CAREERS: ("career", "jobs", "join our team"),
            PageType.LEGAL: ("privacy", "terms", "legal", "cookies", "accessibility"),
            PageType.AUTHENTICATION: ("login", "log in", "sign in", "register", "password"),
        }
        for page_type, keywords in keyword_rules.items():
            for keyword in keywords:
                path_match_allowed = not (
                    page_type is PageType.BLOG_INDEX and len(path.split("/")) > 1
                )
                if path_match_allowed and keyword in path:
                    add(page_type, 9, f"path_keyword:{keyword}")
                if keyword in combined:
                    add(page_type, 3, f"content_label:{keyword}")

        schema_rules = {
            "article": PageType.ARTICLE,
            "blogposting": PageType.ARTICLE,
            "newsarticle": PageType.ARTICLE,
            "product": PageType.PRODUCT,
            "service": PageType.SERVICES,
            "aboutpage": PageType.ABOUT,
            "contactpage": PageType.CONTACT,
            "webpage": PageType.UNKNOWN,
            "faqpage": PageType.DOCUMENTATION,
        }
        for schema_type in features.schema_types:
            mapped = schema_rules.get(schema_type)
            if mapped is not None:
                add(mapped, 8, f"schema:{schema_type}")
        if features.has_password_field:
            add(PageType.AUTHENTICATION, 14, "password_form")
        if features.form_count and any(
            word in combined for word in ("contact", "message", "email")
        ):
            add(PageType.CONTACT, 5, "contact_form")
        if features.article_count == 1 and features.visible_text_length >= 500:
            add(PageType.ARTICLE, 4, "single_article_long_content")
        if features.article_count >= 3 or (
            features.link_density >= 0.35 and any(word in path for word in ("blog", "news"))
        ):
            add(PageType.BLOG_INDEX, 7, "article_listing_structure")
        if features.template_group_size >= 3 and features.article_count == 1:
            add(PageType.ARTICLE, 6, "repeated_article_template")
        if features.link_density >= 0.5 and features.visible_text_length < 2_000:
            add(PageType.BLOG_INDEX, 2, "high_link_density")
        if features.main_count:
            add(PageType.UNKNOWN, 0.5, "semantic_main")

        winner = max(PageType, key=lambda item: (scores[item], -list(PageType).index(item)))
        winning_score = scores[winner]
        ordered_scores = sorted(scores.values(), reverse=True)
        runner_up = ordered_scores[1] if len(ordered_scores) > 1 else 0.0
        if winning_score <= 1:
            winner = PageType.UNKNOWN
            confidence = 0.2
        else:
            confidence = min(0.99, 0.45 + (winning_score - runner_up) / 30)
        explanation = (
            *reasons[winner][:12],
            f"link_density:{features.link_density:.3f}",
            f"visible_text_length:{features.visible_text_length}",
            f"template_group_size:{features.template_group_size}",
        )
        return PageClassification(
            page_type=winner,
            score=round(confidence, 4),
            explanation=explanation,
            classifier=self.name,
            version=self.version,
        )
