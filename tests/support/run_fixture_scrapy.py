"""Subprocess-only Scrapy probe for the loopback development fixture."""

from __future__ import annotations

import argparse
import ipaddress
import json
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import UUID, uuid4

from platform_clients.crawl_policy import CrawlPolicyConfig
from platform_clients.network_safety import (
    ApprovedUrl,
    NetworkRequestContext,
    NetworkSafetyPolicy,
    ValidatedResponseHeaders,
)
from platform_crawler_worker.models import PageDiscovery, TargetCrawlConfiguration
from platform_crawler_worker.spider import WebsiteSpider
from platform_crawler_worker.subprocess_main import _scrapy_settings
from scrapy.crawler import CrawlerProcess


class FixtureSafety:
    """Explicit test-only loopback exception; never imported by production worker code."""

    policy = NetworkSafetyPolicy()

    async def prepare(self, value: str, context: NetworkRequestContext) -> ApprovedUrl:
        del context
        parsed = urlsplit(value)
        return ApprovedUrl(
            url=value,
            scheme=parsed.scheme,
            hostname=parsed.hostname or "127.0.0.1",
            port=parsed.port or 80,
            addresses=frozenset({ipaddress.ip_address("127.0.0.1")}),
        )

    async def prepare_redirect(
        self,
        previous: ApprovedUrl,
        location: str,
        *,
        redirect_count: int,
        context: NetworkRequestContext,
    ) -> ApprovedUrl:
        del redirect_count
        return await self.prepare(urljoin(previous.url, location), context)

    async def revalidate_before_connection(
        self,
        approved: ApprovedUrl,
        context: NetworkRequestContext,
        *,
        peer_address: str | None = None,
    ) -> ApprovedUrl:
        del context, peer_address
        return approved

    async def validate_html_response(
        self, approved: ApprovedUrl, headers: Any, context: NetworkRequestContext
    ) -> ValidatedResponseHeaders:
        del approved, headers, context
        return ValidatedResponseHeaders("text/html", None, 0)


class FixtureRepository:
    def __init__(self) -> None:
        self.pages: dict[str, PageDiscovery] = {}
        self.failures: list[str] = []

    async def persist_robots(self, configuration: Any, policy: Any) -> UUID:
        del configuration, policy
        return uuid4()

    async def persist_page(
        self, configuration: Any, policy_record_id: UUID, discovery: PageDiscovery
    ) -> UUID:
        del configuration, policy_record_id
        self.pages[discovery.canonical_url] = discovery
        return uuid4()

    async def record_failure(self, configuration: Any, failure: Any) -> None:
        del configuration
        self.failures.append(str(failure.code))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    base_url = parser.parse_args().base_url.rstrip("/") + "/"
    repository = FixtureRepository()
    configuration = TargetCrawlConfiguration(
        campaign_id=uuid4(),
        project_id=uuid4(),
        target_id=uuid4(),
        seed_url=base_url,
        source_domain=urlsplit(base_url).hostname or "fixture",
        policy=CrawlPolicyConfig(
            maximum_depth=3,
            maximum_pages_per_domain=20,
            default_crawl_delay_seconds=0,
        ),
        allowed_content_types=frozenset({"text/html"}),
        per_domain_concurrency=1,
        overall_concurrency=1,
        connect_timeout_seconds=5,
        response_timeout_seconds=5,
        campaign_timeout_seconds=30,
        store_raw_html=False,
        retention_days=1,
    )
    settings = _scrapy_settings(configuration)
    settings.set("LOG_ENABLED", False)
    process = CrawlerProcess(settings)
    process.crawl(
        WebsiteSpider,
        configuration=configuration,
        repository=repository,
        network_safety=FixtureSafety(),
        rate_limiter=None,
    )
    process.start()
    print(
        json.dumps(
            {
                "event": "summary",
                "pages": len(repository.pages),
                "titles": sorted(page.title for page in repository.pages.values() if page.title),
                "failures": repository.failures,
            }
        )
    )


if __name__ == "__main__":
    main()
