"""Bounded JSON normalization for PostgreSQL JSONB columns."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


def normalize_json_value(value: object) -> JsonValue:
    """Convert approved values to deterministic JSON-compatible primitives.

    ORM instances and arbitrary objects are rejected rather than serialized through
    ``default=str``, which can leak internal state or silently corrupt contracts.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("JSON datetimes must include a timezone")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            normalized[key] = normalize_json_value(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_json_value(item) for item in value]
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


class SafeJSONB(TypeDecorator[JsonValue]):
    """JSONB type that validates and normalizes every bound value."""

    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value: JsonValue | None, dialect: Dialect) -> JsonValue | None:
        """Normalize values before the driver sees them."""
        del dialect
        return None if value is None else normalize_json_value(value)
