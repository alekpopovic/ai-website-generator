# Embedding Indexing and Drift

## Authority and safety boundary

PostgreSQL SectionPattern records are authoritative. The embedding worker recomputes `section-retrieval-v1` from controlled section type, abstract copy purpose, registered component names, layout, responsive behavior, category, language, and controlled style tags. It requires an exact match with the persisted retrieval document before inference. `VectorPoint` validation independently rejects markup, control characters, and URLs.

The worker never reads raw HTML, screenshots, extracted page prose, source asset URLs, brand names, object-storage keys, prompts, or proprietary source code. Temporal receives only the embedding-run UUID, and heartbeats contain only stage and completed counts.

## Version identity and model drift

A physical collection identity contains:

- embedding provider;
- embedding model name;
- exact model digest;
- retrieval serialization schema version;
- named-vector name.

Changing any value creates a different vector space or serialization contract. Existing vectors must not be mixed with the new identity. Incremental indexing therefore fails readiness with `embedding_reindex_required` when the stable alias does not target the expected collection.

To migrate safely, create a `reindex` embedding run with `promote_alias=true`. The worker prepares the new collection, discovers dimensions from installed-model metadata (or a fixed abstract probe when metadata is unavailable), re-embeds all eligible PostgreSQL patterns, verifies the returned model digest for every batch, and atomically switches the alias only after complete success. The old collection is retained for rollback.

Embedding drift can occur without a model name change when weights, quantization, provider behavior, or tokenizer changes alter the digest. Digest changes always require the same full reindex procedure. Never edit a digest or collection identity to bypass this requirement.

## Idempotency, failures, and removal

Qdrant point IDs equal SectionPattern UUIDs, making retries replacement-safe. PostgreSQL stores one status row per pattern and physical collection, including document hash, model digest, attempts, timestamps, and sanitized error code. Run-level progress and append-only failure history are available through the control-plane API.

Removal eligibility is checked from PostgreSQL before every run and before model readiness. Rejected, provenance-restricted, soft-removed, expired, or legally suppressed records are deleted from every recorded physical collection, not only the active alias. A missing or changed model therefore cannot block a legal-removal sweep. Qdrant remains a disposable retrieval index and is never used to restore application truth.
