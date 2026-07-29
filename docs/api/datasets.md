# Dataset builds

Datasets and their versions are project-owned. Every command resolves the authenticated owner through
the complete project, dataset, version, and build chain; identifiers from another project return the
same not-found response as an unknown identifier.

Creating a version produces an editable draft only. Direct sealing is not exposed. A draft becomes
immutable only after `DatasetBuildWorkflow` has produced a passing quality report and a canonical
manifest checksum.

## Build lifecycle

| Method | Path                                                                                          | Purpose                                           |
| ------ | --------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `POST` | `/projects/{project_id}/datasets/{dataset_id}/versions/{version_id}/builds`                   | Idempotently queue a build                        |
| `GET`  | `/projects/{project_id}/datasets/{dataset_id}/versions/{version_id}/builds/{build_id}`        | Inspect durable status and stage                  |
| `POST` | `/projects/{project_id}/datasets/{dataset_id}/versions/{version_id}/builds/{build_id}/cancel` | Request cooperative cancellation                  |
| `POST` | `/projects/{project_id}/datasets/{dataset_id}/versions/{version_id}/builds/{build_id}/retry`  | Queue a new attempt after failure or cancellation |

Start and retry require bounded URL-safe idempotency keys. The API commits the `dataset_builds` row
before dispatching Temporal, and a partial unique index prevents two queued/running/cancelling builds
for the same version. Temporal receives only build, project, user, and version UUIDs.

The workflow validates the frozen selection policy; resolves candidates; excludes rejected,
unapproved, low-confidence, expired, removed, and legally suppressed records; checks provenance;
deduplicates hashes; rejects source prose and branding; calculates category, language, section,
layout, and style distributions; assigns case-insensitive source domains to deterministic train,
validation, and test splits; writes a quality report; materializes the canonical manifest; optionally
queues missing embeddings; and finally seals the version.

Quality policy thresholds cover maximum source-domain share, minimum category count, maximum repeated
template share, required section types, and maximum serialized text size. The report also detects
schema mismatch, invalid URL/markup/email tokens, insufficient confidence exclusions, copied branding
or prose, fewer than three eligible domains, and cross-split domain leakage. With at least three
domains, deterministic hash ordering guarantees that train, validation, and test are all present
while keeping every canonical domain in exactly one split. Failed reports leave the version as a
draft and retain safe finding codes and aggregate counts for inspection and retry.

Cancellation is cooperative between bounded stages. Retrying creates a new build attempt and reuses
the version's selection policy; it never mutates or retries a sealed version. Optional embedding work
is queued separately and is not a sealing prerequisite.
