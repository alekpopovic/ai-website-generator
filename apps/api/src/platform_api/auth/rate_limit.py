"""Distributed and deterministic fake login rate limits."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Protocol, cast

from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Current fixed-window decision."""

    allowed: bool
    retry_after_seconds: int


class LoginRateLimiter(Protocol):
    """Rate-limit boundary keyed by a non-reversible login fingerprint."""

    async def check(self, *, email: str, client_ip: str) -> RateLimitResult: ...

    async def reset(self, *, email: str, client_ip: str) -> None: ...


class RedisLoginRateLimiter:
    """Atomic fixed-window limiter shared by every API process."""

    _SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""

    def __init__(
        self, redis: Redis, *, prefix: str, attempts: int, window_seconds: int, key_secret: bytes
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._attempts = attempts
        self._window_seconds = window_seconds
        self._key_secret = key_secret

    async def check(self, *, email: str, client_ip: str) -> RateLimitResult:
        key = self._key(email, client_ip)
        result = cast(list[int], await self._redis.eval(self._SCRIPT, 1, key, self._window_seconds))
        attempts, ttl = result
        return RateLimitResult(
            allowed=attempts <= self._attempts,
            retry_after_seconds=max(ttl, 1),
        )

    async def reset(self, *, email: str, client_ip: str) -> None:
        await self._redis.delete(self._key(email, client_ip))

    def _key(self, email: str, client_ip: str) -> str:
        fingerprint = hmac.new(
            self._key_secret, f"{email}|{client_ip}".encode(), hashlib.sha256
        ).hexdigest()
        return f"{self._prefix}:auth:login:{fingerprint}"


class InMemoryLoginRateLimiter:
    """Process-local deterministic limiter used only by fake dependency mode."""

    def __init__(self, *, attempts: int, window_seconds: int) -> None:
        self._attempts = attempts
        self._window_seconds = window_seconds
        self._entries: dict[str, tuple[int, float]] = {}

    async def check(self, *, email: str, client_ip: str) -> RateLimitResult:
        key = f"{email}|{client_ip}"
        now = time.monotonic()
        count, expires = self._entries.get(key, (0, now + self._window_seconds))
        if expires <= now:
            count, expires = 0, now + self._window_seconds
        count += 1
        self._entries[key] = (count, expires)
        return RateLimitResult(
            allowed=count <= self._attempts,
            retry_after_seconds=max(int(expires - now), 1),
        )

    async def reset(self, *, email: str, client_ip: str) -> None:
        self._entries.pop(f"{email}|{client_ip}", None)


class UnavailableLoginRateLimiter:
    """Fail closed when a deployed API has no configured Redis connection."""

    async def check(self, *, email: str, client_ip: str) -> RateLimitResult:
        del email, client_ip
        raise RuntimeError("login rate limiter is unavailable")

    async def reset(self, *, email: str, client_ip: str) -> None:
        del email, client_ip
