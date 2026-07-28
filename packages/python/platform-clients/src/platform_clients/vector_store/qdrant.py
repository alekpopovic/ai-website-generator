"""Asynchronous Qdrant REST adapter for abstract design-pattern vectors."""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx2
from pydantic import TypeAdapter, ValidationError

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

_COLLECTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,239}$")
_JSON_OBJECT = TypeAdapter(dict[str, Any])


class VectorStoreError(RuntimeError):
    """A sanitized provider-neutral vector storage failure."""


class VectorStoreUnavailableError(VectorStoreError):
    """The vector service could not complete a bounded request."""


class CollectionConfigurationError(VectorStoreError):
    """An existing collection conflicts with the requested identity."""


class MalformedVectorResponseError(VectorStoreError):
    """Qdrant returned an unexpected response contract."""


@dataclass(frozen=True, slots=True)
class QdrantConfig:
    base_url: str
    api_key: str | None = None
    collection_alias: str = "design-patterns"
    vector_name: str = "design-pattern"
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 30.0
    max_concurrency: int = 8
    max_batch_size: int = 256

    def __post_init__(self) -> None:
        endpoint = urlsplit(self.base_url)
        if (
            endpoint.scheme not in {"http", "https"}
            or endpoint.hostname is None
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
            or endpoint.path not in {"", "/"}
        ):
            raise ValueError("base_url must be a credential-free HTTP(S) service root")
        if _COLLECTION_NAME.fullmatch(self.collection_alias) is None:
            raise ValueError("collection_alias is invalid")
        if _COLLECTION_NAME.fullmatch(self.vector_name) is None or len(self.vector_name) > 64:
            raise ValueError("vector_name is invalid")
        if min(self.connect_timeout_seconds, self.request_timeout_seconds) <= 0:
            raise ValueError("Qdrant timeouts must be positive")
        if not 1 <= self.max_concurrency <= 64:
            raise ValueError("Qdrant concurrency must be between 1 and 64")
        if not 1 <= self.max_batch_size <= 1_000:
            raise ValueError("Qdrant batch size must be between 1 and 1000")


