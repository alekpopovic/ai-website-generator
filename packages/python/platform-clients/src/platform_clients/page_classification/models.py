"""Provider-neutral page classification and representative-selection contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol
from uuid import UUID


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


class ManualSelection(StrEnum):
    AUTOMATIC = "automatic"
    INCLUDE = "include"
    EXCLUDE = "exclude"


@dataclass(frozen=True, slots=True)
class PageClassificationFeatures:
    normalized_path: str
    title: str
    headings: tuple[str, ...]
    navigation_labels: tuple[str, ...]
    schema_types: tuple[str, ...]
    link_count: int
    internal_link_count: int
    link_text_length: int
    visible_text_length: int
    form_count: int
    has_password_field: bool
    article_count: int
    section_count: int
    main_count: int
    template_group_size: int = 1

    @property
    def link_density(self) -> float:
        return self.link_text_length / max(1, self.visible_text_length)

    def with_template_group_size(self, size: int) -> PageClassificationFeatures:
        return replace(self, template_group_size=max(1, size))

    def to_dict(self) -> dict[str, object]:
        return {
            "normalized_path": self.normalized_path,
            "title": self.title,
            "headings": list(self.headings),
            "navigation_labels": list(self.navigation_labels),
            "schema_types": list(self.schema_types),
            "link_count": self.link_count,
            "internal_link_count": self.internal_link_count,
            "link_text_length": self.link_text_length,
            "visible_text_length": self.visible_text_length,
            "form_count": self.form_count,
            "has_password_field": self.has_password_field,
            "article_count": self.article_count,
            "section_count": self.section_count,
            "main_count": self.main_count,
            "template_group_size": self.template_group_size,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> PageClassificationFeatures:
        def strings(name: str) -> tuple[str, ...]:
            raw = value.get(name, [])
            return tuple(str(item) for item in raw) if isinstance(raw, list) else ()

        def integer(name: str, default: int = 0) -> int:
            raw = value.get(name, default)
            return int(raw) if isinstance(raw, (int, float)) else default

        return cls(
            normalized_path=str(value.get("normalized_path", "/")),
            title=str(value.get("title", "")),
            headings=strings("headings"),
            navigation_labels=strings("navigation_labels"),
            schema_types=strings("schema_types"),
            link_count=integer("link_count"),
            internal_link_count=integer("internal_link_count"),
            link_text_length=integer("link_text_length"),
            visible_text_length=integer("visible_text_length"),
            form_count=integer("form_count"),
            has_password_field=value.get("has_password_field") is True,
            article_count=integer("article_count"),
            section_count=integer("section_count"),
            main_count=integer("main_count"),
            template_group_size=max(1, integer("template_group_size", 1)),
        )


@dataclass(frozen=True, slots=True)
class PageClassification:
    page_type: PageType
    score: float
    explanation: tuple[str, ...]
    classifier: str
    version: int


class PageClassifier(Protocol):
    def classify(self, features: PageClassificationFeatures) -> PageClassification: ...


@dataclass(frozen=True, slots=True)
class RepresentativeCandidate:
    page_id: UUID
    normalized_url: str
    page_type: PageType
    classification_score: float
    template_group_key: str | None
    normalized_text_length: int
    exact_duplicate: bool
    near_duplicate: bool
    manual_selection: ManualSelection = ManualSelection.AUTOMATIC


@dataclass(frozen=True, slots=True)
class RepresentativeDecision:
    page_id: UUID
    selected: bool
    rank: int | None
    score: float
    explanation: tuple[str, ...]
    selector: str
    version: int
