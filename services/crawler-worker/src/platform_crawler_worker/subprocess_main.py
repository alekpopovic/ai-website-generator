"""One-shot Scrapy process: exactly one reactor lifecycle per scan target."""

from __future__ import annotations

import argparse
import asyncio
import signal
from uuid import UUID

from platform_api.config import get_settings
from platform_api.database import DatabaseManager
from platform_clients.crawl_policy import RedisCrawlLocks, RedisDomainRateLimiter
from platform_clients.network_safety import (
    NetworkLimits,
    NetworkSafetyPolicy,
    NetworkSafetySubsystem,
)
from platform_clients.network_safety.resolver import SystemDnsResolver
from platform_clients.object_storage import StorageConfig
from platform_clients.object_storage.models import StorageProvider
from platform_clients.object_storage.s3 import S3ObjectStorage
from redis.asyncio import Redis
from scrapy.crawler import CrawlerRunner
from scrapy.settings import Settings as ScrapySettings
from twisted.internet import asyncioreactor

from platform_crawler_worker.middleware import SafeRequestMiddleware
from platform_crawler_worker.models import CrawlFailure, TargetCrawlConfiguration
from platform_crawler_worker.repository import CrawlRepository
from platform_crawler_worker.spider import WebsiteSpider


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one isolated scan-target crawl")
    parser.add_argument("--campaign-id", type=UUID, required=True)
    parser.add_argument("--scan-target-id", type=UUID, required=True)
    return parser.parse_args()


async def _run(campaign_id: UUID, target_id: UUID) -> None:
    settings = get_settings()
    database = DatabaseManager(settings.database)
    redis: Redis | None = None
    storage: S3ObjectStorage | None = None
    try:
        preliminary = CrawlRepository(database)
        configuration = await preliminary.load_configuration(campaign_id, target_id)
        if settings.redis.url is None:
            raise RuntimeError("REDIS_URL is required by the crawler subprocess")
        redis = Redis.from_url(
            settings.redis.url.get_secret_value(),
            socket_connect_timeout=settings.redis.connect_timeout_seconds,
            decode_responses=False,
        )
        locks = RedisCrawlLocks(redis, prefix=settings.redis.key_prefix)
        lease = await locks.acquire(
            configuration.source_domain,
            ttl_seconds=min(float(configuration.campaign_timeout_seconds + 60), 86_400),
        )
        if lease is None:
            raise RuntimeError("another crawler owns the domain lease")
        try:
            if configuration.store_raw_html:
                minio = settings.minio
                storage = await S3ObjectStorage.create(
                    StorageConfig(
                        provider=StorageProvider(minio.provider),
                        region=minio.region,
                        endpoint_url=str(minio.endpoint) if minio.endpoint is not None else None,
                        access_key=minio.access_key.get_secret_value()
                        if minio.access_key
                        else None,
                        secret_key=minio.secret_key.get_secret_value()
                        if minio.secret_key
                        else None,
                        session_token=(
                            minio.session_token.get_secret_value() if minio.session_token else None
                        ),
                        connect_timeout_seconds=minio.connect_timeout_seconds,
                        read_timeout_seconds=minio.read_timeout_seconds,
                        multipart_part_size=minio.multipart_part_size,
                    )
                )
            repository = CrawlRepository(database, storage)
            limiter = RedisDomainRateLimiter(
                redis,
                prefix=settings.redis.key_prefix,
                capacity=configuration.policy.token_bucket_capacity,
                refill_per_second=1.0 / max(configuration.policy.default_crawl_delay_seconds, 0.05),
            )
            safety = NetworkSafetySubsystem(
                SystemDnsResolver(),
                policy=NetworkSafetyPolicy(
                    limits=NetworkLimits(
                        max_redirects=5,
                        max_response_body_bytes=5 * 1_024 * 1_024,
                    )
                ),
            )
            runner = CrawlerRunner(_scrapy_settings(configuration))
            deferred = runner.crawl(
                WebsiteSpider,
                configuration=configuration,
                repository=repository,
                network_safety=safety,
                rate_limiter=limiter,
            )
            await asyncio.wait_for(
                deferred.asFuture(asyncio.get_running_loop()),
                timeout=configuration.campaign_timeout_seconds,
            )
            await repository.mark_target(target_id, "completed")
        except Exception as error:
            await preliminary.record_failure(
                configuration,
                CrawlFailure(
                    code="crawler_subprocess_failed",
                    message="isolated crawler subprocess failed",
                    retryable=isinstance(error, (OSError, TimeoutError)),
                ),
            )
            await preliminary.mark_target(target_id, "failed")
            raise
        finally:
            await locks.release(lease)
    finally:
        if storage is not None:
            await storage.close()
        if redis is not None:
            await redis.aclose()
        await database.close()


def _scrapy_settings(config: TargetCrawlConfiguration) -> ScrapySettings:
    return ScrapySettings(
        {
            "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
            "ROBOTSTXT_OBEY": False,
            "REDIRECT_ENABLED": False,
            "LOG_ENABLED": False,
            "TELNETCONSOLE_ENABLED": False,
            "COOKIES_ENABLED": False,
            "USER_AGENT": config.policy.user_agent,
            "DEFAULT_REQUEST_HEADERS": {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.8,text/plain;q=0.5"
            },
            "DOWNLOAD_WARNSIZE": 4 * 1_024 * 1_024,
            "DOWNLOAD_MAXSIZE": 5 * 1_024 * 1_024,
            "DOWNLOAD_TIMEOUT": config.response_timeout_seconds,
            "DNS_TIMEOUT": config.connect_timeout_seconds,
            "CONCURRENT_REQUESTS": config.overall_concurrency,
            "CONCURRENT_REQUESTS_PER_DOMAIN": config.per_domain_concurrency,
            "DOWNLOAD_DELAY": config.policy.default_crawl_delay_seconds,
            "RANDOMIZE_DOWNLOAD_DELAY": False,
            "AUTOTHROTTLE_ENABLED": True,
            "AUTOTHROTTLE_START_DELAY": max(config.policy.default_crawl_delay_seconds, 1.0),
            "AUTOTHROTTLE_MAX_DELAY": 60.0,
            "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
            "AUTOTHROTTLE_DEBUG": False,
            "CLOSESPIDER_PAGECOUNT": config.policy.maximum_pages_per_domain,
            "CLOSESPIDER_TIMEOUT": config.campaign_timeout_seconds,
            # CrawlPolicyEvaluator owns semantic depth; Scrapy's depth includes robots/sitemaps.
            "DEPTH_LIMIT": 0,
            "RETRY_ENABLED": True,
            "RETRY_TIMES": 2,
            "RETRY_HTTP_CODES": [408, 425, 429, 500, 502, 503, 504],
            "DOWNLOADER_MIDDLEWARES": {
                f"{SafeRequestMiddleware.__module__}.{SafeRequestMiddleware.__name__}": 50,
                "scrapy.downloadermiddlewares.redirect.RedirectMiddleware": None,
                "scrapy.downloadermiddlewares.redirect.MetaRefreshMiddleware": None,
            },
        }
    )


def main() -> None:
    arguments = _arguments()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    asyncioreactor.install(loop)  # type: ignore[no-untyped-call]
    task = loop.create_task(_run(arguments.campaign_id, arguments.scan_target_id))
    for process_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(process_signal, task.cancel)
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        pass
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


if __name__ == "__main__":
    main()
