"""System and deterministic DNS resolvers returning every A and AAAA address."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections import defaultdict, deque
from collections.abc import Iterable

from platform_clients.network_safety.models import NetworkFailureCode, NetworkSafetyError

type IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class SystemDnsResolver:
    """Resolve A and AAAA through the event loop without using proxy environment state."""

    async def resolve(self, hostname: str, port: int) -> frozenset[IpAddress]:
        try:
            loop = asyncio.get_running_loop()
            ipv4, ipv6 = await asyncio.gather(
                self._resolve_family(loop, hostname, port, socket.AF_INET),
                self._resolve_family(loop, hostname, port, socket.AF_INET6),
            )
        except (OSError, TimeoutError) as error:
            raise NetworkSafetyError(
                NetworkFailureCode.DNS_RESOLUTION_FAILED,
                "DNS resolution failed.",
                retryable=True,
            ) from error
        addresses = {*ipv4, *ipv6}
        if not addresses:
            raise NetworkSafetyError(
                NetworkFailureCode.DNS_NO_RECORDS,
                "DNS returned no usable A or AAAA records.",
                retryable=True,
            )
        return frozenset(addresses)

    @staticmethod
    async def _resolve_family(
        loop: asyncio.AbstractEventLoop,
        hostname: str,
        port: int,
        family: socket.AddressFamily,
    ) -> set[IpAddress]:
        try:
            records = await loop.getaddrinfo(
                hostname,
                port,
                family=family,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except socket.gaierror as error:
            no_data_codes = {socket.EAI_NONAME}
            if hasattr(socket, "EAI_NODATA"):
                no_data_codes.add(socket.EAI_NODATA)
            if error.errno in no_data_codes:
                return set()
            raise
        addresses: set[IpAddress] = set()
        for record_family, _, _, _, sockaddr in records:
            if record_family == socket.AF_INET:
                addresses.add(ipaddress.IPv4Address(sockaddr[0]))
            elif record_family == socket.AF_INET6:
                addresses.add(ipaddress.IPv6Address(sockaddr[0]))
        return addresses


class SequenceDnsResolver:
    """Offline fake supporting stable, mixed, failed, and rebinding DNS test sequences."""

    def __init__(self, records: dict[str, Iterable[Iterable[str] | Exception]]) -> None:
        self._records: dict[str, deque[Iterable[str] | Exception]] = defaultdict(deque)
        for hostname, sequence in records.items():
            self._records[hostname.casefold()].extend(sequence)
        self.calls: list[tuple[str, int]] = []

    async def resolve(self, hostname: str, port: int) -> frozenset[IpAddress]:
        key = hostname.casefold()
        self.calls.append((key, port))
        sequence = self._records[key]
        if not sequence:
            raise NetworkSafetyError(
                NetworkFailureCode.DNS_NO_RECORDS,
                "DNS returned no usable A or AAAA records.",
                retryable=True,
            )
        value = sequence[0] if len(sequence) == 1 else sequence.popleft()
        if isinstance(value, NetworkSafetyError):
            raise value
        if isinstance(value, Exception):
            raise NetworkSafetyError(
                NetworkFailureCode.DNS_RESOLUTION_FAILED,
                "DNS resolution failed.",
                retryable=True,
            ) from value
        addresses = frozenset(ipaddress.ip_address(address) for address in value)
        if not addresses:
            raise NetworkSafetyError(
                NetworkFailureCode.DNS_NO_RECORDS,
                "DNS returned no usable A or AAAA records.",
                retryable=True,
            )
        return addresses
