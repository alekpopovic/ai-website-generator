"""Stateful per-domain crawl admission with explicit policy provenance."""

from __future__ import annotations

from urllib.parse import urlsplit

from platform_clients.crawl_policy.canonical import (
    canonicalize_url,
    exclusion_reason,
    query_permutation_key,
)
from platform_clients.crawl_policy.models import (
    CrawlDecision,
    CrawlDecisionCode,
    CrawlPolicyConfig,
    RobotsPolicy,
)
from platform_clients.crawl_policy.robots import robots_allows


class CrawlPolicyEvaluator:
    """Evaluate and reserve canonical URLs for one domain crawl."""

    def __init__(self, config: CrawlPolicyConfig, robots: RobotsPolicy) -> None:
        self._config = config
        self._robots = robots
        self._accepted: set[str] = set()
        self._query_permutations: dict[
            tuple[str, str, str, tuple[tuple[str, str, bool], ...]], str
        ] = {}

    def evaluate(self, url: str, *, depth: int, reserve: bool = True) -> CrawlDecision:
        try:
            canonical = canonicalize_url(url, self._config)
        except ValueError:
            return self._decision(url, None, depth, False, CrawlDecisionCode.INVALID_URL, None)
        if canonical in self._accepted:
            return self._decision(url, canonical, depth, False, CrawlDecisionCode.DUPLICATE, None)
        if self._config.query_parameter_ordering == "preserve" and urlsplit(canonical).query:
            parsed = urlsplit(canonical)
            permutation = (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                query_permutation_key(canonical),
            )
            prior = self._query_permutations.get(permutation)
            if prior is not None and prior != canonical:
                return self._decision(
                    url, canonical, depth, False, CrawlDecisionCode.QUERY_PERMUTATION, None
                )
        if depth > self._config.maximum_depth:
            return self._decision(url, canonical, depth, False, CrawlDecisionCode.DEPTH_LIMIT, None)
        reason = exclusion_reason(canonical, self._config)
        if reason is not None:
            return self._decision(url, canonical, depth, False, reason, None)
        robots_allowed = robots_allows(self._robots, canonical)
        if not robots_allowed:
            code = (
                CrawlDecisionCode.ROBOTS_DISALLOWED
                if self._robots.usable
                else CrawlDecisionCode.ROBOTS_UNAVAILABLE
            )
            return self._decision(url, canonical, depth, False, code, False)
        if len(self._accepted) >= self._config.maximum_pages_per_domain:
            return self._decision(url, canonical, depth, False, CrawlDecisionCode.PAGE_LIMIT, True)
        if reserve:
            self._accepted.add(canonical)
            if self._config.query_parameter_ordering == "preserve" and urlsplit(canonical).query:
                parsed = urlsplit(canonical)
                permutation = (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    query_permutation_key(canonical),
                )
                self._query_permutations[permutation] = canonical
        return self._decision(url, canonical, depth, True, CrawlDecisionCode.ALLOWED, True)

    @property
    def accepted_count(self) -> int:
        return len(self._accepted)

    def _decision(
        self,
        requested_url: str,
        canonical_url: str | None,
        depth: int,
        allowed: bool,
        code: CrawlDecisionCode,
        robots_allowed: bool | None,
    ) -> CrawlDecision:
        return CrawlDecision(
            requested_url=requested_url,
            canonical_url=canonical_url,
            depth=depth,
            allowed=allowed,
            code=code,
            robots_allowed=robots_allowed,
            policy=self._robots,
        )