class QdrantVectorStore:
    """Qdrant implementation using named dense vectors and atomic aliases."""

    def __init__(
        self,
        config: QdrantConfig,
        client: httpx2.AsyncClient,
        *,
        owns_client: bool = False,
    ) -> None:
        self._config = config
        self._client = client
        self._owns_client = owns_client
        self._semaphore = asyncio.Semaphore(config.max_concurrency)

    @classmethod
    def create(cls, config: QdrantConfig) -> QdrantVectorStore:
        client = httpx2.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers={"api-key": config.api_key} if config.api_key else None,
            timeout=httpx2.Timeout(
                config.request_timeout_seconds,
                connect=config.connect_timeout_seconds,
            ),
            follow_redirects=False,
            trust_env=False,
            limits=httpx2.Limits(
                max_connections=config.max_concurrency,
                max_keepalive_connections=config.max_concurrency,
            ),
        )
        return cls(config, client, owns_client=True)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: Literal["GET", "PUT", "POST"],
        path: str,
        *,
        payload: dict[str, object] | None = None,
        accepted: frozenset[int] = frozenset({200}),
    ) -> tuple[int, dict[str, Any] | None]:
        try:
            async with self._semaphore, asyncio.timeout(self._config.request_timeout_seconds):
                response = await self._client.request(method, path, json=payload)
        except (httpx2.TransportError, TimeoutError) as error:
            raise VectorStoreUnavailableError("vector service request failed") from error
        if response.status_code not in accepted:
            raise VectorStoreUnavailableError(
                f"vector service rejected a request with status {response.status_code}"
            )
        if not response.content:
            return response.status_code, None
        if len(response.content) > 8_388_608:
            raise MalformedVectorResponseError("vector service response is too large")
        try:
            return response.status_code, _JSON_OBJECT.validate_python(response.json())
        except (ValueError, ValidationError) as error:
            raise MalformedVectorResponseError("vector service returned malformed JSON") from error

    @staticmethod
    def _path_name(name: str) -> str:
        if _COLLECTION_NAME.fullmatch(name) is None:
            raise ValueError("collection name is invalid")
        return quote(name, safe="")

    async def health(self) -> VectorStoreHealth:
        try:
            # The collections endpoint is authenticated and JSON across supported Qdrant versions;
            # `/healthz` may return plain text and would not exercise API-key authorization.
            await self._request("GET", "/collections")
        except VectorStoreError:
            return VectorStoreHealth(available=False, detail="Vector service is unavailable.")
        return VectorStoreHealth(available=True)

    async def readiness(
        self, identity: CollectionIdentity, dimensions: int
    ) -> VectorStoreReadiness:
        expected = identity.physical_name(self._config.collection_alias)
        try:
            active = await self._active_collection()
            statistics = await self.statistics(identity if active == expected else None)
        except VectorStoreError:
            return VectorStoreReadiness(
                ready=False,
                alias=self._config.collection_alias,
                expected_collection=expected,
                active_collection=None,
                dimensions_match=False,
                identity_match=False,
                detail="Vector collection readiness check failed.",
            )
        dimension_match = statistics.dimensions == dimensions
        identity_match = active == expected
        return VectorStoreReadiness(
            ready=statistics.ready and dimension_match and identity_match,
            alias=self._config.collection_alias,
            expected_collection=expected,
            active_collection=active,
            dimensions_match=dimension_match,
            identity_match=identity_match,
            detail=(
                None
                if statistics.ready and dimension_match and identity_match
                else "Active vector collection does not match configured embedding identity."
            ),
        )

    async def prepare_collection(
        self, identity: CollectionIdentity, dimensions: int
    ) -> CollectionStatistics:
        if not 1 <= dimensions <= 65_536:
            raise ValueError("embedding dimensions must be between 1 and 65536")
        name = identity.physical_name(self._config.collection_alias)
        path = self._path_name(name)
        status_code, _ = await self._request(
            "GET", f"/collections/{path}", accepted=frozenset({200, 404})
        )
        if status_code == 404:
            await self._request(
                "PUT",
                f"/collections/{path}",
                payload={
                    "vectors": {identity.vector_name: {"size": dimensions, "distance": "Cosine"}}
                },
            )
        statistics = await self.statistics(identity)
        if statistics.dimensions != dimensions or statistics.vector_name != identity.vector_name:
            raise CollectionConfigurationError(
                "collection vector name or dimensions conflict with the embedding model"
            )
        await self._ensure_payload_indexes(name)
        return statistics

    async def _ensure_payload_indexes(self, collection: str) -> None:
        path = self._path_name(collection)
        for field, schema in (
            ("project_id", "uuid"),
            ("dataset_id", "uuid"),
            ("dataset_version_id", "uuid"),
            ("source_website_id", "uuid"),
            ("source_domain", "keyword"),
            ("category", "keyword"),
            ("page_type", "keyword"),
            ("section_type", "keyword"),
            ("layout", "keyword"),
            ("style_tags", "keyword"),
            ("language", "keyword"),
            ("approved", "bool"),
            ("provenance_status", "keyword"),
        ):
            await self._request(
                "PUT",
                f"/collections/{path}/index?wait=true",
                payload={"field_name": field, "field_schema": schema},
                accepted=frozenset({200, 409}),
            )

    async def promote_collection(self, identity: CollectionIdentity) -> CollectionStatistics:
        target = identity.physical_name(self._config.collection_alias)
        await self.statistics(identity)
        active = await self._active_collection()
        if active != target:
            actions: list[dict[str, dict[str, str]]] = []
            if active is not None:
                actions.append({"delete_alias": {"alias_name": self._config.collection_alias}})
            actions.append(
                {
                    "create_alias": {
                        "collection_name": target,
                        "alias_name": self._config.collection_alias,
                    }
                }
            )
            await self._request("POST", "/collections/aliases", payload={"actions": actions})
        return await self.statistics(identity)

    async def _active_collection(self) -> str | None:
        alias = self._path_name(self._config.collection_alias)
        status, body = await self._request(
            "GET", f"/aliases/{alias}", accepted=frozenset({200, 404})
        )
        if status == 404 or body is None:
            return None
        result = body.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("aliases"), list):
            raise MalformedVectorResponseError("alias response has an invalid shape")
        aliases = result["aliases"]
        if not aliases:
            return None
        first = aliases[0]
        if not isinstance(first, dict) or not isinstance(first.get("collection_name"), str):
            raise MalformedVectorResponseError("alias target has an invalid shape")
        return cast(str, first["collection_name"])

    async def statistics(self, identity: CollectionIdentity | None = None) -> CollectionStatistics:
        collection = (
            identity.physical_name(self._config.collection_alias)
            if identity is not None
            else await self._active_collection()
        )
        vector_name = identity.vector_name if identity is not None else self._config.vector_name
        if collection is None:
            return CollectionStatistics(
                alias=self._config.collection_alias,
                physical_collection=None,
                status="missing",
                ready=False,
                vector_name=vector_name,
                identity=identity,
            )
        status, body = await self._request(
            "GET",
            f"/collections/{self._path_name(collection)}",
            accepted=frozenset({200, 404}),
        )
        if status == 404 or body is None:
            return CollectionStatistics(
                alias=self._config.collection_alias,
                physical_collection=collection,
                status="missing",
                ready=False,
                vector_name=vector_name,
                identity=identity,
            )
        result = body.get("result")
        if not isinstance(result, dict):
            raise MalformedVectorResponseError("collection response has an invalid shape")
        vectors = _nested(result, "config", "params", "vectors")
        if not isinstance(vectors, dict):
            raise MalformedVectorResponseError("collection vectors have an invalid shape")
        if identity is None and len(vectors) == 1:
            vector_name = next(iter(vectors))
        vector_config = vectors.get(vector_name)
        dimensions = vector_config.get("size") if isinstance(vector_config, dict) else None
        if not isinstance(dimensions, int):
            dimensions = None
        collection_status = result.get("status", "unknown")
        points_count = result.get("points_count", 0)
        indexed_count = result.get("indexed_vectors_count", 0)
        return CollectionStatistics(
            alias=self._config.collection_alias,
            physical_collection=collection,
            status=str(collection_status),
            ready=collection_status in {"green", "yellow"} and dimensions is not None,
            vector_name=vector_name,
            dimensions=dimensions,
            points_count=points_count if isinstance(points_count, int) else 0,
            indexed_vectors_count=indexed_count if isinstance(indexed_count, int) else 0,
            identity=identity,
        )

    async def upsert_points(
        self, identity: CollectionIdentity, points: tuple[VectorPoint, ...]
    ) -> None:
        if not points or len(points) > self._config.max_batch_size:
            raise ValueError(
                f"upsert batch size must be between 1 and {self._config.max_batch_size}"
            )
        statistics = await self.statistics(identity)
        if statistics.dimensions is None or any(
            len(point.vector) != statistics.dimensions for point in points
        ):
            raise ValueError("point dimensions do not match the collection")
        collection = identity.physical_name(self._config.collection_alias)
        encoded = []
        for point in points:
            payload = point.payload.model_dump(mode="json")
            payload["abstract_pattern_text"] = point.abstract_pattern_text
            encoded.append(
                {
                    "id": str(point.point_id),
                    "vector": {identity.vector_name: list(point.vector)},
                    "payload": payload,
                }
            )
        await self._request(
            "PUT",
            f"/collections/{self._path_name(collection)}/points?wait=true",
            payload={"points": encoded},
        )

    async def delete_points(
        self,
        point_ids: tuple[UUID, ...],
        identity: CollectionIdentity | None = None,
        physical_collection: str | None = None,
    ) -> None:
        if not point_ids or len(point_ids) > self._config.max_batch_size:
            raise ValueError(
                f"delete batch size must be between 1 and {self._config.max_batch_size}"
            )
        collection = physical_collection or (
            identity.physical_name(self._config.collection_alias)
            if identity is not None
            else self._config.collection_alias
        )
        await self._request(
            "POST",
            f"/collections/{self._path_name(collection)}/points/delete?wait=true",
            payload={"points": [str(point_id) for point_id in point_ids]},
        )

    async def query(self, request: VectorQuery) -> tuple[VectorMatch, ...]:
        requested_limit = request.limit
        if request.diversity is not None:
            requested_limit = min(1_000, request.limit * request.diversity.oversample_factor)
        body: dict[str, object] = {
            "query": list(request.vector),
            "using": self._config.vector_name,
            "filter": _qdrant_filter(request.filters),
            "limit": requested_limit,
            "with_payload": True,
        }
        if request.score_threshold is not None:
            body["score_threshold"] = request.score_threshold
        _, response = await self._request(
            "POST",
            f"/collections/{self._path_name(self._config.collection_alias)}/points/query",
            payload=body,
        )
        raw_points = _result_points(response)
        matches = tuple(_decode_match(point) for point in raw_points)
        if request.diversity is None:
            return matches[: request.limit]
        selected: list[VectorMatch] = []
        counts: Counter[str] = Counter()
        for match in matches:
            key = (
                match.payload.source_domain
                if request.diversity.field is DiversityField.SOURCE_DOMAIN
                else str(match.payload.source_website_id)
            )
            if counts[key] >= request.diversity.maximum_per_source:
                continue
            counts[key] += 1
            selected.append(match)
            if len(selected) == request.limit:
                break
        return tuple(selected)

    async def scroll(self, *, offset: str | int | None = None, limit: int = 256) -> ScrollPage:
        if not 1 <= limit <= 1_000:
            raise ValueError("scroll limit must be between 1 and 1000")
        payload: dict[str, object] = {
            "limit": limit,
            "with_payload": True,
        }
        if offset is not None:
            payload["offset"] = offset
        _, response = await self._request(
            "POST",
            f"/collections/{self._path_name(self._config.collection_alias)}/points/scroll",
            payload=payload,
        )
        if response is None or not isinstance(response.get("result"), dict):
            raise MalformedVectorResponseError("scroll response has an invalid shape")
        result = cast(dict[str, Any], response["result"])
        raw_points = result.get("points")
        if not isinstance(raw_points, list):
            raise MalformedVectorResponseError("scroll points have an invalid shape")
        points = tuple(_decode_scrolled(point) for point in raw_points)
        next_offset = result.get("next_page_offset")
        if next_offset is not None and not isinstance(next_offset, (str, int)):
            raise MalformedVectorResponseError("scroll offset has an invalid shape")
        return ScrollPage(points=points, next_offset=next_offset)


