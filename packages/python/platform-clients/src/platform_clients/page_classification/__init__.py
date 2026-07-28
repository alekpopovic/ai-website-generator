"""Deterministic page classification and representative selection contracts."""

from platform_clients.page_classification.models import (
    ManualSelection,
    PageClassification,
    PageClassificationFeatures,
    PageClassifier,
    PageType,
    RepresentativeCandidate,
    RepresentativeDecision,
)
from platform_clients.page_classification.selector import (
    SELECTOR_NAME,
    SELECTOR_VERSION,
    select_representative_pages,
)

__all__ = [
    "SELECTOR_NAME",
    "SELECTOR_VERSION",
    "ManualSelection",
    "PageClassification",
    "PageClassificationFeatures",
    "PageClassifier",
    "PageType",
    "RepresentativeCandidate",
    "RepresentativeDecision",
    "select_representative_pages",
]
