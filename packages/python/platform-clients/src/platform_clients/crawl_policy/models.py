"""Typed crawl-policy decisions and provenance records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RobotsFetchStatus(StrEnum):
    FETCHED = "fetched"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    OVERSIZED = "oversized"
    REDIRECT_LIMIT_EXCEEDED = "redirect_limit_exceeded"
    BLOCKED = "blocked"


class CrawlDecisionCode(StrEnum):
    ALLOWED = "allowed"
    DUPLICATE = "duplicate"
    DEPTH_LIMIT = "depth_limit"
    PAGE_LIMIT = "page_limit"
    INCLUDE_PATTERN_MISS = "include_pattern_miss"
    EXCLUDE_PATTERN = "exclude_pattern"
    ROBOTS_DISALLOWED = "robots_disallowed"
    ROBOTS_UNAVAILABLE = "robots_unavailable"
    LOGOUT = "logout"
    CART_MUTATION = "cart_mutation"
    ADMIN_AREA = "admin_area"
    ACCOUNT_ACTION = "account_action"
    FILE_DOWNLOAD = "file_download"
    CALENDAR_TRAP = "calendar_trap"
    TRACKING_URL = "tracking_url"
    INVALID_URL = "invalid_url"


@dataclass(frozen=True, slots=True)
class CrawlPolicyConfig:
    user_agent: str = "AIWebsiteGeneratorBot/1.0"
    maximum_depth: int = 5
    maximum_pages_per_domain: int = 100
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()
    tracking_parameters: frozenset[str] = frozenset(
        {"dclid", "fbclid", "gclid", "mc_cid", "mc_eid", "msclkid", "ref", "referrer"}
    )
    tracking_parameter_prefixes: tuple[str, ...] = ("utm_",)
    robots_max_bytes: int = 512 * 1024
    default_crawl_delay_seconds: float = 1.0
    token_bucket_capacity: int = 2

    def __post_init__(self) -> None:
        if not self.user_agent.strip() or len(self.user_agent) > 256:
            raise ValueError("crawler user agent must be non-empty and at most 256 characters")
        if not 0 <= self.maximum_depth <= 20:
            raise ValueError("maximum depth must be between 0 and 20")
        if not 1 <= self.maximum_pages_per_domain <= 10_000:
            raise ValueError("maximum pages per domain must be between 1 and 10000")
        if not 1_024 <= self.robots_max_bytes <= 2 * 1024 * 1024:
            raise ValueError("robots size limit must be between 1 KiB and 2 MiB")
        if not 0 <= self.default_crawl_delay_seconds <= 60:
            raise ValueError("default crawl delay must be between 0 and 60 seconds")
        if not 1 <= self.token_bucket_capacity <= 100:
            raise ValueError("token bucket capacity must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class RobotsPolicy:
    robots_url: str
    final_url: str
    fetch_status: RobotsFetchStatus
    fetched_at: datetime
    content_sha256: str | None
    user_agent: str
    crawl_delay_seconds: float | None
    sitemaps: tuple[str, ...] = ()
    redirect_count: int = 0
    body: str | None = field(default=None, repr=False)

    @property
    def usable(self) -> bool:
        return self.fetch_status in {RobotsFetchStatus.FETCHED, RobotsFetchStatus.NOT_FOUND}


@dataclass(frozen=True, slots=True)
class CrawlDecision:
    requested_url: str
    canonical_url: str | None
    depth: int
    allowed: bool
    code: CrawlDecisionCode
    robots_allowed: bool | None
    policy: RobotsPolicy

    def provenance(self) -> dict[str, object]:
        """Return bounded JSON-compatible policy evidence for persistence."""
        return {
            "policy_version": 1,
            "code": self.code.value,
            "allowed": self.allowed,
            "depth": self.depth,
            "robots_allowed": self.robots_allowed,
            "robots_url": self.policy.robots_url,
            "robots_fetch_status": self.policy.fetch_status.value,
            "robots_content_sha256": self.policy.content_sha256,
            "user_agent": self.policy.user_agent,
        }
