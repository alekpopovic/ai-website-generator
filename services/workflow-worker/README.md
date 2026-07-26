# Workflow Worker

Hosts Temporal workflow definitions that durably coordinate scans, datasets, generation, validation, repair, and optional training. Workflows pass database identifiers and object-storage keys, delegate heavy work to activity workers, and implement retry, cancellation, timeout, and compensation policies.
