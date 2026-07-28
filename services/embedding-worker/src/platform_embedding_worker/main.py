"""Run the private Ollama and Qdrant Temporal embedding worker."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from platform_api.config import get_settings
from platform_api.database import DatabaseManager
from platform_clients.llm.ollama import OllamaConfig, OllamaGateway
from platform_clients.vector_store.qdrant import QdrantConfig, QdrantVectorStore
from platform_workflows.client import TemporalClientConfig, create_temporal_client
from platform_workflows.queues import TaskQueue
from platform_workflows.worker import (
    WorkerConfig,
    WorkerHealthIndicator,
    WorkerState,
    create_worker,
)

from platform_embedding_worker.activities import EmbeddingActivities
from platform_embedding_worker.repository import SqlAlchemyEmbeddingRepository
from platform_embedding_worker.runner import EmbeddingIndexer

logger = logging.getLogger(__name__)


async def run() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    settings = get_settings()
    database = DatabaseManager(settings.database)
    ollama_settings = settings.ollama
    qdrant_settings = settings.qdrant
    gateway = OllamaGateway.create(
        OllamaConfig(
            base_url=str(ollama_settings.url),
            embedding_model=ollama_settings.embedding_model,
            connect_timeout_seconds=ollama_settings.connect_timeout_seconds,
            request_timeout_seconds=ollama_settings.request_timeout_seconds,
            concurrency_wait_seconds=ollama_settings.concurrency_wait_seconds,
            max_concurrency=ollama_settings.max_concurrency,
            max_attempts=ollama_settings.max_attempts,
            retry_backoff_seconds=ollama_settings.retry_backoff_seconds,
            circuit_failure_threshold=ollama_settings.circuit_failure_threshold,
            circuit_recovery_seconds=ollama_settings.circuit_recovery_seconds,
            metadata_cache_seconds=ollama_settings.metadata_cache_seconds,
            max_prompt_bytes=ollama_settings.max_prompt_bytes,
            keep_alive=ollama_settings.keep_alive,
        )
    )
    vector_store = QdrantVectorStore.create(
        QdrantConfig(
            base_url=str(qdrant_settings.url),
            api_key=(
                qdrant_settings.api_key.get_secret_value() if qdrant_settings.api_key else None
            ),
            connect_timeout_seconds=qdrant_settings.connect_timeout_seconds,
            request_timeout_seconds=qdrant_settings.request_timeout_seconds,
            max_concurrency=qdrant_settings.max_concurrency,
            max_batch_size=min(qdrant_settings.max_batch_size, 256),
            collection_alias=qdrant_settings.collection_alias,
            vector_name=qdrant_settings.vector_name,
        )
    )
    client = await create_temporal_client(
        TemporalClientConfig(
            address=settings.temporal.address,
            namespace=settings.temporal.namespace,
        )
    )
    repository = SqlAlchemyEmbeddingRepository(database)
    indexer = EmbeddingIndexer(repository, gateway, vector_store)
    activities = EmbeddingActivities(indexer)
    config = WorkerConfig(
        task_queue=TaskQueue.EMBEDDING,
        max_concurrent_activities=int(os.environ.get("EMBEDDING_WORKER_MAX_ACTIVITIES", "2")),
        graceful_shutdown_seconds=60,
    )
    health = WorkerHealthIndicator("embedding-worker", config.task_queue)
    worker = create_worker(client, config, activities=(activities.index_section_patterns,))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for process_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(process_signal, stop.set)
    worker_task: asyncio.Task[None] | None = None
    try:
        worker_task = asyncio.create_task(worker.run(), name="temporal-embedding-worker")
        stop_task = asyncio.create_task(stop.wait(), name="embedding-worker-stop-signal")
        health.transition(WorkerState.READY)
        logger.info("worker_ready %s", health.snapshot())
        done, _ = await asyncio.wait({worker_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if worker_task in done:
            stop_task.cancel()
            await worker_task
        else:
            health.transition(WorkerState.STOPPING)
            await worker.shutdown()
            await worker_task
    except Exception:
        health.transition(WorkerState.FAILED, detail="embedding worker terminated unexpectedly")
        raise
    finally:
        await vector_store.close()
        await gateway.close()
        await database.close()
        health.transition(WorkerState.STOPPED)


def main() -> None:
    asyncio.run(run())