def _nested(value: dict[str, Any], *keys: str) -> object:
    current: object = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _qdrant_filter(filters: PayloadFilter) -> dict[str, object]:
    must: list[dict[str, object]] = [
        {"key": "project_id", "match": {"value": str(filters.project_id)}},
        {"key": "approved", "match": {"value": filters.approved}},
    ]
    for key, values in (
        ("dataset_id", tuple(map(str, filters.dataset_ids))),
        ("dataset_version_id", tuple(map(str, filters.dataset_version_ids))),
        ("source_domain", filters.source_domains),
        ("source_website_id", tuple(map(str, filters.source_website_ids))),
        ("category", filters.categories),
        ("page_type", filters.page_types),
        ("section_type", filters.section_types),
        ("layout", filters.layouts),
        ("style_tags", filters.style_tags),
        ("language", filters.languages),
        (
            "provenance_status",
            tuple(status.value for status in filters.provenance_statuses),
        ),
    ):
        if values:
            must.append({"key": key, "match": {"any": list(values)}})
    if filters.minimum_confidence is not None:
        must.append({"key": "confidence", "range": {"gte": filters.minimum_confidence}})
    return {"must": must}


def _result_points(response: dict[str, Any] | None) -> list[object]:
    if response is None:
        raise MalformedVectorResponseError("query response is empty")
    result = response.get("result")
    if isinstance(result, list):
        return cast(list[object], result)
    if isinstance(result, dict) and isinstance(result.get("points"), list):
        return cast(list[object], result["points"])
    raise MalformedVectorResponseError("query response has an invalid shape")


