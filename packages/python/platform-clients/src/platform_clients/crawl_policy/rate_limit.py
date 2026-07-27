"""Atomic per-domain token-bucket rate limiting."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class TokenBucketResult:
    allowed: bool
    retry_after_seconds: float
    remaining_tokens: float


class DomainRateLimiter(Protocol):
    async def acquire(self, domain: str, *, cost: float = 1.0) -> TokenBucketResult: ...


class RedisDomainRateLimiter:
    """Redis TIME-based bucket shared by crawler processes."""

    _SCRIPT = """
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) + tonumber(now_parts[2]) / 1000000
local values = redis.call('HMGET', KEYS[1], 'tokens', 'updated')
local tokens = tonumber(values[1]) or tonumber(ARGV[1])
local updated = tonumber(values[2]) or now
tokens = math.min(tonumber(ARGV[1]), tokens + math.max(0, now - updated) * tonumber(ARGV[2]))
local allowed = 0
local retry = 0
if tokens >= tonumber(ARGV[3]) then
  tokens = tokens - tonumber(ARGV[3])
  allowed = 1
else
  retry = (tonumber(ARGV[3]) - tokens) / tonumber(ARGV[2])
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated', now)
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
return {allowed, tostring(retry), tostring(tokens)}
"""

    def __init__(
        self, redis: Redis, *, prefix: str, capacity: int, refill_per_second: float
    ) -> None:
        if capacity < 1 or refill_per_second <= 0:
            raise ValueError("token bucket capacity and refill rate must be positive")
        self._redis = redis
        self._prefix = prefix
        self._capacity = capacity
        self._refill = refill_per_second

    async def acquire(self, domain: str, *, cost: float = 1.0) -> TokenBucketResult:
        if not 0 < cost <= self._capacity:
            raise ValueError("token cost must be positive and no greater than capacity")
        ttl = max(int(self._capacity / self._refill * 2), 60)
        raw = cast(
            list[bytes | int],
            await self._redis.eval(
                self._SCRIPT,
                1,
                self._key(domain),
                self._capacity,
                self._refill,
                cost,
                ttl,
            ),
        )
        return TokenBucketResult(
            allowed=int(raw[0]) == 1,
            retry_after_seconds=float(raw[1]),
            remaining_tokens=float(raw[2]),
        )

    def _key(self, domain: str) -> str:
        digest = hashlib.sha256(domain.casefold().encode()).hexdigest()
        return f"{self._prefix}:crawl:rate:{digest}"


class InMemoryDomainRateLimiter:
    def __init__(
        self,
        *,
        capacity: int,
        refill_per_second: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacity = capacity
        self._refill = refill_per_second
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}

    async def acquire(self, domain: str, *, cost: float = 1.0) -> TokenBucketResult:
        now = self._clock()
        tokens, updated = self._buckets.get(domain, (float(self._capacity), now))
        tokens = min(float(self._capacity), tokens + max(0.0, now - updated) * self._refill)
        allowed = tokens >= cost
        retry = 0.0 if allowed else (cost - tokens) / self._refill
        if allowed:
            tokens -= cost
        self._buckets[domain] = (tokens, now)
        return TokenBucketResult(allowed, retry, tokens)
