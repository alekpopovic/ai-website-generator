"""Bounded response metadata, body streaming, and operation timeout helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Iterable, Mapping

from platform_clients.network_safety.models import (
    HTML_CONTENT_TYPES,
    NetworkFailureCode,
    NetworkLimits,
    NetworkSafetyError,
    ValidatedResponseHeaders,
)


def validate_html_response_headers(
    headers: Mapping[str, str] | Iterable[tuple[str, str]], limits: NetworkLimits
) -> ValidatedResponseHeaders:
    """Bound headers and reject non-HTML before browser or AI processing."""
    items = list(headers.items()) if isinstance(headers, Mapping) else list(headers)
    header_bytes = sum(
        len(name.encode("utf-8")) + len(value.encode("utf-8")) + 4 for name, value in items
    )
    if header_bytes > limits.max_response_header_bytes:
        raise NetworkSafetyError(
            NetworkFailureCode.RESPONSE_HEADERS_TOO_LARGE,
            "Response headers exceed the configured limit.",
        )
    normalized: dict[str, str] = {}
    for name, value in items:
        lowered = name.casefold()
        if (
            not name
            or any(ord(character) < 33 or ord(character) > 126 for character in name)
            or "\r" in value
            or "\n" in value
            or (lowered in {"content-length", "content-type"} and lowered in normalized)
        ):
            raise NetworkSafetyError(
                NetworkFailureCode.RESPONSE_HEADERS_INVALID,
                "Response headers are malformed or ambiguous.",
            )
        normalized[lowered] = value.strip()
    content_type = normalized.get("content-type", "").split(";", 1)[0].strip().casefold()
    if content_type not in HTML_CONTENT_TYPES:
        raise NetworkSafetyError(
            NetworkFailureCode.CONTENT_TYPE_NOT_HTML,
            "Only HTML responses are eligible for expensive processing.",
        )
    content_length: int | None = None
    if raw_length := normalized.get("content-length"):
        try:
            content_length = int(raw_length)
        except ValueError as error:
            raise NetworkSafetyError(
                NetworkFailureCode.RESPONSE_HEADERS_INVALID,
                "The response content length is invalid.",
            ) from error
        if content_length < 0 or content_length > limits.max_response_body_bytes:
            raise NetworkSafetyError(
                NetworkFailureCode.RESPONSE_BODY_TOO_LARGE,
                "Response body exceeds the configured limit.",
            )
    return ValidatedResponseHeaders(
        content_type=content_type,
        content_length=content_length,
        header_bytes=header_bytes,
    )


async def bounded_body(source: AsyncIterable[bytes], limits: NetworkLimits) -> AsyncIterator[bytes]:
    """Stream a response with read, total, and decoded-body size enforcement."""
    iterator = aiter(source)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limits.timeouts.total_seconds
    size = 0
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise NetworkSafetyError(
                NetworkFailureCode.TOTAL_TIMEOUT,
                "The response exceeded the total timeout.",
                retryable=True,
            )
        wait_seconds = min(remaining, limits.timeouts.read_seconds)
        try:
            chunk = await asyncio.wait_for(anext(iterator), timeout=wait_seconds)
        except StopAsyncIteration:
            return
        except NetworkSafetyError:
            raise
        except TimeoutError as error:
            code = (
                NetworkFailureCode.TOTAL_TIMEOUT
                if remaining <= limits.timeouts.read_seconds
                else NetworkFailureCode.READ_TIMEOUT
            )
            raise NetworkSafetyError(
                code,
                "The response timed out while reading.",
                retryable=True,
            ) from error
        except Exception as error:
            raise NetworkSafetyError(
                NetworkFailureCode.TRANSPORT_FAILURE,
                "The response stream failed.",
                retryable=True,
            ) from error
        size += len(chunk)
        if size > limits.max_response_body_bytes:
            raise NetworkSafetyError(
                NetworkFailureCode.RESPONSE_BODY_TOO_LARGE,
                "Response body exceeds the configured limit.",
            )
        yield chunk


async def with_connection_timeout[ValueT](
    operation: Awaitable[ValueT], limits: NetworkLimits
) -> ValueT:
    try:
        return await asyncio.wait_for(operation, timeout=limits.timeouts.connect_seconds)
    except NetworkSafetyError:
        raise
    except TimeoutError as error:
        raise NetworkSafetyError(
            NetworkFailureCode.CONNECTION_TIMEOUT,
            "The connection attempt timed out.",
            retryable=True,
        ) from error
    except Exception as error:
        raise NetworkSafetyError(
            NetworkFailureCode.TRANSPORT_FAILURE,
            "The connection attempt failed.",
            retryable=True,
        ) from error


async def with_total_timeout[ValueT](operation: Awaitable[ValueT], limits: NetworkLimits) -> ValueT:
    try:
        return await asyncio.wait_for(operation, timeout=limits.timeouts.total_seconds)
    except NetworkSafetyError:
        raise
    except TimeoutError as error:
        raise NetworkSafetyError(
            NetworkFailureCode.TOTAL_TIMEOUT,
            "The outbound operation exceeded the total timeout.",
            retryable=True,
        ) from error
    except Exception as error:
        raise NetworkSafetyError(
            NetworkFailureCode.TRANSPORT_FAILURE,
            "The outbound operation failed.",
            retryable=True,
        ) from error


async def with_browser_navigation_timeout[ValueT](
    operation: Awaitable[ValueT], limits: NetworkLimits
) -> ValueT:
    try:
        return await asyncio.wait_for(operation, timeout=limits.timeouts.browser_navigation_seconds)
    except NetworkSafetyError:
        raise
    except TimeoutError as error:
        raise NetworkSafetyError(
            NetworkFailureCode.BROWSER_NAVIGATION_TIMEOUT,
            "Browser navigation timed out.",
            retryable=True,
        ) from error
    except Exception as error:
        raise NetworkSafetyError(
            NetworkFailureCode.TRANSPORT_FAILURE,
            "Browser navigation failed.",
            retryable=True,
        ) from error
