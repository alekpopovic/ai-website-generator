"""Lease-based Redis crawl locks with ownership-safe release and renewal."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol, cast

from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class CrawlLockLease:
    key: str
    token: str


class DistributedCrawlLocks(Protocol):
    async def acquire(self, domain: str, *, ttl_seconds: float) -> CrawlLockLease | None: ...
    async def renew(self, lease: CrawlLockLease, *, ttl_seconds: float) -> bool: ...
    async def release(self, lease: CrawlLockLease) -> bool: ...


class RedisCrawlLocks:
    _RELEASE = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end"
    _RENEW = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('PEXPIRE', KEYS[1], ARGV[2]) else return 0 end"

    def __init__(self, redis: Redis, *, prefix: str) -> None:
        self._redis = redis
        self._prefix = prefix

    async def acquire(self, domain: str, *, ttl_seconds: float) -> CrawlLockLease | None:
        ttl_ms = self._ttl_ms(ttl_seconds)
        key = self._key(domain)
        token = secrets.token_urlsafe(32)
        acquired = await self._redis.set(key, token, nx=True, px=ttl_ms)
        return CrawlLockLease(key, token) if acquired else None

    async def renew(self, lease: CrawlLockLease, *, ttl_seconds: float) -> bool:
        result = await self._redis.eval(
            self._RENEW, 1, lease.key, lease.token, self._ttl_ms(ttl_seconds)
        )
        return int(cast(int, result)) == 1

    async def release(self, lease: CrawlLockLease) -> bool:
        result = await self._redis.eval(self._RELEASE, 1, lease.key, lease.token)
        return int(cast(int, result)) == 1

    @staticmethod
    def _ttl_ms(ttl_seconds: float) -> int:
        if not 1 <= ttl_seconds <= 86_400:
            raise ValueError("crawl lock TTL must be between 1 second and 24 hours")
        return int(ttl_seconds * 1_000)

    def _key(self, domain: str) -> str:
        digest = hashlib.sha256(domain.casefold().encode()).hexdigest()
        return f"{self._prefix}:crawl:lock:{digest}"


class InMemoryCrawlLocks:
    def __init__(self) -> None:
        self._leases: dict[str, str] = {}

    async def acquire(self, domain: str, *, ttl_seconds: float) -> CrawlLockLease | None:
        del ttl_seconds
        key = domain.casefold()
        if key in self._leases:
            return None
        token = secrets.token_urlsafe(32)
        self._leases[key] = token
        return CrawlLockLease(key, token)

    async def renew(self, lease: CrawlLockLease, *, ttl_seconds: float) -> bool:
        del ttl_seconds
        return self._leases.get(lease.key) == lease.token

    async def release(self, lease: CrawlLockLease) -> bool:
        if self._leases.get(lease.key) != lease.token:
            return False
        del self._leases[lease.key]
        return True
