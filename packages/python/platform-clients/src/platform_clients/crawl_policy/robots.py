"""Bounded, SSRF-aware robots.txt retrieval and parsing."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from platform_clients.crawl_policy.models import CrawlPolicyConfig, RobotsFetchStatus, RobotsPolicy
from platform_clients.network_safety import (
    ApprovedUrl,
    NetworkFailureCode,
    NetworkRequestContext,
    NetworkSafetyError,
    NetworkSafetySubsystem,
)


@dataclass(frozen=True, slots=True)
class RobotsHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: AsyncIterable[bytes]
    peer_address: str | None = None


class RobotsTransport(Protocol):
    """Transport must connect only to an address from ``approved.addresses``."""

    async def get(
        self, approved: ApprovedUrl, *, user_agent: str, connect_timeout: float, read_timeout: float
    ) -> RobotsHttpResponse: ...


class RobotsFetcher:
    def __init__(
        self,
        safety: NetworkSafetySubsystem,
        transport: RobotsTransport,
        config: CrawlPolicyConfig,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._safety = safety
        self._transport = transport
        self._config = config
        self._clock = clock

    async def fetch(self, origin_url: str, context: NetworkRequestContext) -> RobotsPolicy:
        parsed = urlsplit(origin_url)
        robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
        current_url = robots_url
        redirect_count = 0
        try:
            approved = await self._safety.prepare(current_url, context)
            while True:
                approved = await self._safety.revalidate_before_connection(approved, context)
                response = await self._transport.get(
                    approved,
                    user_agent=self._config.user_agent,
                    connect_timeout=self._safety.policy.limits.timeouts.connect_seconds,
                    read_timeout=self._safety.policy.limits.timeouts.read_seconds,
                )
                if response.peer_address is not None:
                    await self._safety.revalidate_before_connection(
                        approved, context, peer_address=response.peer_address
                    )
                header_bytes = sum(
                    len(str(name).encode()) + len(str(value).encode()) + 4
                    for name, value in response.headers.items()
                )
                if header_bytes > self._safety.policy.limits.max_response_header_bytes:
                    return self._record(
                        robots_url,
                        current_url,
                        RobotsFetchStatus.OVERSIZED,
                        redirect_count=redirect_count,
                    )
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location") or response.headers.get("Location")
                    approved = await self._safety.prepare_redirect(
                        approved, location or "", redirect_count=redirect_count, context=context
                    )
                    redirect_count += 1
                    current_url = approved.url
                    continue
                break
        except NetworkSafetyError as error:
            status = (
                RobotsFetchStatus.REDIRECT_LIMIT_EXCEEDED
                if error.code is NetworkFailureCode.REDIRECT_LIMIT_EXCEEDED
                else RobotsFetchStatus.BLOCKED
            )
            return self._record(robots_url, current_url, status, redirect_count=redirect_count)
        except (OSError, TimeoutError):
            return self._record(
                robots_url,
                current_url,
                RobotsFetchStatus.UNAVAILABLE,
                redirect_count=redirect_count,
            )
        if response.status in {404, 410}:
            return self._record(
                robots_url, current_url, RobotsFetchStatus.NOT_FOUND, redirect_count=redirect_count
            )
        if response.status < 200 or response.status >= 300:
            return self._record(
                robots_url,
                current_url,
                RobotsFetchStatus.UNAVAILABLE,
                redirect_count=redirect_count,
            )
        declared_length = response.headers.get("content-length") or response.headers.get(
            "Content-Length"
        )
        if declared_length is not None:
            try:
                if int(declared_length) > self._config.robots_max_bytes:
                    return self._record(
                        robots_url,
                        current_url,
                        RobotsFetchStatus.OVERSIZED,
                        redirect_count=redirect_count,
                    )
            except ValueError:
                return self._record(
                    robots_url,
                    current_url,
                    RobotsFetchStatus.INVALID,
                    redirect_count=redirect_count,
                )
        body = bytearray()
        try:
            async for chunk in response.body:
                body.extend(chunk)
                if len(body) > self._config.robots_max_bytes:
                    return self._record(
                        robots_url,
                        current_url,
                        RobotsFetchStatus.OVERSIZED,
                        redirect_count=redirect_count,
                    )
        except (OSError, TimeoutError):
            return self._record(
                robots_url,
                current_url,
                RobotsFetchStatus.UNAVAILABLE,
                redirect_count=redirect_count,
            )
        if b"\x00" in body:
            return self._record(
                robots_url, current_url, RobotsFetchStatus.INVALID, redirect_count=redirect_count
            )
        try:
            text = bytes(body).decode("utf-8-sig")
        except UnicodeDecodeError:
            return self._record(
                robots_url, current_url, RobotsFetchStatus.INVALID, redirect_count=redirect_count
            )
        if any(
            ":" not in line.split("#", 1)[0]
            for line in text.splitlines()
            if line.split("#", 1)[0].strip()
        ):
            return self._record(
                robots_url, current_url, RobotsFetchStatus.INVALID, redirect_count=redirect_count
            )
        parser = RobotFileParser()
        parser.set_url(current_url)
        try:
            parser.parse(text.splitlines())
            delay = parser.crawl_delay(self._config.user_agent)
            sitemaps = tuple(parser.site_maps() or ())
        except (TypeError, ValueError):
            return self._record(
                robots_url, current_url, RobotsFetchStatus.INVALID, redirect_count=redirect_count
            )
        return self._record(
            robots_url,
            current_url,
            RobotsFetchStatus.FETCHED,
            content_sha256=hashlib.sha256(body).hexdigest(),
            crawl_delay=float(delay) if delay is not None else None,
            sitemaps=sitemaps,
            redirect_count=redirect_count,
            body=text,
        )

    def _record(
        self,
        robots_url: str,
        final_url: str,
        status: RobotsFetchStatus,
        *,
        content_sha256: str | None = None,
        crawl_delay: float | None = None,
        sitemaps: tuple[str, ...] = (),
        redirect_count: int = 0,
        body: str | None = None,
    ) -> RobotsPolicy:
        return RobotsPolicy(
            robots_url=robots_url,
            final_url=final_url,
            fetch_status=status,
            fetched_at=self._clock(),
            content_sha256=content_sha256,
            user_agent=self._config.user_agent,
            crawl_delay_seconds=crawl_delay,
            sitemaps=sitemaps,
            redirect_count=redirect_count,
            body=body,
        )


def robots_allows(policy: RobotsPolicy, url: str) -> bool:
    if policy.fetch_status is RobotsFetchStatus.NOT_FOUND:
        return True
    if policy.fetch_status is not RobotsFetchStatus.FETCHED or policy.body is None:
        return False
    parser = RobotFileParser()
    parser.set_url(policy.final_url)
    parser.parse(policy.body.splitlines())
    return parser.can_fetch(policy.user_agent, url)


def effective_crawl_delay(config: CrawlPolicyConfig, policy: RobotsPolicy) -> float:
    """Choose the stricter configured or robots-declared per-domain delay."""
    return max(config.default_crawl_delay_seconds, policy.crawl_delay_seconds or 0.0)
