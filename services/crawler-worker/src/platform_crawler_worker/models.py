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
    urls: tuple[str, ...]
    child_sitemaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CrawlFailure:
    code: str
    message: str
    retryable: bool
    requested_url: str | None = None
