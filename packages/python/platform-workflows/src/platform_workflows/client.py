"""Temporal client creation and lazy process ownership."""

import asyncio
from dataclasses import dataclass, field

from temporalio.client import Client


@dataclass(frozen=True, slots=True)
class TemporalClientConfig:
    """Trusted internal Temporal connection configuration."""

    address: str
    namespace: str = "default"
    connect_timeout_seconds: float = 5.0
    api_key: str | None = field(default=None, repr=False)
    tls: bool = False

    def __post_init__(self) -> None:
        if not self.address or ":" not in self.address:
            raise ValueError("Temporal address must contain a host and port")
        if not self.namespace:
            raise ValueError("Temporal namespace must not be blank")
        if not 0 < self.connect_timeout_seconds <= 60:
            raise ValueError("Temporal connect timeout must be between 0 and 60 seconds")


async def create_temporal_client(config: TemporalClientConfig) -> Client:
    """Create a bounded Temporal connection without exposing credentials."""
    async with asyncio.timeout(config.connect_timeout_seconds):
        return await Client.connect(
            config.address,
            namespace=config.namespace,
            api_key=config.api_key,
            tls=config.tls,
        )


class TemporalClientProvider:
    """Lazily create and share one concurrency-safe client per process."""

    def __init__(self, config: TemporalClientConfig) -> None:
        self._config = config
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> Client:
        """Return the existing client or connect on first actual use."""
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                self._client = await create_temporal_client(self._config)
            return self._client
