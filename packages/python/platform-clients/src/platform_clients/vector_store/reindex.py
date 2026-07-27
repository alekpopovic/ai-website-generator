"""Explicit, resumable design-pattern reindex command."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass

from platform_clients.llm.models import EmbeddingRequest, ModelRole
from platform_clients.llm.ollama import OllamaConfig, OllamaGateway
from platform_clients.llm.protocols import EmbeddingGenerator
from platform_clients.vector_store.models import (
    CollectionIdentity,
    VectorPoint,
)
from platform_clients.vector_store.protocols import VectorStore
from platform_clients.vector_store.qdrant import QdrantConfig, QdrantVectorStore

_DIMENSION_PROBE = "abstract layout pattern with balanced spacing and clear hierarchy"


@dataclass(frozen=True, slots=True)
class ReindexArguments:
    execute: bool
    promote: bool
    confirm_alias: str | None
    batch_size: int


def _arguments() -> ReindexArguments:
    parser = argparse.ArgumentParser(
        description=(
            "Re-embed allowlisted abstract design-pattern records into a versioned "
            "Qdrant collection. The old collection is retained."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform network calls and write the new physical collection",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="atomically move the stable collection alias after a successful reindex",
    )
    parser.add_argument(
        "--confirm-alias",
        help="must exactly equal QDRANT_COLLECTION_ALIAS when --promote is used",
    )
    parser.add_argument("--batch-size", type=int, default=64)
    values = parser.parse_args()
    if not 1 <= values.batch_size <= 256:
        parser.error("--batch-size must be between 1 and 256")
    if values.promote and not values.execute:
        parser.error("--promote requires --execute")
    return ReindexArguments(
        execute=values.execute,
        promote=values.promote,
        confirm_alias=values.confirm_alias,
        batch_size=values.batch_size,
    )


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


async def _run(arguments: ReindexArguments) -> None:
    alias = _env("QDRANT_COLLECTION_ALIAS", "design-patterns")
    if arguments.promote and arguments.confirm_alias != alias:
        raise SystemExit("--confirm-alias must exactly match QDRANT_COLLECTION_ALIAS")
    ollama = OllamaGateway.create(
        OllamaConfig(
            base_url=_env("OLLAMA_URL", "http://127.0.0.1:11434"),
            embedding_model=_env("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:0.6b"),
        )
    )
    qdrant = QdrantVectorStore.create(
        QdrantConfig(
            base_url=_env("QDRANT_URL", "http://127.0.0.1:6333"),
            api_key=os.environ.get("QDRANT_API_KEY") or None,
            collection_alias=alias,
            vector_name=_env("QDRANT_VECTOR_NAME", "design-pattern"),
            max_batch_size=arguments.batch_size,
        )
    )
    try:
        if not arguments.execute:
            print(
                json.dumps(
                    {
                        "execute": False,
                        "collection_alias": alias,
                        "message": "Dry plan only. Use --execute to inspect models and reindex.",
                    },
                    sort_keys=True,
                )
            )
            return
        metadata = await ollama.model_metadata(ModelRole.EMBEDDING)
        dimensions = metadata.embedding_dimensions
        if dimensions is None:
            probe = await ollama.create_embeddings(EmbeddingRequest(inputs=(_DIMENSION_PROBE,)))
            dimensions = len(probe.value[0])
        identity = CollectionIdentity(
            embedding_provider=metadata.provider,
            embedding_model=metadata.name,
            embedding_model_digest=metadata.digest,
            serialization_schema_version=int(_env("QDRANT_SERIALIZATION_SCHEMA_VERSION", "1")),
            vector_name=_env("QDRANT_VECTOR_NAME", "design-pattern"),
        )
        previous = await qdrant.statistics()
        target = await qdrant.prepare_collection(identity, dimensions)
        copied = 0
        if (
            previous.physical_collection is not None
            and previous.physical_collection != target.physical_collection
        ):
            copied = await reindex_active_records(
                ollama,
                qdrant,
                identity=identity,
                dimensions=dimensions,
                batch_size=arguments.batch_size,
            )
        if arguments.promote:
            target = await qdrant.promote_collection(identity)
        print(
            json.dumps(
                {
                    "execute": True,
                    "promoted": arguments.promote,
                    "collection_alias": alias,
                    "physical_collection": target.physical_collection,
                    "embedding_provider": metadata.provider,
                    "embedding_model": metadata.name,
                    "embedding_model_digest": metadata.digest,
                    "dimensions": dimensions,
                    "points_reindexed": copied,
                },
                sort_keys=True,
            )
        )
    finally:
        await qdrant.close()
        await ollama.close()


async def reindex_active_records(
    embeddings: EmbeddingGenerator,
    vector_store: VectorStore,
    *,
    identity: CollectionIdentity,
    dimensions: int,
    batch_size: int,
) -> int:
    """Copy validated abstract records into a prepared identity, resumably."""
    if not 1 <= batch_size <= 256:
        raise ValueError("reindex batch size must be between 1 and 256")
    copied = 0
    offset: str | int | None = None
    while True:
        page = await vector_store.scroll(offset=offset, limit=batch_size)
        if page.points:
            result = await embeddings.create_embeddings(
                EmbeddingRequest(
                    inputs=tuple(text for _, text, _ in page.points),
                    dimensions=dimensions,
                )
            )
            if result.metadata.model_digest != identity.embedding_model_digest:
                raise RuntimeError("embedding model changed during reindex")
            points = tuple(
                VectorPoint(
                    abstract_pattern_text=text,
                    payload=payload,
                    vector=vector,
                )
                for (_, text, payload), vector in zip(page.points, result.value, strict=True)
            )
            await vector_store.upsert_points(identity, points)
            copied += len(points)
        if page.next_offset is None:
            return copied
        offset = page.next_offset


def main() -> None:
    """Run the guarded reindex command."""
    asyncio.run(_run(_arguments()))


if __name__ == "__main__":
    main()
