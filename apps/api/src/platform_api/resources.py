"""Application-owned resource lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

import httpx2
from redis.asyncio import Redis

from platform_api.auth.mail import (
    AuthenticationMailer,
    InMemoryAuthenticationMailer,
    SmtpAuthenticationMailer,
)
from platform_api.auth.rate_limit import (
    InMemoryLoginRateLimiter,
    LoginRateLimiter,
    RedisLoginRateLimiter,
    UnavailableLoginRateLimiter,
)
from platform_api.auth.security import AccessTokenManager, AsyncPasswordManager
from platform_api.config import Settings
from platform_api.database import DatabaseManager
from platform_api.probes import ProbeRegistry, fake_probe_registry, real_probe_registry
from platform_api.telemetry import Telemetry


@dataclass(slots=True)
class ApplicationResources:
    """Resources initialized and released by the FastAPI lifespan."""

    database: DatabaseManager | None
    http_client: httpx2.AsyncClient
    probes: ProbeRegistry
    telemetry: Telemetry
    redis: Redis | None
    login_rate_limiter: LoginRateLimiter
    authentication_mailer: AuthenticationMailer
    password_manager: AsyncPasswordManager
    access_tokens: AccessTokenManager | None

    @classmethod
    async def create(cls, settings: Settings, telemetry: Telemetry) -> ApplicationResources:
        """Initialize clients without checking external dependency availability."""
        await telemetry.startup()
        http_client = httpx2.AsyncClient(
            follow_redirects=False,
            trust_env=False,
            limits=httpx2.Limits(max_connections=20, max_keepalive_connections=10),
        )
        database = None
        if not settings.application.fake_dependencies and settings.database.url is not None:
            database = DatabaseManager(settings.database)
        redis: Redis | None = None
        if settings.application.fake_dependencies:
            login_rate_limiter: LoginRateLimiter = InMemoryLoginRateLimiter(
                attempts=settings.security.login_rate_limit_attempts,
                window_seconds=settings.security.login_rate_limit_window_seconds,
            )
            authentication_mailer: AuthenticationMailer = InMemoryAuthenticationMailer()
        else:
            if settings.redis.url is None:
                login_rate_limiter = UnavailableLoginRateLimiter()
            else:
                redis = Redis.from_url(
                    settings.redis.url.get_secret_value(),
                    socket_connect_timeout=settings.redis.connect_timeout_seconds,
                    socket_timeout=settings.redis.connect_timeout_seconds,
                    decode_responses=False,
                )
                key_secret = (
                    settings.security.access_token_secret.get_secret_value().encode()
                    if settings.security.access_token_secret is not None
                    else b"unconfigured-authentication-key"
                )
                login_rate_limiter = RedisLoginRateLimiter(
                    redis,
                    prefix=settings.redis.key_prefix,
                    attempts=settings.security.login_rate_limit_attempts,
                    window_seconds=settings.security.login_rate_limit_window_seconds,
                    key_secret=key_secret,
                )
            authentication_mailer = SmtpAuthenticationMailer(settings.email)
        access_tokens = (
            AccessTokenManager(settings.security)
            if settings.security.access_token_secret is not None
            else None
        )
        probes = (
            fake_probe_registry()
            if settings.application.fake_dependencies
            else real_probe_registry(settings, database, http_client)
        )
        return cls(
            database=database,
            http_client=http_client,
            probes=probes,
            telemetry=telemetry,
            redis=redis,
            login_rate_limiter=login_rate_limiter,
            authentication_mailer=authentication_mailer,
            password_manager=AsyncPasswordManager(),
            access_tokens=access_tokens,
        )

    async def close(self) -> None:
        """Close resources in reverse ownership order."""
        if self.database is not None:
            await self.database.close()
        if self.redis is not None:
            await self.redis.aclose()
        await self.http_client.aclose()
        await self.telemetry.shutdown()
