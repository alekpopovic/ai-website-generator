# ADR 0019: Versioned normalized analysis contracts

- Status: Accepted
- Date: 2026-07-28

## Context

Browser scans contain hostile, proprietary, and high-volume source observations. Later retrieval,
generation, and optimization stages need reusable design knowledge without copying identities,
assets, prose, code, or complete compositions. Structured inference also requires a strict output
contract that can evolve without silently reinterpreting persisted data.

## Decision

Use the versioned Pydantic `WebsiteProfile` family in `platform-schemas` as the analysis trust
boundary. It permits only bounded design tokens, controlled section/component/copy-purpose
registries, abstract responsive behavior, controlled accessibility observations, confidence, and
identifier-only provenance.

Generated JSON Schema artifacts are committed and verified for freshness. Persisted payloads carry
an integer `schema_version`; upgrades use explicitly registered sequential migrations and fail
closed on missing paths or future versions. Deterministic conversion consumes only browser style
frequencies and makes no model call.

## Consequences

- Raw copy, brand/customer names, logos, source assets, HTML, URLs, and executable material have no
  representation in the normalized schema.
- Adding section or component types requires an intentional registry and schema-version review.
- Model providers can later consume the same generated JSON Schema without becoming part of the
  domain contract.
- New persisted versions require migration code and regenerated committed artifacts.
