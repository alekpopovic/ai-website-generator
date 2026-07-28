# API Documentation

Control-plane API conventions, authentication, authorization, versioning, idempotency, pagination, errors, asynchronous job semantics, and generated specifications belong here.

The control plane exposes domain contracts under `/api/v1`. Process health remains unversioned under `/health` so container and orchestration probes do not depend on a domain API version.

Errors use `application/problem+json` with stable `code` and `request_id` extensions. Validation responses include sanitized parameter locations and reasons but never echo rejected input. Successful versioned responses use typed envelopes; collection routes will use bounded offset-pagination primitives until a domain requires an explicitly designed cursor.

See [API client generation](../development/api-client-generation.md) for the deterministic FastAPI
OpenAPI to Angular SDK workflow.

| Method | Path                                          | Purpose                                                |
| ------ | --------------------------------------------- | ------------------------------------------------------ |
| `GET`  | `/health/live`                                | Process liveness without dependency I/O                |
| `GET`  | `/health/ready`                               | Critical control-plane dependency readiness            |
| `GET`  | `/health/dependencies`                        | Critical and worker-facing dependency diagnostics      |
| `GET`  | `/api/v1/version`                             | API contract and service build identity                |
| `GET`  | `/api/v1/models/readiness`                    | Authenticated model installation and capability status |
| `POST` | `/api/v1/admin/models/{model_role}/warm-up`   | Admin-only durable worker-side model warm-up           |
| `GET`  | `/api/v1/admin/vector-collections/statistics` | Admin-only vector collection metadata                  |

See [Vector collection diagnostics](vector-collections.md) for the collection identity and
administrator authorization contract.

See [Scan campaigns](scan-campaigns.md) for project ownership, configuration, lifecycle controls,
targets, page projections, failures, and the control-only Temporal dispatch contract.

See [scan-target imports](scan-target-imports.md) for streamed TXT/CSV validation, dry-run commits,
row-level outcomes, and error export.

See [analysis profiles](analysis-profiles.md) for historical structured analysis, deterministic
section retrieval documents, duplicate lineage, and owner-audited curation.
