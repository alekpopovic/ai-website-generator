# ADR 0010: Scan Campaign Control State and Workflow Dispatch

- Status: Accepted
- Date: 2026-07-27

## Context

Scan configuration, ownership, lifecycle state, discovered-page projections, rendered-page metadata,
and failures must be queryable independently of Temporal history. Starting and controlling a scan
also crosses the PostgreSQL and Temporal trust boundary. Holding a database transaction open while
calling Temporal would violate the established transaction architecture and could expose an
uncommitted campaign to workers.

This increment must dispatch `ScanCampaignWorkflow`, but crawling and browser work are not yet
implemented.

## Decision

PostgreSQL owns `scan_campaigns`, `scan_targets`, `crawl_pages`, `page_scans`, and `scan_failures`.
Every campaign is scoped through its project and the project's owner. Campaign and mutable worker
projections use optimistic versions, constrained string statuses, UTC timestamps, and bounded JSONB
only for typed configuration structures.

The API records a queued campaign and deterministic workflow ID inside the request transaction. A
request-owned after-commit action dispatches or signals Temporal only after that transaction exits
successfully. Duplicate starts are safe because workflow IDs incorporate the campaign UUID and
caller-supplied idempotency key. An unavailable Temporal service leaves the authoritative campaign
queued and emits a sanitized structured error; reconciliation of queued commands is a future
control-worker responsibility.

The current scan workflow accepts idempotent `pause`, `resume`, and `cancel` signals and performs no
activities. It remains durable until cancellation. Crawl, browser, analysis, embedding, and status
projection activities require later reviewed implementations.

State-changing API transitions are:

- `draft -> queued` for start;
- `queued|running -> pausing` for pause;
- `paused -> running` for resume;
- `queued|running|pausing|paused -> cancelling` for cancel;
- `failed|partially_succeeded -> queued` for retryable failures.

Workers will own transitions into `running`, `paused`, and terminal statuses. Only drafts and their
targets can be edited or deleted.

## Consequences

- FastAPI never crawls, renders, analyzes, or embeds a page.
- Temporal receives campaign, project, user, and idempotency identifiers only.
- Ownership checks are present in repository SQL, not only route code.
- A queued dispatch can require reconciliation after a post-commit Temporal outage; it must not be
  silently changed back to draft.
- Seed URL validation rejects statically identifiable SSRF destinations, while crawler and browser
  workers must still resolve and revalidate DNS, redirects, assets, and every subsequent request.
