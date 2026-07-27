"""Run the private Ollama-backed AI activity worker."""

import asyncio
import logging
import os
import signal

from platform_clients.llm.ollama import OllamaConfig, OllamaGateway
from platform_workflows.client import TemporalClientConfig, create_temporal_client
from platform_workflows.queues import TaskQueue
from platform_workflows.worker import (
    WorkerConfig,
    WorkerHealthIndicator,
    WorkerState,
    create_worker,
)

from platform_ai_worker.activities import ModelActivities

logger = logging.getLogger(__name__)


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def ollama_config_from_environment() -> OllamaConfig:
    """Read bounded non-secret local provider configuration from worker environment."""
    return OllamaConfig(
        base_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
        vision_model=os.environ.get("OLLAMA_VISION_MODEL", "qwen3-vl:8b"),
        generation_model=os.environ.get("OLLAMA_GENERATION_MODEL", "qwen3-coder:30b"),
        embedding_model=os.environ.get("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:0.6b"),
        connect_timeout_seconds=_float("OLLAMA_CONNECT_TIMEOUT_SECONDS", 5),
        request_timeout_seconds=_float("OLLAMA_REQUEST_TIMEOUT_SECONDS", 300),
        concurrency_wait_seconds=_float("OLLAMA_CONCURRENCY_WAIT_SECONDS", 10),
        max_concurrency=_int("OLLAMA_MAX_CONCURRENCY", 2),
        max_attempts=_int("OLLAMA_MAX_ATTEMPTS", 3),
        retry_backoff_seconds=_float("OLLAMA_RETRY_BACKOFF_SECONDS", 0.25),
        circuit_failure_threshold=_int("OLLAMA_CIRCUIT_FAILURE_THRESHOLD", 3),
        circuit_recovery_seconds=_float("OLLAMA_CIRCUIT_RECOVERY_SECONDS", 30),
        metadata_cache_seconds=_float("OLLAMA_METADATA_CACHE_SECONDS", 30),
        max_prompt_bytes=_int("OLLAMA_MAX_PROMPT_BYTES", 262_144),
        max_image_bytes=_int("OLLAMA_MAX_IMAGE_BYTES", 10_485_760),
        max_total_image_bytes=_int("OLLAMA_MAX_TOTAL_IMAGE_BYTES", 20_971_520),
        max_response_bytes=_int("OLLAMA_MAX_RESPONSE_BYTES", 4_194_304),
        keep_alive=os.environ.get("OLLAMA_KEEP_ALIVE", "5m"),
    )


async def run() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    gateway = OllamaGateway.create(ollama_config_from_environment())
    try:
        client = await create_temporal_client(
            TemporalClientConfig(
                address=os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"),
                namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
            )
        )
        config = WorkerConfig(
            task_queue=TaskQueue.AI_ANALYSIS,
            max_concurrent_activities=_int("AI_WORKER_MAX_CONCURRENT_ACTIVITIES", 2),
        )
        health = WorkerHealthIndicator("ai-worker", config.task_queue)
        activities = ModelActivities(gateway)
        worker = create_worker(client, config, activities=(activities.warm_up_model,))
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for process_signal in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(process_signal, stop.set)
        worker_task = asyncio.create_task(worker.run(), name="temporal-ai-worker")
        stop_task = asyncio.create_task(stop.wait(), name="ai-worker-stop-signal")
        health.transition(WorkerState.READY)
        logger.info("worker_ready %s", health.snapshot())
        done, _ = await asyncio.wait({worker_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if worker_task in done:
            stop_task.cancel()
            try:
                await worker_task
            except Exception:
                health.transition(WorkerState.FAILED, detail="worker poll loop failed")
                logger.exception("worker_failed %s", health.snapshot())
                raise
        else:
            health.transition(WorkerState.STOPPING)
            logger.info("worker_stopping %s", health.snapshot())
            await worker.shutdown()
            await worker_task
        health.transition(WorkerState.STOPPED)
        logger.info("worker_stopped %s", health.snapshot())
    finally:
        await gateway.close()


def main() -> None:
    asyncio.run(run())
