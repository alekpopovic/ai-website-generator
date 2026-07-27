"""OpenTelemetry-compatible lifecycle and request instrumentation boundaries."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer

from platform_api.constants import SERVICE_NAME, SERVICE_VERSION


class Telemetry(Protocol):
    """Boundary that allows exporters and SDK instrumentation to be wired externally."""

    async def startup(self) -> None:
        """Initialize telemetry resources without making network calls by default."""
        ...

    async def shutdown(self) -> None:
        """Flush and release telemetry resources."""
        ...

    def request_span(self, method: str, route: str) -> AbstractContextManager[Span]:
        """Create a server request span."""
        ...


class OpenTelemetryBoundary:
    """API-only instrumentation that works with any globally configured OTel provider."""

    def __init__(self, tracer: Tracer | None = None) -> None:
        self._tracer = tracer or trace.get_tracer(SERVICE_NAME, SERVICE_VERSION)

    async def startup(self) -> None:
        """Leave provider/exporter ownership to the deployment composition root."""

    async def shutdown(self) -> None:
        """Leave provider/exporter shutdown to the deployment composition root."""

    def request_span(self, method: str, route: str) -> AbstractContextManager[Span]:
        """Create a span without requiring an SDK or exporter in tests."""
        return self._tracer.start_as_current_span(
            f"{method} {route}",
            kind=trace.SpanKind.SERVER,
            attributes={"http.request.method": method, "url.path": route},
        )


class NoopTelemetry:
    """Deterministic telemetry boundary for tests."""

    async def startup(self) -> None:
        """Perform no startup work."""

    async def shutdown(self) -> None:
        """Perform no shutdown work."""

    def request_span(self, method: str, route: str) -> AbstractContextManager[Span]:
        """Return the OpenTelemetry no-op provider's span context."""
        tracer = trace.NoOpTracerProvider().get_tracer(SERVICE_NAME, SERVICE_VERSION)
        return tracer.start_as_current_span(f"{method} {route}")
