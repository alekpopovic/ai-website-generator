"""Policy-aware Scrapy spider for one database-owned scan target."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
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

from platform_crawler_worker.fingerprinting import compute_page_fingerprints
from platform_crawler_worker.models import (
    CrawlFailure,
    HreflangLink,
    PageDiscovery,
    TargetCrawlConfiguration,
)
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
        self.seen_sitemaps: set[str] = set()
        self.sitemap_url_count = 0

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
                request = self._sitemap_request(
                    sitemap, index_depth=0, page_source="robots_sitemap"
                )
                if request is not None:
                    requests.append(request)
        root = self._page_request(
            self.configuration.seed_url, depth=0, source="submitted_root", parent_url=None
        )
        if root is not None:
            requests.append(root)
        return requests

    async def parse_sitemap_response(self, response: Response) -> list[Request]:
        try:
            remaining = self.configuration.policy.maximum_sitemap_urls - self.sitemap_url_count
            if remaining <= 0:
                return []
            document = parse_sitemap(
                response.body,
                maximum_urls=remaining,
                maximum_bytes=self.configuration.policy.maximum_sitemap_bytes,
            )
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
        page_source = str(response.meta.get("sitemap_page_source", "sitemap"))
        self.sitemap_url_count += len(document.urls) + len(document.child_sitemaps)
        if index_depth < self.configuration.policy.maximum_sitemap_depth:
            for sitemap in document.child_sitemaps:
                if self._internal(sitemap.original_url):
                    request = self._sitemap_request(
                        sitemap.original_url,
                        index_depth=index_depth + 1,
                        page_source="sitemap",
                    )
                    if request is not None:
                        requests.append(request)
        for entry in document.urls:
            request = self._page_request(
                entry.original_url,
                depth=0,
                source=page_source,
                parent_url=response.url,
                last_modified_at=entry.last_modified_at,
            )
            if request is not None:
                requests.append(request)
        return requests

    async def parse_page(self, response: Response) -> list[Request]:
        if self.evaluator is None or self.policy_record_id is None:
            raise RuntimeError("robots policy must be persisted before crawling pages")
        canonical = canonicalize_url(response.url, self.configuration.policy)
        metadata = extract_html_metadata(response.body, response_url=response.url)
        declared_canonical: str | None = None
        if metadata.canonical_link is not None:
            try:
                declared_canonical = canonicalize_url(
                    metadata.canonical_link, self.configuration.policy
                )
            except ValueError:
                declared_canonical = None
        hreflangs: list[HreflangLink] = []
        for language, original_url in metadata.hreflang_links:
            try:
                normalized_url = canonicalize_url(original_url, self.configuration.policy)
            except ValueError:
                continue
            hreflangs.append(HreflangLink(language, original_url, normalized_url))
        last_modified = response.meta.get("sitemap_last_modified_at")
        if not isinstance(last_modified, datetime):
            last_modified = self._http_last_modified(response)
        content_type = (response.headers.get("Content-Type") or b"").decode("latin-1")
        discovery = PageDiscovery(
            requested_url=str(response.meta["requested_url"]),
            final_url=response.url,
            canonical_url=canonical,
            declared_canonical_url=declared_canonical,
            hreflang_links=tuple(hreflangs),
            last_modified_at=last_modified,
            fingerprints=compute_page_fingerprints(
                response.body, normalized_url=canonical, response_url=response.url
            ),
            status_code=response.status,
            content_type=content_type.partition(";")[0].casefold(),
            title=metadata.title,
            meta_description=metadata.description,
            language=metadata.language,
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
        if declared_canonical is not None and declared_canonical != canonical:
            request = self._page_request(
                declared_canonical,
                depth=discovery.depth,
                source="canonical",
                parent_url=canonical,
            )
            if request is not None:
                requests.append(request)
        for link in metadata.links:
            request = self._page_request(
                link, depth=next_depth, source="html_link", parent_url=canonical
            )
            if request is not None:
                requests.append(request)
        return requests

    def _page_request(
        self,
        url: str,
        *,
        depth: int,
        source: str,
        parent_url: str | None,
        last_modified_at: datetime | None = None,
    ) -> Request | None:
        if self.evaluator is None:
            return None
        try:
            normalized = canonicalize_url(url, self.configuration.policy)
        except ValueError:
            return None
        if not self._internal(normalized):
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
                "sitemap_last_modified_at": last_modified_at,
                "handle_httpstatus_all": True,
            },
        )

    def _sitemap_request(self, url: str, *, index_depth: int, page_source: str) -> Request | None:
        try:
            normalized = canonicalize_url(url, self.configuration.policy)
        except ValueError:
            return None
        if normalized in self.seen_sitemaps:
            return None
        self.seen_sitemaps.add(normalized)
        return Request(
            normalized,
            callback=self.parse_sitemap_response,
            errback=self.request_failed,
            meta={
                "crawl_kind": "sitemap",
                "sitemap_depth": index_depth,
                "sitemap_page_source": page_source,
                "handle_httpstatus_all": True,
            },
        )

    @staticmethod
    def _http_last_modified(response: Response) -> datetime | None:
        value = response.headers.get("Last-Modified")
        if value is None:
            return None
        try:
            parsed = parsedate_to_datetime(value.decode("latin-1"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            return None

    def _internal(self, url: str) -> bool:
        try:
            parsed = urlsplit(canonicalize_url(url, self.configuration.policy))
        except ValueError:
            return False
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
