# ADR 0006: Storage Responsibilities

- Status: Accepted
- Date: 2026-07-27

## Context

The platform manages transactional application state, large immutable artifacts, ephemeral coordination data, and similarity-search indexes. No single store is appropriate for all four concerns.

## Decision

- PostgreSQL is authoritative for tenants, authorization, projects, jobs, artifact metadata, provenance, lineage, policy, and audits.
- MinIO or compatible S3 storage holds large scan artifacts, screenshots, datasets, generated sites, validation reports, and model artifacts.
- Redis provides bounded caches, distributed locks, rate-limit state, and ephemeral event streams; it is not authoritative storage.
- Qdrant stores embeddings plus tenant, dataset, provenance, licensing, and model-version filters; it is not authoritative application storage.

Temporal histories reference records and object keys and do not carry large artifacts.

## Consequences

- Each data class has storage suited to its access and durability requirements.
- Cross-store operations require durable reconciliation and idempotent updates rather than distributed transactions.
- Retention, backup, tenant isolation, and removal workflows must cover every derived store.
- Object and vector metadata must remain traceable to PostgreSQL records.
