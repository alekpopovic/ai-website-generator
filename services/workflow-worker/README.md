# Workflow Worker

Hosts Temporal workflow definitions that durably coordinate scans, datasets, generation, validation, repair, and optional training. Workflows pass database identifiers and object-storage keys, delegate heavy work to activity workers, and implement retry, cancellation, timeout, and compensation policies.

It also hosts restart-safe PostgreSQL scan control activities for campaign validation, paged target
and representative enumeration, progress/job-event persistence, embedding-run preparation, and final
aggregation.

Run locally after the Temporal development stack is healthy:

```sh
uv run platform-workflow-worker
```

The process polls the `control` task queue, logs explicit ready/stopping/stopped health transitions,
and shuts down cooperatively on `SIGINT` or `SIGTERM`. Activity implementations remain in their
resource-isolated worker services; this initial worker registers orchestration skeletons only.
