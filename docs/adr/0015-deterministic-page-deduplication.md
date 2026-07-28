# ADR 0015: Deterministic page fingerprinting and deduplication

- Status: Accepted
- Date: 2026-07-28

## Context

Discovery may produce exact copies, tracking or timestamp variants, near-identical articles, and large
collections rendered by one template. Removing rows would destroy crawl provenance, while using an LLM
would make classification expensive, difficult to reproduce, and unavailable in default CI.

## Decision

The isolated crawler computes versioned cryptographic fingerprints for normalized URLs, visible text,
DOM structure, headings, links, response bytes, and DOM templates, plus a deterministic 64-bit text
SimHash. Executable and known analytics nodes, volatile attributes, timestamps, random identifiers,
CSRF values, and obvious dynamic tokens are normalized before hashing.

All discovered rows remain in PostgreSQL. A campaign-wide deterministic grouping pass assigns exact,
near-content, and template representatives selected by normalized URL and UUID. Exact normalized-content
hashes form exact groups. SimHash candidates use eight locality-sensitive bands and a bounded Hamming
distance. DOM-template hashes identify repeated collections independently of content similarity.
Grouping is serialized with a PostgreSQL advisory transaction lock and is safe to repeat. An explicit
worker CLI can recompute missing or outdated fingerprints from retained private raw-HTML artifacts.

## Consequences

- Results are offline, explainable, versioned, and independent of model availability.
- Source provenance is retained because duplicate relationships never delete pages.
- SimHash and template thresholds are heuristics and must be versioned when changed.
- Pages without retained HTML can be regrouped if already fingerprinted but cannot have missing
  fingerprints reconstructed.
