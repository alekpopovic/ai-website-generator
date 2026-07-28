"""Run the persistent browser Temporal worker with one reusable Chromium process."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from platform_api.config import get_settings
from platform_api.database import DatabaseManager
from platform_clients.network_safety import (
    NetworkLimits,
    NetworkSafetyPolicy,
    NetworkSafetySubsystem,
    NetworkTimeouts,
    PlaywrightRequestSafety,
)
from platform_clients.network_safety.resolver import SystemDnsResolver
from platform_clients.object_storage import S3ObjectStorage, StorageConfig
from platform_clients.object_storage.models import StorageProvider
from platform_workflows.client import TemporalClientConfig, create_temporal_client
from platform_workflows.queues import TaskQueue
from platform_workflows.worker import (
    WorkerConfig,
    WorkerHealthIndicator,
    WorkerState,
    create_worker,
)

from platform_browser_worker.activities import BrowserActivities
from platform_browser_worker.renderer import PlaywrightBrowserRenderer
from platform_browser_worker.repository import BrowserScanRepository
from platform_browser_worker.runner import BrowserScanRunner

logger = logging.getLogger(__name__)


async def run() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    settings = get_settings()
    database = DatabaseManager(settings.database)
    minio = settings.minio
    storage = await S3ObjectStorage.create(
        StorageConfig(
            provider=StorageProvider(minio.provider),
            region=minio.region,
            endpoint_url=str(minio.endpoint) if minio.endpoint is not None else None,
            access_key=minio.access_key.get_secret_value() if minio.access_key else None,
            secret_key=minio.secret_key.get_secret_value() if minio.secret_key else None,
            session_token=minio.session_token.get_secret_value() if minio.session_token else None,
            connect_timeout_seconds=minio.connect_timeout_seconds,
            read_timeout_seconds=minio.read_timeout_seconds,
            multipart_part_size=minio.multipart_part_size,
        )
    )
    client = await create_temporal_client(
        TemporalClientConfig(
            address=settings.temporal.address,
            namespace=settings.temporal.namespace,
        )
    )
    maximum_contexts = int(os.environ.get("BROWSER_WORKER_MAX_CONTEXTS", "2"))
    navigation_seconds = float(os.environ.get("BROWSER_NAVIGATION_TIMEOUT_SECONDS", "45"))
    request_safety = PlaywrightRequestSafety(
        NetworkSafetySubsystem(
            SystemDnsResolver(),
            policy=NetworkSafetyPolicy(
                limits=NetworkLimits(
                    max_redirects=5,
                    max_response_header_bytes=64 * 1_024,
                    max_response_body_bytes=5 * 1_024 * 1_024,
                    timeouts=NetworkTimeouts(
                        connect_seconds=10,
                        read_seconds=30,
                        total_seconds=max(45, navigation_seconds),
                        browser_navigation_seconds=navigation_seconds,
                    ),
                )
            ),
        )
    )
    renderer = PlaywrightBrowserRenderer(request_safety, maximum_concurrency=maximum_contexts)
    repository = BrowserScanRepository(database, storage)
    runner = BrowserScanRunner(repository, renderer)
    activities = BrowserActivities(runner)
    config = WorkerConfig(
        task_queue=TaskQueue.BROWSER,
        max_concurrent_activities=maximum_contexts,
        graceful_shutdown_seconds=60,
    )
    health = WorkerHealthIndicator("browser-worker", config.task_queue)
    worker = create_worker(client, config, activities=(activities.render_representative_page,))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for process_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(process_signal, stop.set)
    worker_task: asyncio.Task[None] | None = None
    try:
        await renderer.start()
        worker_task = asyncio.create_task(worker.run(), name="temporal-browser-worker")
        stop_task = asyncio.create_task(stop.wait(), name="browser-worker-stop-signal")
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
        health.transition(WorkerState.FAILED, detail="browser worker terminated unexpectedly")
        raise
    finally:
        await renderer.close()
        await storage.close()
        await database.close()
        health.transition(WorkerState.STOPPED)


def main() -> None:
    asyncio.run(run())
