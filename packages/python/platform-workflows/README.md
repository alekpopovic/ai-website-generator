# Platform Workflows

Shared Temporal client, worker, queue, retry, heartbeat, cancellation, workflow identity, job-event,
dispatch, orchestration, and test foundations. Workflow code is deterministic and passes only UUIDs
and object-storage keys. Network, database, storage, browser, model, and clock-dependent work belongs
in activities.

The scan campaign workflow is fully orchestrated through bounded target children and registered
activities. Dataset, generation, and training workflows remain staged foundations for later prompts.
