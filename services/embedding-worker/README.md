# Embedding Worker

Runs Temporal `index-section-patterns` activities on the private `embedding` task queue. The activity receives only an `embedding_run_id`, reloads authoritative PostgreSQL state, recomputes the controlled retrieval document, calls the configured private Ollama embedding model in bounded batches, and idempotently upserts points into a versioned Qdrant collection.

Eligibility requires an approved SectionPattern with authorized provenance, no legal suppression, and no expired retrieval window. Rejected, restricted, removed, expired, or legally suppressed patterns are deleted from every physical collection recorded in PostgreSQL, including retained rollback collections.

An incremental run requires the stable alias already to identify the configured model and serialization version. A model or digest change fails with `embedding_reindex_required`. A full reindex prepares the new physical collection, embeds every eligible PostgreSQL record, and switches the alias only after every batch succeeds. The old collection remains available for rollback but remains subject to removal sweeps.

Start locally with:

```shell
task embedding-worker
```

The worker requires PostgreSQL, Temporal, private Ollama, and Qdrant. `EMBEDDING_WORKER_MAX_ACTIVITIES` defaults to `2`; each run additionally enforces its persisted batch size between 1 and 256. Default CI uses `FakeLLMGateway`, `InMemoryVectorStore`, and deterministic repository fixtures.
