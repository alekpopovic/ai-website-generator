# Scan artifact API

Scan artifacts are private, project-owned records under
`/api/v1/projects/{project_id}/scan-campaigns/{campaign_id}`.

- `GET /pages/{page_id}/artifacts` lists bounded artifact metadata without object keys or bodies.
- `GET /artifacts/{artifact_id}/screenshot` streams an integrity-checked PNG through FastAPI for the
  Angular application.
- `GET /artifacts/{artifact_id}/read-url` creates a short-lived authorized object URL. Raw response and
  rendered HTML require administrator access. Angular must not use this endpoint to contact MinIO/S3;
  it must use the screenshot endpoint for visual previews.
- `POST /artifacts/{artifact_id}/removal-request` records an auditable removal request and starts the
  non-destructive deletion-workflow placeholder.

Artifacts in `pending_deletion`, `expired`, or `deleted` state cannot be read. Legal-hold artifacts can
be read by authorized principals but cannot receive a removal request. Presigned URLs expire after
60–900 seconds and must not be logged.

Raw and rendered HTML are hostile source material. They are never returned inline by normal API routes,
must not be rendered in the application origin, and are not available to ordinary project owners by
default.
