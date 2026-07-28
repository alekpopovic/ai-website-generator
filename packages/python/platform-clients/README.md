# Platform Clients

Typed adapters for PostgreSQL-backed repositories, Redis, Temporal, S3-compatible storage, Qdrant,
and private Ollama access. Adapters centralize timeouts, retries, telemetry, tenant scoping, and test
fakes without leaking vendor clients into domain code.

The implemented `object_storage` package provides asynchronous MinIO/AWS S3 access, immutable
checksum-verified streaming and multipart uploads, streaming downloads, typed keys, metadata and
retention contracts, controlled presigning, deterministic gzip helpers, and an in-memory fake.

The `llm` package defines provider-neutral chat, Pydantic-structured generation, vision,
embedding, model catalog, capability, readiness, and warm-up contracts. Its Ollama adapter applies
prompt redaction, strict byte limits, bounded concurrency and timeouts, selective retries, circuit
breaking, response validation, and safe inference metadata. `FakeLLMGateway` keeps default CI
deterministic and offline.

The `vector_store` package exposes versioned collection lifecycle, named dense-vector upserts,
typed payload filters, source-diverse retrieval, health/readiness, and collection statistics. Its
Qdrant adapter uses an atomic stable alias over embedding-provider/model/digest/schema-specific
physical collections. The in-memory implementation provides equivalent deterministic behavior for
unit tests. Only bounded abstract design-pattern text and allowlisted provenance metadata can enter
this boundary.

The `network_safety` package provides the shared fail-closed URL, DNS, redirect, connection, peer,
response-size, HTML content-type, timeout, and blocked-request audit policy used by Scrapy,
Playwright, asset inspection, and publishing integrations. It includes an offline sequence resolver
and recording auditor for deterministic security tests.

The `page_classification` package defines the replaceable classifier protocol, versioned feature and
result contracts, and the deterministic template-diverse representative selector shared by workers
and the control-plane override path. Provider-specific HTML feature extraction remains in the crawler
worker.
