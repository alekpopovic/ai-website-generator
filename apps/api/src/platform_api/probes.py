"""Bounded dependency health probes with deterministic fake implementations."""

from __future__ import annotations

import asyncio
import ssl
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from urllib.parse import unquote, urlsplit

from platform_clients.llm.models import ModelRole
from platform_clients.llm.protocols import LLMGateway
from platform_clients.object_storage.models import ObjectStorage
from platform_clients.vector_store.models import CollectionIdentity
from platform_clients.vector_store.protocols import VectorStore
from pydantic import BaseModel, ConfigDict, Field

from platform_api.config import Settings
from platform_api.database import DatabaseManager
from platform_api.logging import get_logger


class DependencyState(StrEnum):
    """Public state vocabulary used by dependency health endpoints."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class DependencyCheck(BaseModel):
    """Sanitized result of one bounded dependency probe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    state: DependencyState
    critical: bool
    latency_ms: float = Field(ge=0)
    detail: str | None = None


class DependencyProbe(Protocol):
    """Explicit health-check boundary implemented by real and fake dependencies."""

    @property
    def name(self) -> str:
        """Return the stable dependency name."""
        ...

    @property
    def critical(self) -> bool:
        """Return whether this dependency gates API readiness."""
        ...

    async def check(self) -> DependencyCheck:
        """Return one non-throwing, non-secret-bearing health result."""
        ...


ProbeFunction = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class FunctionProbe:
    """Convert a bounded async function into a sanitized dependency probe."""

    name: str
    critical: bool
    function: ProbeFunction

    async def check(self) -> DependencyCheck:
        """Measure a check and collapse internal exceptions into safe state."""
        started = time.perf_counter()
        try:
            await self.function()
        except Exception as error:  # Dependency libraries expose unrelated exception hierarchies.
            get_logger().warning(
                "dependency_probe_failed",
                dependency=self.name,
                error_type=type(error).__name__,
            )
            state = DependencyState.UNAVAILABLE
            detail: str | None = "Health check failed."
        else:
            state = DependencyState.AVAILABLE
            detail = None
        return DependencyCheck(
            name=self.name,
            state=state,
            critical=self.critical,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            detail=detail,
        )


class ProbeRegistry:
    """Own the dependency probe set and run checks concurrently."""

    def __init__(self, probes: Sequence[DependencyProbe]) -> None:
        names = [probe.name for probe in probes]
        if len(names) != len(set(names)):
            raise ValueError("Dependency probe names must be unique")
        self._probes = tuple(probes)

    async def check(self, *, critical_only: bool = False) -> tuple[DependencyCheck, ...]:
        """Run selected checks concurrently while retaining declaration order."""
        selected = [probe for probe in self._probes if probe.critical or not critical_only]
        return tuple(await asyncio.gather(*(probe.check() for probe in selected)))


def fake_probe_registry() -> ProbeRegistry:
    """Return deterministic healthy probes for CI and unit tests."""

    async def healthy() -> None:
        return None

    return ProbeRegistry(
        [
            FunctionProbe(name="database", critical=True, function=healthy),
            FunctionProbe(name="redis", critical=True, function=healthy),
            FunctionProbe(name="temporal", critical=True, function=healthy),
            FunctionProbe(name="minio", critical=True, function=healthy),
            FunctionProbe(name="qdrant", critical=False, function=healthy),
            FunctionProbe(name="ollama", critical=False, function=healthy),
        ]
    )


