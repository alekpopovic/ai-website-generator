# ADR 0018: Typed immutable scan artifacts

- Status: Accepted
- Date: 2026-07-28

## Context

Crawler and browser outputs previously had object keys on page records but no single typed ownership,
authorization, retention, or provenance record. Browser captures also combined diagnostics and semantic
data in a small number of manifests, making selective retention and safe access difficult.

## Decision

Every retained scan object has an immutable content-addressed key, mandatory SHA-256, validated S3
metadata, and a `scan_artifacts` row. The row owns artifact type, project/campaign/source/page lineage,
optional viewport scan, content metadata, scanner version, provenance, access policy, retention policy,
and removal lifecycle. Upload is completed and checksum-verified before its record is committed; retries
accept an identical object and relational record but reject different bytes or metadata at the same key.

Raw response HTML is created only when the campaign explicitly enables it. Browser captures persist
rendered HTML, full and viewport PNGs, semantic snapshots, extracted nodes, style summaries, network
manifests, console diagnostics, and a final metadata manifest. Large HTML and JSON values are
deterministically gzip-compressed. Desktop and mobile full-page captures use distinct artifact types.

Project ownership gates all reads. Raw and rendered HTML presigning additionally requires the explicit
administrator allowlist and is not intended for Angular. Angular-compatible screenshot viewing streams
only integrity-checked `image/png` artifacts through FastAPI with private caching, MIME sniffing,
cross-origin, and content-security headers. Other authorized presigned reads are short-lived and remain
an API-controlled export capability.

Removal requests change relational retention and provenance state to pending, append an audit event,
and dispatch an `ArtifactDeletionWorkflow` placeholder using only IDs and the object key. The placeholder
does not delete data. A later policy-aware implementation must evaluate legal hold, retention,
transitive provenance, retry safety, and object deletion before marking a record deleted.

## Consequences

- PostgreSQL is authoritative for artifact authorization and lifecycle; S3 remains authoritative for
  bytes and mirrors bounded provenance metadata.
- Scan metadata manifests reference the checksum and key of every preceding artifact but cannot include
  their own checksum without a circular identity.
- Existing legacy key columns remain as compatibility projections while typed rows become the access
  boundary.
- Object uploads can precede a failed database transaction; content-addressed idempotency makes retry
  safe, while orphan reconciliation remains future operational work.
