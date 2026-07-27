"""Typed contracts for hostile-network access policy and failures."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class NetworkFailureCode(StrEnum):
    SCHEME_NOT_ALLOWED = "scheme_not_allowed"
    CREDENTIALS_NOT_ALLOWED = "credentials_not_allowed"
    URL_INVALID = "url_invalid"
    HOSTNAME_INVALID = "hostname_invalid"
    HOSTNAME_BLOCKED = "hostname_blocked"
    METADATA_ENDPOINT_BLOCKED = "metadata_endpoint_blocked"
    ENCODED_IP_BLOCKED = "encoded_ip_blocked"
    ADDRESS_BLOCKED = "address_blocked"
    PORT_BLOCKED = "port_blocked"
    DNS_RESOLUTION_FAILED = "dns_resolution_failed"
    DNS_NO_RECORDS = "dns_no_records"
    DNS_MIXED_SCOPE = "dns_mixed_scope"
    DNS_REBINDING = "dns_rebinding"
    PEER_ADDRESS_MISMATCH = "peer_address_mismatch"
    REDIRECT_LIMIT_EXCEEDED = "redirect_limit_exceeded"
    REDIRECT_LOCATION_INVALID = "redirect_location_invalid"
    RESPONSE_HEADERS_TOO_LARGE = "response_headers_too_large"
    RESPONSE_HEADERS_INVALID = "response_headers_invalid"
    RESPONSE_BODY_TOO_LARGE = "response_body_too_large"
    CONTENT_TYPE_NOT_HTML = "content_type_not_html"
    CONNECTION_TIMEOUT = "connection_timeout"
    READ_TIMEOUT = "read_timeout"
    TOTAL_TIMEOUT = "total_timeout"
    BROWSER_NAVIGATION_TIMEOUT = "browser_navigation_timeout"
    TRANSPORT_FAILURE = "transport_failure"


class NetworkSafetyError(Exception):
    """Sanitized, typed failure that never exposes a raw resolver or transport exception."""

    def __init__(
        self,
        code: NetworkFailureCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class NetworkTimeouts:
    connect_seconds: float = 10.0
    read_seconds: float = 30.0
    total_seconds: float = 45.0
    browser_navigation_seconds: float = 45.0

    def __post_init__(self) -> None:
        for name, value in (
            ("connect_seconds", self.connect_seconds),
            ("read_seconds", self.read_seconds),
            ("total_seconds", self.total_seconds),
            ("browser_navigation_seconds", self.browser_navigation_seconds),
        ):
            if not 0.1 <= value <= 300:
                raise ValueError(f"{name} must be between 0.1 and 300 seconds")
        if self.connect_seconds > self.total_seconds or self.read_seconds > self.total_seconds:
            raise ValueError("connect and read timeouts cannot exceed the total timeout")


@dataclass(frozen=True, slots=True)
class NetworkLimits:
    max_redirects: int = 5
    max_response_header_bytes: int = 64 * 1_024
    max_response_body_bytes: int = 5 * 1_024 * 1_024
    timeouts: NetworkTimeouts = field(default_factory=NetworkTimeouts)

    def __post_init__(self) -> None:
        if not 0 <= self.max_redirects <= 20:
            raise ValueError("max_redirects must be between 0 and 20")
        if not 1_024 <= self.max_response_header_bytes <= 1024 * 1024:
            raise ValueError("response header limit must be between 1 KiB and 1 MiB")
        if not 1_024 <= self.max_response_body_bytes <= 100 * 1_024 * 1_024:
            raise ValueError("response body limit must be between 1 KiB and 100 MiB")


@dataclass(frozen=True, slots=True)
class NetworkSafetyPolicy:
    default_ports: frozenset[int] = frozenset({80, 443})
    administrator_ports: frozenset[int] = frozenset()
    internal_hostname_suffixes: tuple[str, ...] = (
        ".corp",
        ".home",
        ".internal",
        ".intranet",
        ".lan",
        ".local",
        ".localdomain",
        ".localhost",
        ".svc",
    )
    limits: NetworkLimits = field(default_factory=NetworkLimits)

    def __post_init__(self) -> None:
        if not self.default_ports or any(not 1 <= port <= 65_535 for port in self.default_ports):
            raise ValueError("default ports must be valid TCP ports")
        if any(not 1 <= port <= 65_535 for port in self.administrator_ports):
            raise ValueError("administrator ports must be valid TCP ports")
        if self.default_ports & self.administrator_ports:
            raise ValueError("administrator ports must not duplicate default ports")


@dataclass(frozen=True, slots=True)
class NetworkRequestContext:
    component: str
    request_id: str | None = None
    project_id: str | None = None
    administrator_port_access: bool = False

    def __post_init__(self) -> None:
        if not self.component or len(self.component) > 64:
            raise ValueError("component must be a non-empty bounded identifier")


@dataclass(frozen=True, slots=True)
class ApprovedUrl:
    url: str
    scheme: str
    hostname: str
    port: int
    addresses: frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address]


@dataclass(frozen=True, slots=True)
class NetworkBlockedAuditEvent:
    action: str
    component: str
    failure_code: NetworkFailureCode
    safe_url: str
    hostname: str | None
    request_id: str | None
    project_id: str | None
    retryable: bool


@dataclass(frozen=True, slots=True)
class ValidatedResponseHeaders:
    content_type: str
    content_length: int | None
    header_bytes: int


HTML_CONTENT_TYPES = frozenset({"application/xhtml+xml", "text/html"})
EMPTY_HEADERS: Mapping[str, str] = MappingProxyType({})
