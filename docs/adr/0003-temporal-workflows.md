# ADR 0003: Temporal as the Durable Workflow Engine

- Status: Accepted
- Date: 2026-07-27

## Context

Scanning, dataset preparation, generation, validation, repair, and training span multiple failure-prone activities and may run longer than an HTTP request or process lifetime.

## Decision

Use Temporal for durable orchestration. Workflows coordinate specialized activity queues, retries, timers, cancellation, and recovery. Activities must be idempotent, retry-safe, observable, and cancellable where practical. Workflow inputs and results contain database IDs, object keys, checksums, and compact state rather than large artifacts.

## Consequences

- Work continues safely across process restarts and transient failures.
- Workflow and activity versioning must preserve deterministic replay.
- Idempotency keys and explicit timeout and retry policies are mandatory.
- Temporal is coordination infrastructure, not artifact or application storage.
