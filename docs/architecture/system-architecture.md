# System Architecture

## 1. System context

The platform turns authorized source observations and user requirements into deterministic static websites. Users operate the Angular application, which calls only the FastAPI control plane. FastAPI persists application state and starts or signals Temporal workflows. Specialized workers perform all expensive or untrusted processing and exchange large artifacts through MinIO or another S3-compatible store.

```text
User -> Angular -> FastAPI -> PostgreSQL
                         |-> Redis
                         `-> Temporal -> specialized workers
                                          |-> MinIO
                                          |-> Qdrant
                                          `-> private Ollama
```

PostgreSQL, Redis, Temporal, MinIO, Qdrant, and Ollama are internal services. Generated static sites are artifacts, not executable input to the control plane.

## 2. Control plane versus worker responsibilities

The FastAPI control plane owns authentication, authorization, request validation, application metadata, policy decisions, idempotent command submission, workflow start and signal operations, job queries, and signed or proxied artifact access. Request handlers remain bounded and do not perform crawl, browser, inference, embedding, rendering, validation, repair, or training work.

Temporal workflows own durable orchestration, retries, timeouts, cancellation, and recovery. Activity workers own resource-intensive execution:

- crawler worker: policy evaluation, discovery, and HTTP collection;
- browser worker: isolated rendering and screenshots;
- AI worker: structured inference and DSPy programs;
- embedding worker: embedding creation and Qdrant updates;
- generation worker: deterministic `SiteSpec` rendering;
- validation worker: static and browser-based checks and repair findings;
- training worker: optional offline dataset preparation, tuning, and evaluation.

Workflow histories carry IDs, compact state, and object keys. Large documents, screenshots, model outputs, and binaries remain in object storage.

Shared queue names, retry categories, workflow IDs, heartbeat and cancellation helpers, dispatch
boundaries, and deterministic test utilities are defined in `platform-workflows`. The control plane
uses a lazy Temporal client and a fake dispatcher in default unit tests. See
[Temporal workers](../development/temporal-workers.md) for local process and test commands.

## 3. Scan workflow

1. An authorized user submits a source, scope, and authorization attestation.
2. FastAPI validates the request, records policy and provenance metadata, and starts a Temporal scan workflow.
3. The crawler worker resolves and validates every URL, enforces `robots.txt`, licensing policy, rate and size limits, and performs bounded discovery.
4. Raw responses and manifests are written to object storage; relational state stores their identifiers and checksums.
5. Approved pages are passed by ID to the browser worker for isolated rendering with outbound-network interception and SSRF checks.
6. The AI worker converts stored observations into validated `WebsiteProfile` records containing abstract tokens, layout metadata, and component patterns.
7. The embedding worker embeds approved abstract records and writes tenant- and provenance-scoped vectors to Qdrant.
8. Temporal records terminal state, partial failures, and cancellation; FastAPI exposes progress and safe artifact references.

The scan never promotes third-party logos, names, copy, media, code, or complete compositions into reusable generation inputs.

## 4. Dataset workflow

Dataset creation selects eligible abstract scan records by ID and evaluates authorization, provenance, licensing, removal state, schema version, and quality policy. Workers normalize and deduplicate records, create immutable versioned manifests, and split data deterministically. Dataset bodies live in object storage; PostgreSQL holds lifecycle state, ownership, policy, lineage, checksums, and object keys. Optional embeddings live in Qdrant with the same dataset and provenance identifiers.

Every dataset version is reproducible from its manifest. Removal requests mark affected sources in PostgreSQL and trigger workflows that exclude or rebuild derived datasets and delete applicable vector entries and artifacts according to retention policy.

## 5. Generation workflow

1. FastAPI validates the project request and starts a generation workflow.
2. Retrieval selects only tenant-authorized abstract patterns from Qdrant; source licensing and provenance filters are applied before results are returned.
3. DSPy programs and private Ollama inference produce validated `WebsiteProfile`, `PageSpec`, and `SiteSpec` structures.
4. Schema and policy gates reject unknown components, unsafe URLs, arbitrary code, unsupported properties, and unbounded content.
5. The generation worker resolves only versioned registered components and renders them deterministically through Jinja2.
6. Generated files, manifests, component versions, inputs, checksums, and model/program versions are written to object storage.
7. The validation workflow must pass before an artifact can be marked publishable.

Model output is data. It is never evaluated as HTML templates, JavaScript, Python, SQL, shell input, or a URL to fetch.

## 6. Validation and repair workflow

Validation runs in an isolated worker against an immutable generation artifact. It performs schema and manifest validation, allowlist checks, static security analysis, link and asset policy checks, accessibility tests, deterministic build checks, and bounded Playwright rendering. Results are stored as structured findings.

