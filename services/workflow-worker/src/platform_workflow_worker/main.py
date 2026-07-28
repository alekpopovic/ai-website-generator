"""Run the workflow-only Temporal worker process."""

import asyncio
import logging
import os
import signal
from typing import cast

from platform_api.config import get_settings
from platform_api.database import DatabaseManager
from platform_workflows.client import TemporalClientConfig, create_temporal_client
from platform_workflows.events import RedisJobEventPublisher, RedisStream
from platform_workflows.queues import TaskQueue
from platform_workflows.worker import (
    WorkerConfig,
    WorkerHealthIndicator,
    WorkerState,
    create_worker,
)
from platform_workflows.workflows import WORKFLOW_TYPES
from redis.asyncio import Redis

from platform_workflow_worker.activities import ScanControlActivities

logger = logging.getLogger(__name__)


async def run() -> None:
    """Connect, report readiness, and shut down cooperatively on process signals."""
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    settings = get_settings()
    database = DatabaseManager(settings.database)
    client = await create_temporal_client(
        TemporalClientConfig(
            address=os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"),
            namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
        )
    )
    config = WorkerConfig(task_queue=TaskQueue.CONTROL)
    health = WorkerHealthIndicator("workflow-worker", config.task_queue)
    redis: Redis | None = None
    event_publisher = None
    if settings.redis.url is not None:
        redis = Redis.from_url(
            settings.redis.url.get_secret_value(),
            socket_connect_timeout=settings.redis.connect_timeout_seconds,
            decode_responses=False,
        )
        event_publisher = RedisJobEventPublisher(
            cast(RedisStream, redis),
            prefix=settings.redis.key_prefix,
            maxlen=settings.redis.job_event_stream_max_length,
        )
    activities = ScanControlActivities(database, settings.qdrant, event_publisher)
    worker = create_worker(
        client, config, workflows=WORKFLOW_TYPES, activities=activities.registered()
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for process_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(process_signal, stop.set)

    worker_task = asyncio.create_task(worker.run(), name="temporal-workflow-worker")
    stop_task = asyncio.create_task(stop.wait(), name="worker-stop-signal")
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
    await database.close()
    if redis is not None:
        await redis.aclose()
    health.transition(WorkerState.STOPPED)
    logger.info("worker_stopped %s", health.snapshot())


def main() -> None:
    """Synchronous console entry point."""
    asyncio.run(run())
