"""Cooperative cancellation helpers for activity implementations."""

import asyncio

from temporalio import activity


def raise_if_activity_cancelled() -> None:
    """Stop at a safe checkpoint when Temporal has requested cancellation."""
    if activity.is_cancelled():
        raise asyncio.CancelledError


async def wait_for_activity_cancellation() -> None:
    """Wait until Temporal cancellation or worker shutdown reaches the activity."""
    await activity.wait_for_cancelled()