Repair receives findings and the current `SiteSpec`, not executable output. The AI worker may propose a new validated spec using registered components and bounded fields. Generation then produces a new immutable artifact, followed by the complete validation suite. Temporal limits repair attempts, retains each version, supports cancellation, and prevents partial artifacts from replacing the last valid result.

## 7. Optional training workflow

Fine-tuning is disabled by default and is not required for CI or normal generation. An explicitly authorized workflow freezes a licensed, provenance-complete dataset version; creates deterministic splits; establishes an evaluation baseline; and runs TRL and PEFT with optional QLoRA in a separately resourced training worker. Checkpoints, adapter weights, configuration, metrics, dataset lineage, and environment metadata are stored as versioned artifacts.

A trained model is promoted only after reproducible evaluation, security review, and rollback metadata are recorded. RAG quality and DSPy prompt/program optimization are exhausted before fine-tuning is considered.

## 8. Storage responsibilities

| Store      | Authoritative responsibilities                                                                                         | Must not contain                                                    |
| ---------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| PostgreSQL | tenants, users, projects, authorization, job state, artifact metadata, provenance, policy, lineage, and audit records  | large binaries or workflow payloads                                 |
| MinIO/S3   | raw bounded scan artifacts, screenshots, normalized datasets, generated sites, validation reports, and model artifacts | authoritative authorization or lifecycle state                      |
| Redis      | bounded caches, distributed coordination locks, rate-limit state, and ephemeral event streams                          | durable workflow state or sole copies of business records           |
| Temporal   | workflow histories, activity coordination, retries, timers, cancellation, and compact identifiers                      | large HTML, screenshots, model bodies, or binary artifacts          |
| Qdrant     | embeddings and retrieval metadata scoped by tenant, dataset, provenance, licensing, and model version                  | source-of-truth application state or unfiltered raw scraped content |

Object access uses typed keys and private buckets through the asynchronous `platform-clients`
abstraction. Immutable uploads and downloads are SHA-256 verified, large streams use multipart
checksums, and retention intent is mirrored as metadata while PostgreSQL remains authoritative.
Presigned writes are restricted to control-plane-approved user assets; there is no general browser
object-storage client.

## 9. Trust boundaries

The primary boundaries are: public browser to Angular; Angular to authenticated FastAPI; FastAPI to internal infrastructure; workers to untrusted external websites; workers to private inference; and generated artifacts to preview or publication environments. Authentication does not replace tenant authorization. IDs, workflow signals, object keys, model output, scraped content, uploaded files, webhook bodies, and external URLs are untrusted until validated for their specific boundary.

Crawler and browser workers operate as hostile-content processors with restricted identities, filesystems, resources, and egress. Training workloads are isolated from serving workloads. Preview and generated-site execution are isolated from control-plane credentials and origins.

## 10. Network boundaries

Only the web application and the intended FastAPI ingress may be publicly reachable. Angular reaches internal capabilities exclusively through FastAPI. PostgreSQL, Redis, Temporal, MinIO, Qdrant, and Ollama use private networks and authenticated service identities; Ollama has no public ingress.

Crawler and browser egress passes through URL policy enforcement. Every initial URL, redirect, asset, browser request, and webhook target is re-resolved and checked against allowed schemes, ports, DNS results, IP ranges, redirect limits, and destination policy. Loopback, link-local, private, multicast, metadata-service, and otherwise reserved destinations are denied unless an explicit narrowly scoped internal policy applies. DNS rebinding protections validate at connection time.

## 11. Data provenance

Every scan and derivative record carries tenant and source identifiers, authorization attestation, canonical URL, timestamps, fetch policy result, content checksum, licensing metadata, tool and schema versions, and parent artifact references. Derived profiles, vectors, datasets, `SiteSpec` versions, generated artifacts, and model artifacts retain transitive lineage through immutable manifests.

Provenance gates control retrieval, dataset eligibility, retention, publication, and removal. Audit records distinguish user decisions from automated transformations. Removal and licensing changes propagate through durable workflows to affected derived data according to policy.

## 12. Generated-site security model

Generated sites are assembled only from a versioned component registry, escaped Jinja2 templates, validated design tokens, and controlled JavaScript authored and reviewed in this repository. `SiteSpec` fields use strict schemas, bounded values, URL policies, and explicit component discriminators; unknown fields and components are rejected.

The renderer never evaluates model-authored templates or code and never fetches model-provided URLs. Output validation enforces a restrictive content security policy, safe link behavior, asset allowlists, integrity and size limits, and the absence of inline or unknown scripts. Previewing occurs on an isolated origin without platform cookies, credentials, internal network access, or privileged APIs. Publication uses immutable validated artifacts and preserves the manifest needed for audit and rollback.
