# Vector Storage Architecture

## Responsibility and data policy

`platform_clients.vector_store.VectorStore` is the provider-neutral boundary. Qdrant is the first
adapter and `InMemoryVectorStore` is the deterministic offline implementation. Angular never calls
either provider. FastAPI may inspect bounded collection metadata; embedding, indexing, deletion
campaigns, and reindexing belong in workers or an explicitly invoked operations command.

Qdrant contains retrieval indexes, not application truth. PostgreSQL remains authoritative for
ownership, dataset lifecycle, source authorization, licensing, provenance, approval, and removals.
Every query requires a `project_id` and defaults to approved, verified records.

Each point stores one named dense vector (`design-pattern`), bounded `abstract_pattern_text`, and
only these validated metadata fields:

- `project_id`, `dataset_id`, and `dataset_version_id`;
- `source_website_id`, `source_page_id`, `section_pattern_id`, and normalized `source_domain`;
- `category`, `page_type`, `section_type`, `layout`, `style_tags`, and `language`;
- `confidence`, `approved`, and `provenance_status`.

The Pydantic payload rejects unknown fields. Abstract text rejects markup, URLs, control characters,
and oversized content. This boundary must receive design descriptions such as component structure,
spacing, hierarchy, and layout relationships—not source copy, HTML, logos, brand names, media,
code, or complete page compositions. `section_pattern_id` is the Qdrant point UUID, making repeated
upserts replacement-safe and idempotent.

## Collection versioning and aliases

A physical collection identity includes the embedding provider, model name, model digest,
serialization schema version, and named-vector name. Its bounded physical name includes readable
identity fragments plus a hash of the complete identity. The stable `design-patterns` alias is the
only normal retrieval target.

Embedding dimensions come from the configured model's Ollama `model_info.*.embedding_length`
metadata. API readiness never generates an embedding. The explicit reindex command may use one
fixed, non-proprietary abstract probe only when an installed provider omits dimension metadata.

Reindexing creates or resumes the new physical collection, creates payload indexes, scrolls only
the allowlisted abstract records from the active alias, re-embeds and idempotently upserts batches,
and atomically changes the alias after success. The old physical collection is retained for
rollback; removal is a separate reviewed operation.

## Filtering and diversity

`PayloadFilter` supports dataset and dataset-version IDs, source domains and websites, category,
page/section/layout classifications, style tags, language, confidence, approval, and provenance.
Project scope is mandatory. Qdrant payload indexes cover the principal tenant, dataset,
provenance, and design classification fields.

Source-diverse retrieval overfetches a bounded candidate set and applies a deterministic maximum
per source domain or source website. This prevents one scanned source from dominating context while
retaining provider-neutral semantics. Licensing and removal eligibility must still be resolved from
PostgreSQL before generation uses a result.

## Failure and readiness behavior

Health reports Qdrant transport availability. Readiness additionally requires the stable alias to
target the exact configured provider/model/digest/schema collection and its named-vector dimension
to match model metadata. A model change therefore fails readiness until a reindex is explicitly
completed and promoted. Qdrant errors are sanitized and never expose API keys or response bodies.
