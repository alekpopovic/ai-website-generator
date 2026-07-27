"""Run the persistent Temporal crawl worker without importing Scrapy or Twisted."""

import asyncio
import logging
import os
import signal

from platform_workflows.client import TemporalClientConfig, create_temporal_client
from platform_workflows.queues import TaskQueue
from platform_workflows.worker import (
    WorkerConfig,
    WorkerHealthIndicator,
    WorkerState,
    create_worker,
)

from platform_crawler_worker.activities import CrawlActivities
from platform_crawler_worker.runner import SubprocessCrawlerRunner

logger = logging.getLogger(__name__)


async def run() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    client = await create_temporal_client(
        TemporalClientConfig(
            address=os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"),
            namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
        )
    )
    config = WorkerConfig(
        task_queue=TaskQueue.CRAWL,
        max_concurrent_activities=int(os.environ.get("CRAWLER_WORKER_MAX_PROCESSES", "2")),
    )
    health = WorkerHealthIndicator("crawler-worker", config.task_queue)
    activities = CrawlActivities(SubprocessCrawlerRunner())
    worker = create_worker(client, config, activities=(activities.crawl_scan_target,))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for process_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(process_signal, stop.set)
    worker_task = asyncio.create_task(worker.run(), name="temporal-crawler-worker")
    stop_task = asyncio.create_task(stop.wait(), name="crawler-worker-stop-signal")
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
    health.transition(WorkerState.STOPPED)


def main() -> None:
    asyncio.run(run())
