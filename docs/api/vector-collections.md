# Vector Collection Diagnostics API

`GET /api/v1/admin/vector-collections/statistics` returns the stable alias, active and expected
physical collection names, status, point and indexed-vector counts, dimensions, and the configured
embedding provider/model/digest/schema identity.

The endpoint requires a bearer-authenticated user whose normalized email is in the fail-closed
`SECURITY_ADMINISTRATOR_EMAILS` allowlist. It performs metadata and Qdrant inspection only. It does
not embed content, warm a model, create a collection, promote an alias, or reindex data. Missing
Ollama dimension metadata produces a dependency-unavailable response rather than triggering model
inference inside FastAPI.
