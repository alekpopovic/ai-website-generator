"""Streaming, offline-only parsing and normalization for scan-target imports."""

from __future__ import annotations

import codecs
import csv
import ipaddress
import re
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from platform_api.persistence.json import JsonValue

MAX_IMPORT_ROWS = 50_000
MAX_IMPORT_BYTES = 20 * 1_024 * 1_024
MAX_CSV_RECORD_BYTES = 128 * 1_024
TARGET_COLUMNS = ("domain", "url", "hostname", "website")
_COMMON_TWO_LABEL_SUFFIXES = frozenset(
    {
        "ac.uk",
        "co.jp",
        "co.nz",
        "co.uk",
        "com.au",
        "com.br",
        "com.mx",
        "com.sg",
        "com.tr",
        "edu.au",
        "gov.uk",
        "net.au",
        "net.nz",
        "org.au",
        "org.nz",
        "org.uk",
    }
)

ImportOutcome = Literal["accepted", "duplicate", "invalid", "blocked", "already_present"]


@dataclass(frozen=True, slots=True)
class ImportSourceRow:
    row_number: int
    raw_value: str
    metadata: dict[str, JsonValue]
    validation_error: TargetValidationError | None = None


@dataclass(frozen=True, slots=True)
class NormalizedTarget:
    url: str
    domain: str


class TargetValidationError(ValueError):
    """Typed validation outcome safe to persist and export."""

    def __init__(self, code: str, message: str, *, blocked: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.blocked = blocked


async def decoded_lines(chunks: AsyncIterable[bytes]) -> AsyncIterator[str]:
    """Incrementally decode bounded UTF-8 request chunks into logical lines."""
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    pending = ""
    received = 0
    try:
        async for chunk in chunks:
            received += len(chunk)
            if received > MAX_IMPORT_BYTES:
                raise TargetValidationError("file_too_large", "Import exceeds the 20 MiB limit.")
            pending += decoder.decode(chunk)
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                yield line.removesuffix("\r")
        pending += decoder.decode(b"", final=True)
    except UnicodeDecodeError as error:
        raise TargetValidationError("invalid_encoding", "Import must be valid UTF-8.") from error
    if pending:
        yield pending.removesuffix("\r")


async def parse_text_rows(chunks: AsyncIterable[bytes]) -> AsyncIterator[ImportSourceRow]:
    row_number = 0
    async for line in decoded_lines(chunks):
        row_number += 1
        _check_row_limit(row_number)
        yield ImportSourceRow(row_number=row_number, raw_value=line.strip(), metadata={})


async def parse_csv_rows(chunks: AsyncIterable[bytes]) -> AsyncIterator[ImportSourceRow]:
    records = _csv_records(decoded_lines(chunks))
    try:
        header_number, header_record = await anext(records)
    except StopAsyncIteration:
        return
    header = _parse_csv_record(header_record, header_number)
    normalized_header = [value.strip().casefold() for value in header]
    if len(normalized_header) != len(set(normalized_header)):
        raise TargetValidationError("csv_duplicate_header", "CSV column names must be unique.")
    target_column = next((name for name in TARGET_COLUMNS if name in normalized_header), None)
    if target_column is None:
        raise TargetValidationError(
            "csv_missing_target_column",
            "CSV requires one of these columns: domain, url, hostname, website.",
        )
    target_index = normalized_header.index(target_column)
    async for row_number, record in records:
        _check_row_limit(row_number - header_number)
        try:
            values = _parse_csv_record(record, row_number)
        except TargetValidationError as error:
            yield ImportSourceRow(
                row_number=row_number,
                raw_value=record[:2_048],
                metadata={},
                validation_error=error,
            )
            continue
        if len(values) > len(header):
            raise TargetValidationError(
                "csv_malformed_row", f"CSV row {row_number} has more values than the header."
            )
        values.extend([""] * (len(header) - len(values)))
        metadata: dict[str, JsonValue] = {}
        for index, name in enumerate(normalized_header):
            if index == target_index or not name:
                continue
            value = values[index].strip()
            if value:
                if len(name) > 100 or len(value) > 1_000 or len(metadata) >= 50:
                    raise TargetValidationError(
                        "csv_metadata_too_large",
                        f"CSV metadata on row {row_number} exceeds safe limits.",
                    )
                metadata[name] = value
        yield ImportSourceRow(
            row_number=row_number,
            raw_value=values[target_index].strip(),
            metadata=metadata,
        )


async def _csv_records(lines: AsyncIterable[str]) -> AsyncIterator[tuple[int, str]]:
    record = ""
    start = 1
    line_number = 0
    async for line in lines:
        line_number += 1
        if not record:
            start = line_number
            record = line
        else:
            record += "\n" + line
        if len(record.encode("utf-8")) > MAX_CSV_RECORD_BYTES:
            raise TargetValidationError(
                "csv_record_too_large", f"CSV record beginning on row {start} is too large."
            )
        if _quotes_balanced(record):
            yield start, record
            record = ""
    if record:
        raise TargetValidationError(
            "csv_unterminated_quote", f"CSV record beginning on row {start} has an open quote."
        )


def _quotes_balanced(value: str) -> bool:
    quoted = False
    index = 0
    while index < len(value):
        if value[index] == '"':
            if quoted and index + 1 < len(value) and value[index + 1] == '"':
                index += 2
                continue
            quoted = not quoted
        index += 1
    return not quoted


def _parse_csv_record(record: str, row_number: int) -> list[str]:
    try:
        return next(csv.reader([record], strict=True))
    except csv.Error as error:
        raise TargetValidationError(
            "csv_malformed_row", f"CSV row {row_number} is malformed."
        ) from error


def normalize_import_target(value: str, *, allow_ip_literals: bool) -> NormalizedTarget:
    """Turn a domain-like value into a canonical root URL without doing I/O."""
    raw = value.strip().lstrip("\ufeff")
    if not raw:
        raise TargetValidationError("empty_target", "Target is empty.")
    if len(raw) > 2_048 or any(ord(character) < 32 for character in raw) or "\\" in raw:
        raise TargetValidationError("invalid_target", "Target contains invalid characters.")
    explicit_scheme = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw)
    if explicit_scheme is not None and not raw.casefold().startswith(("http://", "https://")):
        raise TargetValidationError(
            "unsupported_scheme", "Only HTTP and HTTPS targets are allowed."
        )
    candidate = raw if explicit_scheme is not None else f"https://{raw}"
    parsed = urlsplit(candidate)
    if parsed.scheme.casefold() not in {"http", "https"} or parsed.hostname is None:
        raise TargetValidationError(
            "invalid_target", "Target must contain a valid HTTP(S) hostname."
        )
    if parsed.username is not None or parsed.password is not None:
        raise TargetValidationError("embedded_credentials", "Embedded credentials are not allowed.")
    try:
        port = parsed.port
    except ValueError as error:
        raise TargetValidationError("invalid_port", "Target port is invalid.") from error
    if port is not None and port not in {80, 443}:
        raise TargetValidationError(
            "blocked_port", "Only standard HTTP(S) ports are allowed.", blocked=True
        )

    hostname = parsed.hostname.rstrip(".").casefold()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        hostname = _normalize_domain(hostname)
        _validate_public_suffix_structure(hostname)
    else:
        if not address.is_global:
            raise TargetValidationError(
                "non_public_ip",
                "Private, reserved, and local IP targets are blocked.",
                blocked=True,
            )
        if not allow_ip_literals:
            raise TargetValidationError(
                "ip_literal_requires_admin",
                "IP literal targets require an explicit administrator override.",
                blocked=True,
            )
        hostname = address.compressed

    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    scheme = parsed.scheme.casefold()
    return NormalizedTarget(url=urlunsplit((scheme, rendered_host, "/", "", "")), domain=hostname)