def _decode_payload(raw: object) -> tuple[str, DesignPatternPayload]:
    if not isinstance(raw, dict):
        raise MalformedVectorResponseError("point payload has an invalid shape")
    payload = dict(raw)
    abstract_text = payload.pop("abstract_pattern_text", None)
    if not isinstance(abstract_text, str):
        raise MalformedVectorResponseError("abstract pattern text is missing")
    try:
        return abstract_text, DesignPatternPayload.model_validate_json(json.dumps(payload))
    except ValidationError as error:
        raise MalformedVectorResponseError("point payload failed validation") from error


def _decode_match(raw: object) -> VectorMatch:
    if not isinstance(raw, dict):
        raise MalformedVectorResponseError("query point has an invalid shape")
    abstract_text, payload = _decode_payload(raw.get("payload"))
    score = raw.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise MalformedVectorResponseError("query score has an invalid shape")
    try:
        return VectorMatch(
            point_id=UUID(str(raw.get("id"))),
            score=float(score),
            abstract_pattern_text=abstract_text,
            payload=payload,
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise MalformedVectorResponseError("query point failed validation") from error


def _decode_scrolled(raw: object) -> tuple[UUID, str, DesignPatternPayload]:
    if not isinstance(raw, dict):
        raise MalformedVectorResponseError("scrolled point has an invalid shape")
    abstract_text, payload = _decode_payload(raw.get("payload"))
    try:
        return UUID(str(raw.get("id"))), abstract_text, payload
    except ValueError as error:
        raise MalformedVectorResponseError("scrolled point ID is invalid") from error
