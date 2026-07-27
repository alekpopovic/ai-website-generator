"""Small async circuit breaker for internal inference calls."""

import asyncio
import time


class CircuitOpenError(RuntimeError):
    """Calls are rejected while the provider recovery window is active."""


class AsyncCircuitBreaker:
    def __init__(self, *, failure_threshold: int, recovery_seconds: float) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    async def before_request(self) -> None:
        async with self._lock:
            if self._opened_at is None:
                return
            if time.monotonic() - self._opened_at < self._recovery_seconds:
                raise CircuitOpenError("local inference circuit is open")
            self._opened_at = None
            self._failures = 0

    async def record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._opened_at = None

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = time.monotonic()
