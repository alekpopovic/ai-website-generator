# Vector Reindexing

Reindexing is an explicit heavy operation. Run it from an operator shell or embedding-worker
environment with private access to Ollama and Qdrant; never call it from a FastAPI handler.

Inspect the no-I/O plan:

```bash
task vector-reindex
```

Create or resume the configured embedding-version collection and copy active abstract records:

```bash
uv run platform-vector-reindex --execute
```

After checking the reported target, point count, model digest, and dimensions, rerun with atomic
promotion:

```bash
uv run platform-vector-reindex --execute --promote --confirm-alias design-patterns
```

Configuration uses `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_ALIAS`,
`QDRANT_VECTOR_NAME`, `QDRANT_SERIALIZATION_SCHEMA_VERSION`, `OLLAMA_URL`, and
`OLLAMA_EMBEDDING_MODEL`. The command is resumable because target point IDs and upserts are
idempotent. It stops if the model digest changes during the run. Promotion deletes only the old
alias binding and atomically creates the new binding; it does not delete the former collection.

The command discovers vector dimensions from model metadata. If metadata is absent, the command—not
the API—embeds one fixed abstract probe. Default unit tests use the in-memory store and never require
Qdrant, Ollama, internet access, or a GPU. To run the opt-in integration test against the local
container:

```bash
QDRANT_INTEGRATION_TESTS=true uv run pytest -m integration \
  packages/python/platform-clients/tests/test_qdrant_integration.py
```

The test uses a unique `aiwg-test-*` alias and collection and removes only those exact resources.
