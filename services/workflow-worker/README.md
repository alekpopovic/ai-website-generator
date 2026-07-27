# Workflow Worker

Hosts Temporal workflow definitions that durably coordinate scans, datasets, generation, validation, repair, and optional training. Workflows pass database identifiers and object-storage keys, delegate heavy work to activity workers, and implement retry, cancellation, timeout, and compensation policies.

Run locally after the Temporal development stack is healthy:

```sh
uv run platform-workflow-worker
```

The process polls the `control` task queue, logs explicit ready/stopping/stopped health transitions,
and shuts down cooperatively on `SIGINT` or `SIGTERM`. Activity implementations remain in their
resource-isolated worker services; this initial worker registers orchestration skeletons only.
