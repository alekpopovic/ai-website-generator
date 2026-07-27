"""Application-owned resource lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

import httpx2
from platform_clients.object_storage.fake import InMemoryObjectStorage
from platform_clients.object_storage.models import ObjectStorage, StorageConfig, StorageProvider
from platform_clients.object_storage.s3 import S3ObjectStorage
from platform_workflows.client import TemporalClientConfig, TemporalClientProvider
from platform_workflows.dispatcher import (
    FakeWorkflowDispatcher,
    TemporalWorkflowDispatcher,
    WorkflowDispatcher,
)
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
    temporal_clients: TemporalClientProvider | None
    workflow_dispatcher: WorkflowDispatcher
    object_storage: ObjectStorage

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
            object_storage: ObjectStorage = InMemoryObjectStorage()
        else:
            minio = settings.minio
            object_storage = await S3ObjectStorage.create(
                StorageConfig(
                    provider=StorageProvider(minio.provider),
                    region=minio.region,
                    endpoint_url=str(minio.endpoint).rstrip("/") if minio.endpoint else None,
                    access_key=(
                        minio.access_key.get_secret_value()
                        if minio.access_key is not None
                        else None
                    ),
                    secret_key=(
                        minio.secret_key.get_secret_value()
                        if minio.secret_key is not None
                        else None
                    ),
                    session_token=(
                        minio.session_token.get_secret_value()
                        if minio.session_token is not None
                        else None
                    ),
                    connect_timeout_seconds=minio.connect_timeout_seconds,
                    read_timeout_seconds=minio.read_timeout_seconds,
                    multipart_part_size=minio.multipart_part_size,
                )
            )
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
        temporal_clients: TemporalClientProvider | None = None
        if settings.application.fake_dependencies:
            workflow_dispatcher: WorkflowDispatcher = FakeWorkflowDispatcher()
        else:
            temporal_clients = TemporalClientProvider(
                TemporalClientConfig(
                    address=settings.temporal.address,
                    namespace=settings.temporal.namespace,
                    connect_timeout_seconds=settings.temporal.connect_timeout_seconds,
                )
            )
            workflow_dispatcher = TemporalWorkflowDispatcher(temporal_clients)
        probes = (
            fake_probe_registry()
            if settings.application.fake_dependencies
            else real_probe_registry(settings, database, http_client, object_storage)
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
            temporal_clients=temporal_clients,
            workflow_dispatcher=workflow_dispatcher,
            object_storage=object_storage,
        )

    async def close(self) -> None:
        """Close resources in reverse ownership order."""
        await self.object_storage.close()
        if self.database is not None:
            await self.database.close()
        if self.redis is not None:
            await self.redis.aclose()
        await self.http_client.aclose()
        await self.telemetry.shutdown()
