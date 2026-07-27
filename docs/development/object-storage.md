# Object Storage

## Responsibilities and access

`platform-clients.object_storage` is the only application-facing S3 abstraction. MinIO is used in
development with an explicit endpoint and path-style addressing. Production AWS mode omits a custom
endpoint and uses the standard AWS credential chain or explicitly injected temporary credentials.

All five buckets are private. Angular receives no bucket credentials, list access, MinIO endpoint,
or general-purpose S3 client. FastAPI may issue short-lived read URLs after authorization. Presigned
uploads are limited by type to approved `user-assets/{project_id}/{asset_id}/{filename}` flows and
bind the content type, SHA-256 checksum, immutable `If-None-Match` condition, and a maximum 15-minute
expiry.

For AWS production configuration, set `MINIO_PROVIDER=aws`, leave `MINIO_ENDPOINT` blank, set the
region, and provide credentials through the workload identity or AWS SDK credential chain. Static
production credentials are discouraged. Development uses `MINIO_PROVIDER=minio` with the local
endpoint and explicit `.env` credentials.

## Keys and immutability

Typed builders are mandatory:

- `scans/{website_id}/{page_scan_id}/...`
- `datasets/{dataset_id}/{version_id}/...`
- `generated/{project_id}/{site_version_id}/...`
- `models/{model_id}/{version_id}/...`
- `user-assets/{project_id}/{asset_id}/...`

Builders require UUID identifiers, normalize filename segments, and reject absolute paths,
backslashes, encoded ambiguity, empty components, and `.` or `..` traversal. Do not concatenate keys
manually or translate keys into local filesystem paths.

Uploads require a caller-computed lowercase SHA-256 digest. The client sends the corresponding S3
checksum, persists the hex digest as object metadata, and verifies streamed bytes before completion.
Re-uploading the same digest with identical content metadata is idempotent; different content or
metadata at an immutable key fails. Large streams use bounded multipart buffers and per-part
server-side checksums. Downloads calculate SHA-256 while streaming and fail if the declared digest
does not match.

Retention metadata records application policy intent; authoritative ownership, authorization,
lineage, licensing, and retention state remain in PostgreSQL through `ArtifactMetadataRepository`.
Object metadata is not an authorization database.

## HTML and JSON compression

Use `gzip_html`, `gzip_json`, or `gzip_stream`, then upload with `content_encoding="gzip"` and the
checksum of the compressed stream. JSON serialization is deterministic and rejects non-standard
NaN values. These helpers do not execute or interpret artifact content.

## Readiness and tests

The API dependency graph owns one asynchronous client. Readiness checks perform `HeadBucket` against
all five expected buckets. Default unit tests use `InMemoryObjectStorage` and never contact MinIO.

MinIO integration tests are opt-in:

```sh
MINIO_INTEGRATION_TESTS=true task integration-test
```

The test suite uses unique typed keys, tags every created object with `aiwg-test-artifact=true`, and
removes only those exact objects during cleanup.

## Development test-artifact CLI

Inspect tagged objects:

```sh
task storage-test-artifacts
```

Removal is restricted to `APP_ENV=development` or `test` with the MinIO provider, considers only
objects carrying the test tag, and requires an explicit confirmation phrase:

```sh
uv run platform-storage-artifacts remove --confirm REMOVE-TEST-ARTIFACTS
```

The CLI cannot remove untagged objects.
