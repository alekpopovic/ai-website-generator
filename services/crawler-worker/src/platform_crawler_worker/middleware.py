"""Scrapy downloader enforcement for URL, redirect, response, and rate policy."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from platform_clients.crawl_policy import DomainRateLimiter
from platform_clients.network_safety import (
    ApprovedUrl,
    NetworkRequestContext,
    NetworkSafetySubsystem,
    ScrapyRequestSafety,
)
from scrapy import Request, Spider
from scrapy.exceptions import IgnoreRequest
from scrapy.http import Response


class SafeRequestMiddleware:
    def __init__(self, safety: NetworkSafetySubsystem) -> None:
        self._adapter = ScrapyRequestSafety(safety)

    @classmethod
    def from_crawler(cls, crawler: Any) -> SafeRequestMiddleware:
        return cls(crawler.spider.network_safety)

    async def process_request(self, request: Request, spider: Spider) -> None:
        crawl_spider = cast(Any, spider)
        context = cast(NetworkRequestContext, crawl_spider.request_context)
        approved = await self._adapter.initial(request.url, context)
        approved = await self._adapter.before_connection(approved, context)
        request.meta["approved_url"] = approved
        limiter = cast(DomainRateLimiter | None, getattr(spider, "rate_limiter", None))
        if limiter is not None:
            while True:
                result = await limiter.acquire(approved.hostname)
                if result.allowed:
                    break
                await asyncio.sleep(min(result.retry_after_seconds, 5.0))

    async def process_response(
        self, request: Request, response: Response, spider: Spider
    ) -> Response | Request:
        approved = cast(ApprovedUrl, request.meta["approved_url"])
        crawl_spider = cast(Any, spider)
        context = cast(NetworkRequestContext, crawl_spider.request_context)
        if response.status in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            if location is None:
                raise IgnoreRequest("redirect response omitted Location")
            redirect_count = int(request.meta.get("redirect_count", 0))
            redirected = await self._adapter.redirect(
                approved, location.decode("latin-1"), redirect_count, context
            )
            redirected = await self._adapter.before_connection(redirected, context)
            return request.replace(
                url=redirected.url,
                dont_filter=True,
                meta={**request.meta, "redirect_count": redirect_count + 1},
            )
        kind = request.meta.get("crawl_kind", "page")
        if kind == "page":
            content_type = (response.headers.get("Content-Type") or b"").decode("latin-1")
            media_type = content_type.partition(";")[0].strip().casefold()
            allowed = cast(frozenset[str], crawl_spider.allowed_content_types)
            if media_type not in allowed:
                raise IgnoreRequest("response is not an allowed HTML content type")
            await self._adapter.html_response(
                approved,
                {
                    (key.decode("latin-1") if isinstance(key, bytes) else key): str(value)
                    for key, value in response.headers.to_unicode_dict().items()
                },
                context,
            )
        return response
