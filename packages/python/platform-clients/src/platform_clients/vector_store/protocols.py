"""Provider-neutral vector storage protocol."""

from typing import Protocol
from uuid import UUID

from platform_clients.vector_store.models import (
    CollectionIdentity,
    CollectionStatistics,
    ScrollPage,
    VectorMatch,
    VectorPoint,
    VectorQuery,
    VectorStoreHealth,
    VectorStoreReadiness,
)


class VectorStore(Protocol):
    """Async collection lifecycle, mutation, and retrieval boundary."""

    async def health(self) -> VectorStoreHealth: ...

    async def readiness(
        self, identity: CollectionIdentity, dimensions: int
    ) -> VectorStoreReadiness: ...

    async def prepare_collection(
        self, identity: CollectionIdentity, dimensions: int
    ) -> CollectionStatistics: ...

    async def promote_collection(self, identity: CollectionIdentity) -> CollectionStatistics: ...

    async def statistics(
        self, identity: CollectionIdentity | None = None
    ) -> CollectionStatistics: ...

    async def upsert_points(
        self, identity: CollectionIdentity, points: tuple[VectorPoint, ...]
    ) -> None: ...

    async def delete_points(self, point_ids: tuple[UUID, ...]) -> None: ...

    async def query(self, request: VectorQuery) -> tuple[VectorMatch, ...]: ...

    async def scroll(self, *, offset: str | int | None = None, limit: int = 256) -> ScrollPage: ...

    async def close(self) -> None: ...
