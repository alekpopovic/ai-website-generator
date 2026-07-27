# ADR 0011: Streamed and staged scan-target imports

- Status: Accepted
- Date: 2026-07-27

## Context

Scan campaigns need to accept pasted domains and files containing tens of thousands of rows. The
control plane must validate targets without making network requests, preserve row-level provenance,
and let users review errors before changing a campaign.

## Decision

The API accepts raw `text/plain` and `text/csv` request bodies and incrementally decodes and parses
them. It does not use multipart form buffering. Imports are bounded to 50,000 rows, 20 MiB per
request, and 128 KiB per CSV record.

Each run creates a `scan_target_imports` record and one `scan_target_import_rows` record per parsed
source row. Outcomes are string-backed values: `accepted`, `duplicate`, `invalid`, `blocked`, and
`already_present`. Typed reason codes and source row numbers support deterministic review and CSV
error export. Optional CSV columns are retained as bounded JSON metadata.

Dry runs persist validation results but create no scan targets. A separate, attested commit command
rechecks campaign membership under a campaign row lock and inserts accepted targets in batches. The
same row lock serializes competing imports. Direct imports use the same parser but commit accepted
rows in the initial transaction.

Normalization strips accidental paths, converts Unicode hostnames to lowercase IDNA ASCII, removes
trailing dots, rejects credentials and non-HTTP schemes, and performs static SSRF checks. No DNS,
HTTP, public-suffix download, or other network request occurs. Public IP literals require both a
request flag and membership in the administrator allowlist; non-public IPs remain blocked.

## Consequences

- File memory usage is bounded independently of file size, while the per-import domain set remains
  bounded by the documented row limit.
- Upload progress can be reported by the browser; final row-processing progress is persisted and
  available from the import resource after the request completes.
- Public-suffix validation uses structural checks plus a bundled set of common multi-label suffixes.
  Scanner workers must still repeat SSRF validation after DNS resolution and on every redirect.
- Imports are atomic with the request transaction. A future asynchronous import workflow may be
  introduced if limits grow beyond control-plane-safe parsing workloads.
