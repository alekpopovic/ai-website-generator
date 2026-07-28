"""Deterministic in-memory vector store for unit tests and offline CI."""

from __future__ import annotations

import math
from collections import Counter
from uuid import UUID

from platform_clients.vector_store.models import (
    CollectionIdentity,
    CollectionStatistics,
    DesignPatternPayload,
    DiversityField,
    PayloadFilter,
    ScrollPage,
    VectorMatch,
    VectorPoint,
    VectorQuery,
    VectorStoreHealth,
    VectorStoreReadiness,
)


class InMemoryVectorStore:
    """A behaviorally representative store with no network or external state."""

    def __init__(self, *, alias: str = "design-patterns") -> None:
        self.alias = alias
        self._collections: dict[str, dict[UUID, VectorPoint]] = {}
        self._identities: dict[str, CollectionIdentity] = {}
        self._dimensions: dict[str, int] = {}
        self._active: str | None = None

    async def health(self) -> VectorStoreHealth:
        return VectorStoreHealth(available=True)

    async def readiness(
        self, identity: CollectionIdentity, dimensions: int
    ) -> VectorStoreReadiness:
        expected = identity.physical_name(self.alias)
        return VectorStoreReadiness(
            ready=self._active == expected and self._dimensions.get(expected) == dimensions,
            alias=self.alias,
            expected_collection=expected,
            active_collection=self._active,
            dimensions_match=self._dimensions.get(self._active or "") == dimensions,
            identity_match=self._active == expected,
            detail=None if self._active == expected else "Expected collection alias is not active.",
        )

    async def prepare_collection(
        self, identity: CollectionIdentity, dimensions: int
    ) -> CollectionStatistics:
        if not 1 <= dimensions <= 65_536:
            raise ValueError("embedding dimensions must be between 1 and 65536")
        name = identity.physical_name(self.alias)
        existing = self._dimensions.get(name)
        if existing is not None and existing != dimensions:
            raise ValueError("collection already exists with different dimensions")
        self._collections.setdefault(name, {})
        self._dimensions[name] = dimensions
        self._identities[name] = identity
        return await self.statistics(identity)

    async def promote_collection(self, identity: CollectionIdentity) -> CollectionStatistics:
        name = identity.physical_name(self.alias)
        if name not in self._collections:
            raise ValueError("collection must be prepared before promotion")
        self._active = name
        return await self.statistics(identity)

    async def statistics(self, identity: CollectionIdentity | None = None) -> CollectionStatistics:
        name = identity.physical_name(self.alias) if identity is not None else self._active
        points = self._collections.get(name or "", {})
        resolved_identity = identity or self._identities.get(name or "")
        return CollectionStatistics(
            alias=self.alias,
            physical_collection=name,
            status="green" if name in self._collections else "missing",
            ready=name is not None and name in self._collections,
            vector_name=(resolved_identity.vector_name if resolved_identity else "design-pattern"),
            dimensions=self._dimensions.get(name or ""),
            points_count=len(points),
            indexed_vectors_count=len(points),
            identity=resolved_identity,
        )

    async def upsert_points(
        self, identity: CollectionIdentity, points: tuple[VectorPoint, ...]
    ) -> None:
        if not points or len(points) > 1_000:
            raise ValueError("upsert batch size must be between 1 and 1000")
        name = identity.physical_name(self.alias)
        dimensions = self._dimensions.get(name)
        if dimensions is None:
            raise ValueError("target collection is not prepared")
        if any(len(point.vector) != dimensions for point in points):
            raise ValueError("point dimensions do not match the collection")
        self._collections[name].update({point.point_id: point for point in points})

    async def delete_points(
        self,
        point_ids: tuple[UUID, ...],
        identity: CollectionIdentity | None = None,
        physical_collection: str | None = None,
    ) -> None:
        if not point_ids or len(point_ids) > 1_000:
            raise ValueError("delete batch size must be between 1 and 1000")
        collection = physical_collection or (
            identity.physical_name(self.alias) if identity is not None else self._active
        )
        if collection is None:
            raise ValueError("collection alias is not active")
        for point_id in point_ids:
            self._collections.get(collection, {}).pop(point_id, None)

    async def query(self, request: VectorQuery) -> tuple[VectorMatch, ...]:
        if self._active is None:
            raise ValueError("collection alias is not active")
        dimensions = self._dimensions[self._active]
        if len(request.vector) != dimensions:
            raise ValueError("query dimensions do not match the collection")
        candidates: list[VectorMatch] = []
        for point in self._collections[self._active].values():
            if not _matches_filter(point.payload, request.filters):
                continue
            score = _cosine_similarity(request.vector, point.vector)
            if request.score_threshold is not None and score < request.score_threshold:
                continue
            candidates.append(
                VectorMatch(
                    point_id=point.point_id,
                    score=score,
                    abstract_pattern_text=point.abstract_pattern_text,
                    payload=point.payload,
                )
            )
        candidates.sort(key=lambda item: (-item.score, str(item.point_id)))
        if request.diversity is None:
            return tuple(candidates[: request.limit])
        selected: list[VectorMatch] = []
        counts: Counter[str] = Counter()
        for item in candidates:
            key = (
                item.payload.source_domain
                if request.diversity.field is DiversityField.SOURCE_DOMAIN
                else str(item.payload.source_website_id)
            )
            if counts[key] >= request.diversity.maximum_per_source:
                continue
            counts[key] += 1
            selected.append(item)
            if len(selected) == request.limit:
                break
        return tuple(selected)

    async def scroll(self, *, offset: str | int | None = None, limit: int = 256) -> ScrollPage:
        if not 1 <= limit <= 1_000:
            raise ValueError("scroll limit must be between 1 and 1000")
        if self._active is None:
            return ScrollPage(points=())
        ordered = sorted(
            self._collections[self._active].values(), key=lambda item: str(item.point_id)
        )
        start = int(offset) if offset is not None else 0
        page = ordered[start : start + limit]
        next_offset = start + len(page) if start + len(page) < len(ordered) else None
        return ScrollPage(
            points=tuple(
                (point.point_id, point.abstract_pattern_text, point.payload) for point in page
            ),
            next_offset=next_offset,
        )

    async def close(self) -> None:
        return None


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _matches_filter(payload: DesignPatternPayload, filters: PayloadFilter) -> bool:
    checks = (
        payload.project_id == filters.project_id,
        not filters.dataset_ids or payload.dataset_id in filters.dataset_ids,
        not filters.dataset_version_ids
        or payload.dataset_version_id in filters.dataset_version_ids,
        not filters.source_domains or payload.source_domain in filters.source_domains,
        not filters.source_website_ids or payload.source_website_id in filters.source_website_ids,
        not filters.categories or payload.category in filters.categories,
        not filters.page_types or payload.page_type in filters.page_types,
        not filters.section_types or payload.section_type in filters.section_types,
        not filters.layouts or payload.layout in filters.layouts,
        not filters.style_tags or bool(set(payload.style_tags) & set(filters.style_tags)),
        not filters.languages or payload.language in filters.languages,
        filters.minimum_confidence is None or payload.confidence >= filters.minimum_confidence,
        payload.approved is filters.approved,
        not filters.provenance_statuses or payload.provenance_status in filters.provenance_statuses,
    )
    return all(checks)
