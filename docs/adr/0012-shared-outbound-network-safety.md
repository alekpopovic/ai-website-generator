# ADR 0012: Shared outbound network safety boundary

- Status: Accepted
- Date: 2026-07-27

## Context

Scrapy discovery, Playwright rendering, redirects, asset inspection, and future publishing connectors
all consume attacker-controlled URLs. Separate validation implementations drift and leave gaps around
IPv6, mixed DNS answers, redirect hops, DNS rebinding, response limits, and audit behavior.

## Decision

All untrusted outbound integrations use `platform_clients.network_safety`. The subsystem:

- permits only credential-free HTTP(S) URLs;
- defaults to ports 80 and 443 and requires both a configured port and administrator-authorized
  context for exceptions;
- normalizes IDNA hostnames and rejects internal names, metadata endpoints, noncanonical encoded IPs,
  and every non-global, loopback, private, link-local, multicast, reserved, or unspecified address;
- resolves and validates the complete A and AAAA answer set;
- pins that set, requires an identical resolution immediately before connection, and optionally
  verifies the connected peer address;
- treats changed answers as DNS rebinding rather than silently following them;
- fully validates every redirect and enforces a bounded hop count;
- bounds headers, decoded body bytes, connect/read/total/navigation time, and rejects non-HTML before
  browser or AI processing;
- exposes only stable typed failure codes and emits sanitized `network.request_blocked` audit events.

Framework adapters identify Scrapy, Playwright, asset-inspection, and publishing events while sharing
the exact policy. Callers must not enable automatic redirect following beneath this boundary.

## Consequences

DNS answer rotation between validation and connection is rejected, favoring safety over availability.
HTTP connectors should connect to an approved pinned address while retaining the original hostname
for TLS SNI and certificate verification, then report the peer address for comparison. Where a
framework does not expose DNS or peer control—especially Chromium—the policy runs at request
interception and again immediately before navigation, and a network firewall or egress proxy remains
mandatory.

See [Outbound network safety](../security/outbound-network-safety.md) for integration requirements and
production firewall guidance.
