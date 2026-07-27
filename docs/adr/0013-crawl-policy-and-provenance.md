# ADR 0013: Shared crawl policy and durable provenance

- Status: Accepted
- Date: 2026-07-28

## Decision

Crawler activities use the shared `platform_clients.crawl_policy` boundary for canonical URLs,
conservative trap filtering, `robots.txt`, URL patterns, depth/page budgets, per-domain token buckets,
and lease-based Redis locks. Every domain stores a `crawl_policy_records` snapshot and every admitted
or blocked crawl page stores its effective decision code and bounded policy evidence.

`robots.txt` compliance is mandatory for normal project users. A missing robots file permits crawling;
an unavailable, invalid, unsafe, redirect-looping, or oversized file fails closed. There is no public
API value that disables compliance. Network retrieval must use the shared SSRF subsystem at initial
resolution, every redirect, immediately before connection, and against the observed peer address when
the transport exposes it.

## Consequences

Policy decisions are reproducible and auditable without retaining the robots body in PostgreSQL. The
SHA-256 digest proves which content was evaluated; permitted sitemap declarations and the effective
crawl delay are retained. Redis coordination prevents separate workers from defeating per-domain
courtesy controls, while deterministic in-memory adapters keep default CI offline.