def real_probe_registry(
    settings: Settings,
    database: DatabaseManager | None,
    object_storage: ObjectStorage,
    llm_gateway: LLMGateway,
    vector_store: VectorStore,
) -> ProbeRegistry:
    """Compose real probes without performing I/O during startup."""

    async def database_check() -> None:
        if database is None:
            raise RuntimeError("Database is not configured")
        await database.check_health()

    async def redis_check() -> None:
        if settings.redis.url is None:
            raise RuntimeError("Redis is not configured")
        await _redis_ping(
            settings.redis.url.get_secret_value(),
            settings.redis.connect_timeout_seconds,
        )

    async def temporal_check() -> None:
        await _tcp_check(
            settings.temporal.address,
            settings.temporal.connect_timeout_seconds,
        )

    async def minio_check() -> None:
        readiness = await object_storage.readiness()
        if not all(bucket.ready for bucket in readiness):
            raise RuntimeError("one or more object-storage buckets are unavailable")

    async def qdrant_check() -> None:
        health = await vector_store.health()
        if not health.available:
            raise RuntimeError("vector service is unavailable")
        metadata = await llm_gateway.model_metadata(ModelRole.EMBEDDING)
        if metadata.embedding_dimensions is None:
            raise RuntimeError("embedding dimensions are absent from model metadata")
        readiness = await vector_store.readiness(
            CollectionIdentity(
                embedding_provider=metadata.provider,
                embedding_model=metadata.name,
                embedding_model_digest=metadata.digest,
                serialization_schema_version=settings.qdrant.serialization_schema_version,
                vector_name=settings.qdrant.vector_name,
            ),
            metadata.embedding_dimensions,
        )
        if not readiness.ready:
            raise RuntimeError("versioned vector collection is not ready")

    async def ollama_check() -> None:
        readiness = await llm_gateway.readiness()
        if not all(model.installed and model.capable for model in readiness):
            raise RuntimeError("one or more configured inference models are unavailable")

    return ProbeRegistry(
        [
            FunctionProbe("database", True, database_check),
            FunctionProbe("redis", True, redis_check),
            FunctionProbe("temporal", True, temporal_check),
            FunctionProbe("minio", True, minio_check),
            FunctionProbe("qdrant", False, qdrant_check),
            FunctionProbe("ollama", False, ollama_check),
        ]
    )


async def _tcp_check(address: str, timeout_seconds: float) -> None:
    """Perform a bounded TCP reachability check for a trusted service address."""
    parsed = urlsplit(f"tcp://{address}")
    if parsed.hostname is None or parsed.port is None:
        raise ValueError("Service address must contain a host and port")
    async with asyncio.timeout(timeout_seconds):
        _, writer = await asyncio.open_connection(parsed.hostname, parsed.port)
        writer.close()
        await writer.wait_closed()


async def _redis_ping(url: str, timeout_seconds: float) -> None:
    """Authenticate when configured and issue a bounded Redis PING."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"redis", "rediss"} or parsed.hostname is None:
        raise ValueError("Redis URL must use redis:// or rediss://")
    port = parsed.port or (6380 if parsed.scheme == "rediss" else 6379)
    tls_context = ssl.create_default_context() if parsed.scheme == "rediss" else None
    async with asyncio.timeout(timeout_seconds):
        reader, writer = await asyncio.open_connection(parsed.hostname, port, ssl=tls_context)
        try:
            if parsed.password is not None:
                auth_parts = ["AUTH"]
                if parsed.username:
                    auth_parts.append(unquote(parsed.username))
                auth_parts.append(unquote(parsed.password))
                await _redis_command(reader, writer, auth_parts, expected="+OK")
            await _redis_command(reader, writer, ["PING"], expected="+PONG")
        finally:
            writer.close()
            await writer.wait_closed()


async def _redis_command(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    parts: Sequence[str],
    *,
    expected: str,
) -> None:
    """Send one fixed Redis health command using RESP framing."""
    encoded_parts = [part.encode() for part in parts]
    payload = [f"*{len(encoded_parts)}\r\n".encode()]
    for part in encoded_parts:
        payload.extend((f"${len(part)}\r\n".encode(), part, b"\r\n"))
    writer.writelines(payload)
    await writer.drain()
    response = (await reader.readline()).decode(errors="replace").rstrip("\r\n")
    if response != expected:
        raise RuntimeError("Redis health command failed")
