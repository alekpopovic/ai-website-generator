"""Offline crawl-policy, robots, canonicalization, limits, and coordination tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from platform_clients.crawl_policy import (
    CrawlDecisionCode,
    CrawlPolicyConfig,
    CrawlPolicyEvaluator,
    InMemoryCrawlLocks,
    InMemoryDomainRateLimiter,
    RobotsFetcher,
    RobotsFetchStatus,
    RobotsHttpResponse,
    RobotsPolicy,
    canonicalize_url,
    effective_crawl_delay,
)
from platform_clients.network_safety import (
    ApprovedUrl,
    NetworkLimits,
    NetworkRequestContext,
    NetworkSafetyPolicy,
    NetworkSafetySubsystem,
    SequenceDnsResolver,
)

pytestmark = pytest.mark.anyio
FIXTURES = Path(__file__).parents[4] / "tests" / "fixtures" / "websites" / "robots"
NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)
PUBLIC_IP = "93.184.216.34"


async def chunks(value: bytes, size: int = 17) -> AsyncIterator[bytes]:
    for offset in range(0, len(value), size):
        yield value[offset : offset + size]


class FakeRobotsTransport:
    def __init__(self, responses: Mapping[str, tuple[int, Mapping[str, str], bytes]]) -> None:
        self._responses = responses
        self.requested: list[str] = []

    async def get(
        self,
        approved: ApprovedUrl,
        *,
        user_agent: str,
        connect_timeout: float,
        read_timeout: float,
    ) -> RobotsHttpResponse:
        del user_agent, connect_timeout, read_timeout
        url = approved.url
        self.requested.append(url)
        status, headers, body = self._responses[url]
        return RobotsHttpResponse(status, headers, chunks(body), peer_address=PUBLIC_IP)


def config(**changes: object) -> CrawlPolicyConfig:
    values: dict[str, object] = {
        "user_agent": "AIWebsiteGeneratorBot",
        "maximum_depth": 2,
        "maximum_pages_per_domain": 2,
    }
    values.update(changes)
    return CrawlPolicyConfig(**values)  # type: ignore[arg-type]


def robots(
    *, body: str | None, status: RobotsFetchStatus = RobotsFetchStatus.FETCHED
) -> RobotsPolicy:
    return RobotsPolicy(
        robots_url="https://example.com/robots.txt",
        final_url="https://example.com/robots.txt",
        fetch_status=status,
        fetched_at=NOW,
        content_sha256="a" * 64 if body is not None else None,
        user_agent="AIWebsiteGeneratorBot",
        crawl_delay_seconds=3,
        body=body,
    )


def test_canonicalization_removes_fragments_tracking_and_query_order() -> None:
    result = canonicalize_url(
        "HTTPS://Exämple.com:443/a/../pricing/?utm_source=x&b=2&a=1#details", config()
    )
    assert result == "https://xn--exmple-cua.com/pricing/?a=1&b=2"


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("https://example.com/logout", CrawlDecisionCode.LOGOUT),
        ("https://example.com/wp-admin/", CrawlDecisionCode.ADMIN_AREA),
        ("https://example.com/account/reset", CrawlDecisionCode.ACCOUNT_ACTION),
        ("https://example.com/product?add-to-cart=1", CrawlDecisionCode.CART_MUTATION),
        ("https://example.com/report.pdf", CrawlDecisionCode.FILE_DOWNLOAD),
        ("https://example.com/calendar/2026/07", CrawlDecisionCode.CALENDAR_TRAP),
    ],
)
async def test_conservative_traps_are_excluded(url: str, code: CrawlDecisionCode) -> None:
    decision = CrawlPolicyEvaluator(config(), robots(body="User-agent: *\nAllow: /\n")).evaluate(
        url, depth=1
    )
    assert not decision.allowed
    assert decision.code is code


async def test_patterns_robots_depth_page_limit_and_fragment_duplicates() -> None:
    policy = (FIXTURES / "allow-with-sitemap.txt").read_text()
    evaluator = CrawlPolicyEvaluator(config(include_patterns=("*/docs/*",)), robots(body=policy))
    assert (
        evaluator.evaluate("https://example.com/other", depth=0).code
        is CrawlDecisionCode.INCLUDE_PATTERN_MISS
    )
    assert (
        evaluator.evaluate("https://example.com/docs/private/", depth=1).code
        is CrawlDecisionCode.ROBOTS_DISALLOWED
    )
    assert evaluator.evaluate("https://example.com/docs/one#top", depth=1).allowed
    assert (
        evaluator.evaluate("https://example.com/docs/one#bottom", depth=1).code
        is CrawlDecisionCode.DUPLICATE
    )
    assert (
        evaluator.evaluate("https://example.com/docs/deep", depth=3).code
        is CrawlDecisionCode.DEPTH_LIMIT
    )
    assert evaluator.evaluate("https://example.com/docs/two", depth=1).allowed
    assert (
        evaluator.evaluate("https://example.com/docs/three", depth=1).code
        is CrawlDecisionCode.PAGE_LIMIT
    )


async def test_robots_fetch_records_hash_delay_sitemap_and_redirect() -> None:
    body = (FIXTURES / "allow-with-sitemap.txt").read_bytes()
    transport = FakeRobotsTransport(
        {
            "https://example.com/robots.txt": (302, {"location": "/policy/robots.txt"}, b""),
            "https://example.com/policy/robots.txt": (
                200,
                {"content-length": str(len(body))},
                body,
            ),
        }
    )
    safety = NetworkSafetySubsystem(
        SequenceDnsResolver({"example.com": [[PUBLIC_IP], [PUBLIC_IP], [PUBLIC_IP], [PUBLIC_IP]]})
    )
    fetched = await RobotsFetcher(safety, transport, config(), clock=lambda: NOW).fetch(
        "https://example.com/start", NetworkRequestContext(component="crawler-worker")
    )
    assert fetched.fetch_status is RobotsFetchStatus.FETCHED
    assert fetched.redirect_count == 1
    assert fetched.content_sha256 is not None
    assert fetched.crawl_delay_seconds == 3
    assert fetched.sitemaps == ("https://example.com/sitemap.xml",)
    assert effective_crawl_delay(config(default_crawl_delay_seconds=5), fetched) == 5


@pytest.mark.parametrize(
    ("status", "body", "limit", "expected"),
    [
        (404, b"", 1024, RobotsFetchStatus.NOT_FOUND),
        (503, b"", 1024, RobotsFetchStatus.UNAVAILABLE),
        (200, b"bad\x00robots", 1024, RobotsFetchStatus.INVALID),
        (200, b"x" * 1025, 1024, RobotsFetchStatus.OVERSIZED),
    ],
)
async def test_robots_failure_modes_fail_closed(
    status: int, body: bytes, limit: int, expected: RobotsFetchStatus
) -> None:
    url = "https://example.com/robots.txt"
    fetcher = RobotsFetcher(
        NetworkSafetySubsystem(SequenceDnsResolver({"example.com": [[PUBLIC_IP], [PUBLIC_IP]]})),
        FakeRobotsTransport({url: (status, {}, body)}),
        config(robots_max_bytes=limit),
        clock=lambda: NOW,
    )
    result = await fetcher.fetch(url, NetworkRequestContext(component="crawler-worker"))
    assert result.fetch_status is expected
    if expected is not RobotsFetchStatus.NOT_FOUND:
        assert (
            not CrawlPolicyEvaluator(config(), result)
            .evaluate("https://example.com/", depth=0)
            .allowed
        )


async def test_redirect_limit_is_typed() -> None:
    url = "https://example.com/robots.txt"
    safety = NetworkSafetySubsystem(
        SequenceDnsResolver({"example.com": [[PUBLIC_IP], [PUBLIC_IP], [PUBLIC_IP]]}),
        policy=NetworkSafetyPolicy(limits=NetworkLimits(max_redirects=1)),
    )
    result = await RobotsFetcher(
        safety,
        FakeRobotsTransport({url: (302, {"location": url}, b"")}),
        config(),
        clock=lambda: NOW,
    ).fetch(url, NetworkRequestContext(component="crawler-worker"))
    assert result.fetch_status is RobotsFetchStatus.REDIRECT_LIMIT_EXCEEDED


async def test_token_bucket_and_owned_lock_fakes_are_deterministic() -> None:
    now = [0.0]
    limiter = InMemoryDomainRateLimiter(capacity=1, refill_per_second=0.5, clock=lambda: now[0])
    assert (await limiter.acquire("example.com")).allowed
    blocked = await limiter.acquire("example.com")
    assert not blocked.allowed and blocked.retry_after_seconds == 2
    now[0] = 2
    assert (await limiter.acquire("example.com")).allowed

    locks = InMemoryCrawlLocks()
    lease = await locks.acquire("example.com", ttl_seconds=30)
    assert lease is not None
    assert await locks.acquire("EXAMPLE.COM", ttl_seconds=30) is None
    assert await locks.renew(lease, ttl_seconds=30)
    assert await locks.release(lease)
