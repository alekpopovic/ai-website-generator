# Platform Workflows

Shared Temporal client, worker, queue, retry, heartbeat, cancellation, workflow identity, job-event,
dispatch, orchestration, and test foundations. Workflow code is deterministic and passes only UUIDs
and object-storage keys. Network, database, storage, browser, model, and clock-dependent work belongs
in activities.

The four initial workflows are orchestration skeletons. Their named activities deliberately have no
business implementation yet.
