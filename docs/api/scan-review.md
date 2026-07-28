# Scan result review

Scan review is an owner-scoped control-plane capability under
`/api/v1/projects/{project_id}/scan-campaigns`. The API exposes campaign and target summaries,
filtered pages and failures, page details, duplicate groups, representative-selection decisions,
and durable activity projections. Selected failure retries pass only database identifiers to the
Temporal workflow.

Page detail responses include normalized metadata, classification and fingerprint relationships,
browser diagnostics, and a typed artifact manifest. The manifest never contains bucket names,
object keys, private storage credentials, or pre-signed URLs. Screenshot bytes are delivered by the
authenticated, integrity-checking screenshot endpoint. Raw and rendered HTML remain restricted and
are never rendered by Angular.

The Angular review interface lives inside a project workspace at
`/projects/{projectId}/scans`. Campaign details provide overview, targets, pages, failures, and
activity tabs. Page filters are bounded to persisted status, page type, and exact source domain;
failure filters use persisted stage and typed error code.
