"""Pure-ASGI middleware for request context and secure response defaults."""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import MutableMapping
from typing import Final, cast

import structlog.contextvars
from opentelemetry.trace import Status, StatusCode
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from platform_api.logging import get_logger
from platform_api.telemetry import Telemetry

REQUEST_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _state(scope: Scope) -> MutableMapping[str, object]:
    """Return the mutable ASGI state mapping."""
    return cast(MutableMapping[str, object], scope.setdefault("state", {}))


class RequestContextMiddleware:
    """Create correlation context, JSON access logs, and request spans."""

    def __init__(self, app: ASGIApp, *, header_name: str, telemetry: Telemetry) -> None:
        self.app = app
        self.header_name = header_name
        self.telemetry = telemetry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        supplied_id = headers.get(self.header_name)
        request_id = (
            supplied_id
            if supplied_id is not None and REQUEST_ID_PATTERN.fullmatch(supplied_id)
            else str(uuid.uuid4())
        )
        _state(scope)["request_id"] = request_id
        method = str(scope.get("method", "UNKNOWN"))
        path = str(scope.get("path", "/"))
        status_code = 500
        started = time.perf_counter()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = MutableHeaders(scope=message)
                response_headers[self.header_name] = request_id
            await send(message)

        logger = get_logger()
        with self.telemetry.request_span(method, path) as span:
            span.set_attribute("http.request_id", request_id)
            try:
                await self.app(scope, receive, send_with_context)
                span.set_attribute("http.response.status_code", status_code)
                if status_code >= 500:
                    span.set_status(Status(StatusCode.ERROR))
            except Exception as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                duration_ms = round((time.perf_counter() - started) * 1000, 3)
                logger.info(
                    "request_complete",
                    http_method=method,
                    http_path=path,
                    http_status=status_code,
                    duration_ms=duration_ms,
                )
                structlog.contextvars.clear_contextvars()


class SecurityHeadersMiddleware:
    """Apply browser-facing defensive headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("Cache-Control", "no-store")
                headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                if scope.get("scheme") == "https":
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestBodyLimitMiddleware:
    """Bound declared and consumed control-plane request bodies."""

    def __init__(self, app: ASGIApp, *, max_bytes: int, request_id_header: str) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.request_id_header = request_id_header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                await self._send_problem(scope, send, 400, "invalid_content_length")
                return
            if declared_length < 0:
                await self._send_problem(scope, send, 400, "invalid_content_length")
                return
            if declared_length > self.max_bytes:
                await self._send_problem(scope, send, 413, "request_body_too_large")
                return

        consumed_bytes = 0

        async def limited_receive() -> Message:
            nonlocal consumed_bytes
            message = await receive()
            if message["type"] == "http.request":
                consumed_bytes += len(message.get("body", b""))
                if consumed_bytes > self.max_bytes:
                    raise RequestBodyTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLargeError:
            await self._send_problem(scope, send, 413, "request_body_too_large")

    async def _send_problem(self, scope: Scope, send: Send, status: int, code: str) -> None:
        request_id = str(_state(scope).get("request_id", "unknown"))
        detail = (
            "The request body exceeds the configured limit."
            if status == 413
            else "The Content-Length header is invalid."
        )
        body = json.dumps(
            {
                "type": f"urn:ai-website-generator:problem:{code}",
                "title": "Content Too Large" if status == 413 else "Bad Request",
                "status": status,
                "detail": detail,
                "instance": str(scope.get("path", "/")),
                "code": code,
                "request_id": request_id,
            },
            separators=(",", ":"),
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode()),
                    (self.request_id_header.lower().encode(), request_id.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class RequestBodyTooLargeError(Exception):
    """Private control-flow exception raised while consuming a chunked body."""
