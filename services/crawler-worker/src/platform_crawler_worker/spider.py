"""Policy-aware Scrapy spider for one database-owned scan target."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from uuid import UUID

from platform_clients.crawl_policy import (
    CrawlPolicyEvaluator,
    DomainRateLimiter,
    RobotsFetchStatus,
    RobotsPolicy,
    canonicalize_url,
    effective_crawl_delay,
)
from platform_clients.network_safety import NetworkRequestContext, NetworkSafetySubsystem
from scrapy import Request, Spider
from scrapy.http import Response
from twisted.python.failure import Failure

from platform_crawler_worker.models import CrawlFailure, PageDiscovery, TargetCrawlConfiguration
from platform_crawler_worker.parsing import extract_html_metadata, parse_sitemap
from platform_crawler_worker.repository import CrawlRepository


class WebsiteSpider(Spider):
    name = "website-target"

    def __init__(
        self,
        configuration: TargetCrawlConfiguration,
        repository: CrawlRepository,
        network_safety: NetworkSafetySubsystem,
        rate_limiter: DomainRateLimiter | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.configuration = configuration
        self.repository = repository
        self.network_safety = network_safety
        self.rate_limiter = rate_limiter
        self.request_context = NetworkRequestContext(
            component="scrapy", project_id=str(configuration.project_id)
        )
        self.allowed_content_types = configuration.allowed_content_types
        self.origin = urlsplit(configuration.seed_url)
        self.evaluator: CrawlPolicyEvaluator | None = None
        self.policy_record_id: UUID | None = None

    async def start(self) -> Any:
        robots_url = urlunsplit((self.origin.scheme, self.origin.netloc, "/robots.txt", "", ""))
        yield Request(
            robots_url,
            callback=self.parse_robots,
            errback=self.request_failed,
            meta={"crawl_kind": "robots", "handle_httpstatus_all": True},
            dont_filter=True,
        )

    async def parse_robots(self, response: Response) -> list[Request]:
        fetched_at = datetime.now(UTC)
        body: str | None = None
        status = RobotsFetchStatus.UNAVAILABLE
        digest: str | None = None
        delay: float | None = None
        sitemaps: tuple[str, ...] = ()
        if response.status in {404, 410}:
            status = RobotsFetchStatus.NOT_FOUND
        elif (
            200 <= response.status < 300
            and len(response.body) <= self.configuration.policy.robots_max_bytes
        ):
            try:
                body = response.body.decode("utf-8-sig")
                if b"\x00" in response.body:
                    raise ValueError
                parser = RobotFileParser(response.url)
                parser.parse(body.splitlines())
                delay_value = parser.crawl_delay(self.configuration.policy.user_agent)
                delay = float(delay_value) if delay_value is not None else None
                sitemaps = tuple(parser.site_maps() or ())
                digest = hashlib.sha256(response.body).hexdigest()
                status = RobotsFetchStatus.FETCHED
            except (UnicodeDecodeError, TypeError, ValueError):
                status = RobotsFetchStatus.INVALID
                body = None
        elif len(response.body) > self.configuration.policy.robots_max_bytes:
            status = RobotsFetchStatus.OVERSIZED
        policy = RobotsPolicy(
            robots_url=urlunsplit((self.origin.scheme, self.origin.netloc, "/robots.txt", "", "")),
            final_url=response.url,
            fetch_status=status,
            fetched_at=fetched_at,
            content_sha256=digest,
            user_agent=self.configuration.policy.user_agent,
            crawl_delay_seconds=delay,
            sitemaps=sitemaps,
            redirect_count=int(response.meta.get("redirect_count", 0)),
            body=body,
        )
        self.policy_record_id = await self.repository.persist_robots(self.configuration, policy)
        self.evaluator = CrawlPolicyEvaluator(self.configuration.policy, policy)
        self.download_delay = effective_crawl_delay(self.configuration.policy, policy)
        if not policy.usable:
            await self.repository.record_failure(
                self.configuration,
                CrawlFailure(
                    code=f"robots_{status.value}",
                    message="robots.txt could not be safely evaluated",
                    retryable=status is RobotsFetchStatus.UNAVAILABLE,
                ),
            )
            return []
        requests: list[Request] = []
        for sitemap in sitemaps:
            if self._internal(sitemap):
                requests.append(self._sitemap_request(sitemap, index_depth=0))
        root = self._page_request(
            self.configuration.seed_url, depth=0, source="seed", parent_url=None
        )
        if root is not None:
            requests.append(root)
        return requests

    async def parse_sitemap_response(self, response: Response) -> list[Request]:
        try:
            document = parse_sitemap(response.body)
        except ValueError:
            await self.repository.record_failure(
                self.configuration,
                CrawlFailure(
                    "sitemap_invalid", "sitemap XML is invalid or oversized", False, response.url
                ),
            )
            return []
        requests: list[Request] = []
        index_depth = int(response.meta.get("sitemap_depth", 0))
        if index_depth < 3:
            for sitemap in document.child_sitemaps:
                if self._internal(sitemap):
                    requests.append(self._sitemap_request(sitemap, index_depth=index_depth + 1))
        for url in document.urls:
            request = self._page_request(url, depth=0, source="sitemap", parent_url=response.url)
            if request is not None:
                requests.append(request)
        return requests

    async def parse_page(self, response: Response) -> list[Request]:
        if self.evaluator is None or self.policy_record_id is None:
            raise RuntimeError("robots policy must be persisted before crawling pages")
        canonical = canonicalize_url(response.url, self.configuration.policy)
        title, description, language, links = extract_html_metadata(
            response.body, response_url=response.url
        )
        content_type = (response.headers.get("Content-Type") or b"").decode("latin-1")
        discovery = PageDiscovery(
            requested_url=str(response.meta["requested_url"]),
            final_url=response.url,
            canonical_url=canonical,
            status_code=response.status,
            content_type=content_type.partition(";")[0].casefold(),
            title=title,
            meta_description=description,
            language=language,
            content_length=len(response.body),
            content_sha256=hashlib.sha256(response.body).hexdigest(),
            discovery_source=str(response.meta["discovery_source"]),
            parent_url=response.meta.get("parent_url"),
            depth=int(response.meta["crawl_depth"]),
            robots_allowed=True,
            policy_provenance=dict(response.meta["policy_provenance"]),
            fetched_at=datetime.now(UTC),
            raw_html=response.body if self.configuration.store_raw_html else None,
        )
        await self.repository.persist_page(self.configuration, self.policy_record_id, discovery)
        print(
            json.dumps({"event": "progress", "completed": self.evaluator.accepted_count}),
            flush=True,
        )
        next_depth = discovery.depth + 1
        requests: list[Request] = []
        for link in links:
            request = self._page_request(
                link, depth=next_depth, source="link", parent_url=canonical
            )
            if request is not None:
                requests.append(request)
        return requests

    def _page_request(
        self, url: str, *, depth: int, source: str, parent_url: str | None
    ) -> Request | None:
        if self.evaluator is None or not self._internal(url):
            return None
        decision = self.evaluator.evaluate(url, depth=depth)
        if not decision.allowed or decision.canonical_url is None:
            return None
        return Request(
            decision.canonical_url,
            callback=self.parse_page,
            errback=self.request_failed,
            meta={
                "crawl_kind": "page",
                "requested_url": url,
                "canonical_url": decision.canonical_url,
                "discovery_source": source,
                "parent_url": parent_url,
                "crawl_depth": depth,
                "policy_provenance": decision.provenance(),
                "handle_httpstatus_all": True,
            },
        )

    def _sitemap_request(self, url: str, *, index_depth: int) -> Request:
        return Request(
            url,
            callback=self.parse_sitemap_response,
            errback=self.request_failed,
            meta={
                "crawl_kind": "sitemap",
                "sitemap_depth": index_depth,
                "handle_httpstatus_all": True,
            },
        )

    def _internal(self, url: str) -> bool:
        parsed = urlsplit(url)
        return (
            parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
            and parsed.hostname.rstrip(".").casefold()
            == (self.origin.hostname or "").rstrip(".").casefold()
            and (parsed.port or (443 if parsed.scheme == "https" else 80))
            == (self.origin.port or (443 if self.origin.scheme == "https" else 80))
        )

    async def request_failed(self, failure: Failure) -> None:
        request = cast(Any, failure).request
        value = failure.value
        code = getattr(getattr(value, "code", None), "value", None) or type(value).__name__
        retryable = bool(getattr(value, "retryable", False))
        await self.repository.record_failure(
            self.configuration,
            CrawlFailure(
                code=f"request_{str(code).casefold()}",
                message="crawl request failed policy or transport validation",
                retryable=retryable,
                requested_url=request.url,
            ),
        )
