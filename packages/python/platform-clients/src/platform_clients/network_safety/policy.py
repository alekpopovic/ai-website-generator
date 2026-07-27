"""URL, DNS, redirect, connection-time, and peer-address safety enforcement."""

from __future__ import annotations

import contextlib
import ipaddress
import re
import socket
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

from platform_clients.network_safety.models import (
    ApprovedUrl,
    NetworkBlockedAuditEvent,
    NetworkFailureCode,
    NetworkRequestContext,
    NetworkSafetyError,
    NetworkSafetyPolicy,
    ValidatedResponseHeaders,
)
from platform_clients.network_safety.protocols import (
    DnsResolver,
    NetworkSafetyAuditor,
    NullNetworkSafetyAuditor,
)
from platform_clients.network_safety.response import bounded_body, validate_html_response_headers

type IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_METADATA_HOSTS = frozenset(
    {
        "instance-data",
        "metadata",
        "metadata.azure.internal",
        "metadata.google.internal",
        "metadata.google",
    }
)
_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("169.254.170.2"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_BLOCKED_IPV6_TRANSITION_NETWORKS = (
    ipaddress.IPv6Network("::ffff:0:0/96"),
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("64:ff9b:1::/48"),
    ipaddress.IPv6Network("2001::/32"),
    ipaddress.IPv6Network("2002::/16"),
)


class NetworkSafetySubsystem:
    """Single reusable policy boundary for every untrusted outbound URL."""

    def __init__(
        self,
        resolver: DnsResolver,
        *,
        policy: NetworkSafetyPolicy | None = None,
        auditor: NetworkSafetyAuditor | None = None,
    ) -> None:
        self._resolver = resolver
        self.policy = policy or NetworkSafetyPolicy()
        self._auditor = auditor or NullNetworkSafetyAuditor()

    async def prepare(self, value: str, context: NetworkRequestContext) -> ApprovedUrl:
        """Validate syntax and all current A/AAAA answers before a request is scheduled."""
        try:
            scheme, hostname, port, normalized, literal = self._parse(value, context)
            addresses = (
                frozenset({literal})
                if literal is not None
                else await self._resolver.resolve(hostname, port)
            )
            self._validate_addresses(addresses)
            return ApprovedUrl(
                url=normalized,
                scheme=scheme,
                hostname=hostname,
                port=port,
                addresses=addresses,
            )
        except NetworkSafetyError as error:
            await self._audit_block(value, context, error)
            raise

    async def prepare_redirect(
        self,
        previous: ApprovedUrl,
        location: str,
        *,
        redirect_count: int,
        context: NetworkRequestContext,
    ) -> ApprovedUrl:
        """Resolve relative redirects and fully re-run policy for every hop."""
        if redirect_count >= self.policy.limits.max_redirects:
            error = NetworkSafetyError(
                NetworkFailureCode.REDIRECT_LIMIT_EXCEEDED,
                "The response exceeded the redirect limit.",
            )
            await self._audit_block(previous.url, context, error)
            raise error
        if not location or any(ord(character) < 32 for character in location):
            error = NetworkSafetyError(
                NetworkFailureCode.REDIRECT_LOCATION_INVALID,
                "The redirect location is invalid.",
            )
            await self._audit_block(previous.url, context, error)
            raise error
        try:
            target = urljoin(previous.url, location)
        except ValueError as cause:
            error = NetworkSafetyError(
                NetworkFailureCode.REDIRECT_LOCATION_INVALID,
                "The redirect location is invalid.",
            )
            await self._audit_block(previous.url, context, error)
            raise error from cause
        return await self.prepare(target, context)

    async def revalidate_before_connection(
        self,
        approved: ApprovedUrl,
        context: NetworkRequestContext,
        *,
        peer_address: str | None = None,
    ) -> ApprovedUrl:
        """Re-resolve immediately before connect and optionally verify the connected peer."""
        try:
            literal = self._literal(approved.hostname)
            addresses = (
                frozenset({literal})
                if literal is not None
                else await self._resolver.resolve(approved.hostname, approved.port)
            )
            if addresses != approved.addresses:
                raise NetworkSafetyError(
                    NetworkFailureCode.DNS_REBINDING,
                    "DNS answers changed between validation and connection.",
                )
            self._validate_addresses(addresses)
            if peer_address is not None:
                try:
                    peer = ipaddress.ip_address(peer_address.split("%", 1)[0])
                except ValueError as error:
                    raise NetworkSafetyError(
                        NetworkFailureCode.PEER_ADDRESS_MISMATCH,
                        "The connected peer address is invalid.",
                    ) from error
                self._validate_addresses(frozenset({peer}))
                if peer not in addresses:
                    raise NetworkSafetyError(
                        NetworkFailureCode.PEER_ADDRESS_MISMATCH,
                        "The connected peer was not present in the approved DNS answers.",
                    )
            return ApprovedUrl(
                url=approved.url,
                scheme=approved.scheme,
                hostname=approved.hostname,
                port=approved.port,
                addresses=addresses,
            )
        except NetworkSafetyError as error:
            await self._audit_block(approved.url, context, error)
            raise

    async def validate_html_response(
        self,
        approved: ApprovedUrl,
        headers: Mapping[str, str] | Iterable[tuple[str, str]],
        context: NetworkRequestContext,
    ) -> ValidatedResponseHeaders:
        try:
            return validate_html_response_headers(headers, self.policy.limits)
        except NetworkSafetyError as error:
            await self._audit_block(approved.url, context, error)
            raise

    async def stream_bounded_body(
        self,
        approved: ApprovedUrl,
        source: AsyncIterable[bytes],
        context: NetworkRequestContext,
    ) -> AsyncIterator[bytes]:
        try:
            async for chunk in bounded_body(source, self.policy.limits):
                yield chunk
        except NetworkSafetyError as error:
            await self._audit_block(approved.url, context, error)
            raise

    def _parse(
        self, value: str, context: NetworkRequestContext
    ) -> tuple[str, str, int, str, IpAddress | None]:
        if (
            not value
            or len(value) > 8_192
            or value != value.strip()
            or "\\" in value
            or any(ord(character) < 32 for character in value)
        ):
            raise NetworkSafetyError(NetworkFailureCode.URL_INVALID, "The URL is invalid.")
        try:
            parsed = urlsplit(value)
        except ValueError as error:
            raise NetworkSafetyError(
                NetworkFailureCode.URL_INVALID, "The URL is invalid."
            ) from error
        scheme = parsed.scheme.casefold()
        if scheme not in {"http", "https"}:
            raise NetworkSafetyError(
                NetworkFailureCode.SCHEME_NOT_ALLOWED,
                "Only HTTP and HTTPS URLs are allowed.",
            )
        if parsed.username is not None or parsed.password is not None:
            raise NetworkSafetyError(
                NetworkFailureCode.CREDENTIALS_NOT_ALLOWED,
                "URL credentials are not allowed.",
            )
        if parsed.hostname is None:
            raise NetworkSafetyError(
                NetworkFailureCode.HOSTNAME_INVALID, "The URL hostname is invalid."
            )
        try:
            port = parsed.port or (443 if scheme == "https" else 80)
        except ValueError as error:
            raise NetworkSafetyError(
                NetworkFailureCode.PORT_BLOCKED, "The URL port is invalid."
            ) from error
        allowed_ports = self.policy.default_ports
        if context.administrator_port_access:
            allowed_ports |= self.policy.administrator_ports
        if port not in allowed_ports:
            raise NetworkSafetyError(
                NetworkFailureCode.PORT_BLOCKED,
                "The URL port is not permitted by outbound policy.",
            )

        raw_hostname = parsed.hostname.rstrip(".").casefold()
        if not raw_hostname or "%" in raw_hostname:
            raise NetworkSafetyError(
                NetworkFailureCode.HOSTNAME_INVALID, "The URL hostname is invalid."
            )
        literal = self._literal(raw_hostname)
        if literal is None:
            if self._is_encoded_ipv4(raw_hostname):
                raise NetworkSafetyError(
                    NetworkFailureCode.ENCODED_IP_BLOCKED,
                    "Non-canonical IP address encodings are blocked.",
                )
            try:
                hostname = raw_hostname.encode("idna").decode("ascii").casefold()
            except UnicodeError as error:
                raise NetworkSafetyError(
                    NetworkFailureCode.HOSTNAME_INVALID, "The URL hostname is invalid."
                ) from error
            labels = hostname.split(".")
            if hostname == "localhost" or hostname.startswith("localhost."):
                raise NetworkSafetyError(
                    NetworkFailureCode.HOSTNAME_BLOCKED, "Localhost names are blocked."
                )
            if hostname in _METADATA_HOSTS:
                raise NetworkSafetyError(
                    NetworkFailureCode.METADATA_ENDPOINT_BLOCKED,
                    "Cloud metadata hostnames are blocked.",
                )
            if any(hostname.endswith(suffix) for suffix in self.policy.internal_hostname_suffixes):
                raise NetworkSafetyError(
                    NetworkFailureCode.HOSTNAME_BLOCKED,
                    "Internal-only hostname suffixes are blocked.",
                )
            if len(labels) < 2 or any(_HOST_LABEL.fullmatch(label) is None for label in labels):
                raise NetworkSafetyError(
                    NetworkFailureCode.HOSTNAME_BLOCKED,
                    "Single-label and malformed hostnames are blocked.",
                )
        else:
            hostname = literal.compressed

        rendered_host = f"[{hostname}]" if ":" in hostname else hostname
        default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        netloc = rendered_host if default_port else f"{rendered_host}:{port}"
        normalized = urlunsplit(SplitResult(scheme, netloc, parsed.path or "/", parsed.query, ""))
        return scheme, hostname, port, normalized, literal

    @staticmethod
    def _literal(hostname: str) -> IpAddress | None:
        try:
            return ipaddress.ip_address(hostname)
        except ValueError:
            return None

    @staticmethod
    def _is_encoded_ipv4(hostname: str) -> bool:
        if ":" in hostname or not re.fullmatch(r"[0-9a-fx.]+", hostname):
            return False
        with contextlib.suppress(OSError, OverflowError):
            socket.inet_aton(hostname)
            return True
        return False

    @staticmethod
    def _validate_addresses(addresses: frozenset[IpAddress]) -> None:
        if not addresses:
            raise NetworkSafetyError(
                NetworkFailureCode.DNS_NO_RECORDS,
                "DNS returned no usable A or AAAA records.",
                retryable=True,
            )
        blocked = {
            address
            for address in addresses
            if not address.is_global
            or address.is_loopback
            or address.is_private
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
            or (
                isinstance(address, ipaddress.IPv6Address)
                and any(address in network for network in _BLOCKED_IPV6_TRANSITION_NETWORKS)
            )
        }
        metadata = addresses & _METADATA_ADDRESSES
        if metadata:
            raise NetworkSafetyError(
                NetworkFailureCode.METADATA_ENDPOINT_BLOCKED,
                "Cloud metadata network addresses are blocked.",
            )
        if blocked:
            code = (
                NetworkFailureCode.DNS_MIXED_SCOPE
                if len(blocked) != len(addresses)
                else NetworkFailureCode.ADDRESS_BLOCKED
            )
            raise NetworkSafetyError(
                code,
                "DNS returned a private, local, reserved, multicast, or unspecified address.",
            )

    async def _audit_block(
        self, value: str, context: NetworkRequestContext, error: NetworkSafetyError
    ) -> None:
        hostname: str | None = None
        with contextlib.suppress(ValueError):
            hostname = urlsplit(value).hostname
        event = NetworkBlockedAuditEvent(
            action="network.request_blocked",
            component=context.component,
            failure_code=error.code,
            safe_url=self._safe_url(value),
            hostname=hostname.casefold() if hostname else None,
            request_id=context.request_id,
            project_id=context.project_id,
            retryable=error.retryable,
        )
        with contextlib.suppress(Exception):
            await self._auditor.blocked(event)

    @staticmethod
    def _safe_url(value: str) -> str:
        with contextlib.suppress(ValueError):
            parsed = urlsplit(value)
            if parsed.scheme and parsed.hostname:
                hostname = parsed.hostname.casefold()
                return f"{parsed.scheme.casefold()}://{hostname}/"
        return "invalid-url"
