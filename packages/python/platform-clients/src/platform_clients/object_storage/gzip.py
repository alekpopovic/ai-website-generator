"""Streaming deterministic gzip helpers for bounded HTML and JSON artifacts."""

import json
import zlib
from collections.abc import AsyncIterable, AsyncIterator

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]


async def gzip_stream(source: AsyncIterable[bytes]) -> AsyncIterator[bytes]:
    """Compress chunks without buffering the complete artifact in memory."""
    compressor = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=31)
    async for chunk in source:
        if not isinstance(chunk, bytes):
            raise TypeError("gzip source must yield bytes")
        compressed = compressor.compress(chunk)
        if compressed:
            yield compressed
    final = compressor.flush()
    if final:
        yield final


async def html_bytes(html: str, *, chunk_size: int = 64 * 1_024) -> AsyncIterator[bytes]:
    """Encode reviewed HTML text in bounded UTF-8 chunks."""
    encoded = html.encode("utf-8")
    for offset in range(0, len(encoded), chunk_size):
        yield encoded[offset : offset + chunk_size]


async def gzip_html(html: str) -> AsyncIterator[bytes]:
    async for chunk in gzip_stream(html_bytes(html)):
        yield chunk


async def json_bytes(value: JsonValue) -> AsyncIterator[bytes]:
    """Serialize JSON deterministically before streaming compression."""
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        allow_nan=False,
        check_circular=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    for piece in encoder.iterencode(value):
        yield piece.encode("utf-8")


async def gzip_json(value: JsonValue) -> AsyncIterator[bytes]:
    async for chunk in gzip_stream(json_bytes(value)):
        yield chunk
