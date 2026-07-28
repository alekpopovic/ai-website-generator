"""Bounded crawler configuration and normalized discovery contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from platform_clients.crawl_policy import CrawlPolicyConfig


@dataclass(frozen=True, slots=True)
class TargetCrawlConfiguration:
    campaign_id: UUID
    project_id: UUID
    target_id: UUID
    seed_url: str
    source_domain: str
    policy: CrawlPolicyConfig
    allowed_content_types: frozenset[str]
    per_domain_concurrency: int
    overall_concurrency: int
    connect_timeout_seconds: float
    response_timeout_seconds: float
    campaign_timeout_seconds: int
    store_raw_html: bool
    retention_days: int


@dataclass(frozen=True, slots=True)
class PageDiscovery:
    requested_url: str
    final_url: str
    canonical_url: str
    declared_canonical_url: str | None
    hreflang_links: tuple[HreflangLink, ...]
    last_modified_at: datetime | None
    fingerprints: PageFingerprints
    status_code: int
    content_type: str
    title: str | None
    meta_description: str | None
    language: str | None
    content_length: int
    content_sha256: str
    discovery_source: str
    parent_url: str | None
    depth: int
    robots_allowed: bool
    policy_provenance: dict[str, object]
    fetched_at: datetime
    raw_html: bytes | None = None


@dataclass(frozen=True, slots=True)
class SitemapDocument:
    urls: tuple[SitemapEntry, ...]
    child_sitemaps: tuple[SitemapEntry, ...]


@dataclass(frozen=True, slots=True)
class SitemapEntry:
    original_url: str
    last_modified_at: datetime | None


@dataclass(frozen=True, slots=True)
class HreflangLink:
    language: str
    original_url: str
    normalized_url: str


@dataclass(frozen=True, slots=True)
class HtmlMetadata:
    title: str | None
    description: str | None
    language: str | None
    links: tuple[str, ...]
    canonical_link: str | None
    hreflang_links: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class PageFingerprints:
    algorithm: str
    version: int
    normalized_url_sha256: str
    visible_text_sha256: str
    dom_structure_sha256: str
    heading_sequence_sha256: str
    link_structure_sha256: str
    response_body_sha256: str
    semantic_simhash: str
    dom_template_sha256: str
    normalized_content_sha256: str
    normalized_text_length: int


@dataclass(frozen=True, slots=True)
class CrawlFailure:
    code: str
    message: str
    retryable: bool
    requested_url: str | None = None
