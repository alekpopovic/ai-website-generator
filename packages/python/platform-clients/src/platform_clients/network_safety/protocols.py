"""Dependency-injection protocols for DNS and blocked-request auditing."""

from __future__ import annotations

import ipaddress
from typing import Protocol

from platform_clients.network_safety.models import NetworkBlockedAuditEvent


class DnsResolver(Protocol):
    async def resolve(
        self, hostname: str, port: int
    ) -> frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address]: ...


class NetworkSafetyAuditor(Protocol):
    async def blocked(self, event: NetworkBlockedAuditEvent) -> None: ...


class NullNetworkSafetyAuditor:
    async def blocked(self, event: NetworkBlockedAuditEvent) -> None:
        del event


class RecordingNetworkSafetyAuditor:
    def __init__(self) -> None:
        self.events: list[NetworkBlockedAuditEvent] = []

    async def blocked(self, event: NetworkBlockedAuditEvent) -> None:
        self.events.append(event)
