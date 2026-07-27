"""Opt-in Redis integration coverage for distributed crawl coordination."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from platform_clients.crawl_policy import RedisCrawlLocks, RedisDomainRateLimiter
from redis.asyncio import Redis

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    url = os.environ.get("INTEGRATION_REDIS_URL")
    if url is None:
        pytest.skip("INTEGRATION_REDIS_URL is not configured")
    client: Redis = Redis.from_url(url, decode_responses=False)
    await client.ping()
    try:
        yield client
    finally:
        await client.aclose()


async def test_redis_lock_ownership_and_atomic_domain_bucket(redis_client: Redis) -> None:
    prefix = f"platform-integration:{uuid4()}"
    locks = RedisCrawlLocks(redis_client, prefix=prefix)
    limiter = RedisDomainRateLimiter(redis_client, prefix=prefix, capacity=1, refill_per_second=0.1)
    try:
        lease = await locks.acquire("example.com", ttl_seconds=30)
        assert lease is not None
        assert await locks.acquire("example.com", ttl_seconds=30) is None
        assert await locks.renew(lease, ttl_seconds=30)
        assert await locks.release(lease)

        assert (await limiter.acquire("example.com")).allowed
        denied = await limiter.acquire("example.com")
        assert not denied.allowed
        assert denied.retry_after_seconds > 0
    finally:
        keys = [key async for key in redis_client.scan_iter(match=f"{prefix}:*")]
        if keys:
            await redis_client.delete(*keys)