def _normalize_domain(hostname: str) -> str:
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError as error:
        raise TargetValidationError("invalid_hostname", "Target hostname is invalid.") from error
    labels = ascii_hostname.split(".")
    if (
        len(ascii_hostname) > 253
        or len(labels) < 2
        or any(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None for label in labels
        )
    ):
        raise TargetValidationError(
            "invalid_hostname", "Target hostname is not publicly structured."
        )
    if ascii_hostname == "localhost" or ascii_hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise TargetValidationError("local_hostname", "Local hostnames are blocked.", blocked=True)
    return ascii_hostname


def _validate_public_suffix_structure(hostname: str) -> None:
    labels = hostname.split(".")
    suffix_labels = 2 if ".".join(labels[-2:]) in _COMMON_TWO_LABEL_SUFFIXES else 1
    suffix = labels[-1]
    if (
        len(labels) <= suffix_labels
        or re.fullmatch(r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})", suffix) is None
    ):
        raise TargetValidationError(
            "invalid_public_suffix",
            "Target must include a registrable domain and a structurally valid public suffix.",
        )


def sanitize_filename(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not normalized:
        return None
    return re.sub(r"[^A-Za-z0-9._ -]", "_", normalized)[:255]


def _check_row_limit(row_number: int) -> None:
    if row_number > MAX_IMPORT_ROWS:
        raise TargetValidationError(
            "row_limit_exceeded", f"Import exceeds the {MAX_IMPORT_ROWS:,}-row limit."
        )
