"""Opt-in Redis Stream coverage for monotonic idempotent job-event wakeups."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import pytest
from platform_workflows.events import JobEvent, RedisJobEventPublisher, RedisStream
from redis.asyncio import Redis

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    url = os.environ.get("INTEGRATION_REDIS_URL")
    if url is None:
        pytest.skip("INTEGRATION_REDIS_URL is not configured")
    client: Redis = Redis.from_url(url, decode_responses=False)
    await client.ping()
    try:
        yield client
    finally:
        await client.aclose()


async def test_event_ids_are_ordered_and_retry_safe(redis_client: Redis) -> None:
    prefix = f"platform-integration:{uuid4()}"
    job_id = str(uuid4())
    project_id = str(uuid4())
    publisher = RedisJobEventPublisher(cast(RedisStream, redis_client), prefix=prefix, maxlen=100)
    first = JobEvent.create(
        job_id=job_id,
        project_id=project_id,
        sequence=1,
        event_type="scan.started",
        status="running",
    )
    second = JobEvent.create(
        job_id=job_id,
        project_id=project_id,
        sequence=2,
        event_type="scan.completed",
        status="succeeded",
    )
    stream = f"{prefix}:job-events:{job_id}"
    try:
        assert await publisher.publish(first) == "1-0"
        assert await publisher.publish(first) == "1-0"
        assert await publisher.publish(second) == "2-0"
        entries = await redis_client.xrange(stream)
        assert entries is not None
        assert [entry_id for entry_id, _ in entries] == [b"1-0", b"2-0"]
    finally:
        await redis_client.delete(stream)
