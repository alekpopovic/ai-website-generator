# ADR 0020: Durable Parent/Child Scan Orchestration

- Status: Accepted
- Date: 2026-07-28

## Context

Scan campaigns can contain thousands of targets and each target can produce many private artifacts. A workflow must survive worker restarts, support operator controls, isolate partial failures, and avoid growing history with HTML, screenshots, or model output.

## Decision

`ScanCampaignWorkflow` pages target UUIDs from PostgreSQL and starts deterministic `ScanTargetWorkflow` children in bounded batches. Each child executes discovery, deterministic post-processing, representative rendering, structured page analysis with transactional profile persistence, and returns only counts. The parent creates an identifier-only embedding run and aggregates the authoritative PostgreSQL campaign state.

Target, browser, and AI concurrency have independent bounds. Activity workers additionally enforce process-wide queue limits. Signals pause new batches at durable checkpoints, resume from the same cursor, and cancel the workflow chain. Permanent authorization, robots, and network-policy failures are non-retryable; transient network, browser, inference, and persistence work use separate retry policies.

All stage activities are idempotent. Activity IDs, child workflow IDs, analysis run IDs, embedding idempotency keys, and job-event sequences are deterministic. Temporal receives UUIDs, bounded counts, and object keys only. PostgreSQL remains the progress authority; MinIO stores scan bodies; Qdrant is a rebuildable retrieval index.

## Consequences

- One failed target or page can produce `partially_succeeded` without discarding successful work.
- Retrying selected failures pages only their owning targets.
- Starting the same workflow ID is rejected by Temporal's fail-on-conflict and reject-duplicate policies.
- Very large campaigns remain bounded per activity payload, although production history thresholds must still be monitored and may later trigger continue-as-new between target pages.
