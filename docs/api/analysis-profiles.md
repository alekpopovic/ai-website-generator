# Analysis Profile Persistence and Review

Normalized analysis is stored as history, not as a mutable replacement for scan data. The API accepts only the versioned `platform-schemas` contracts at the worker persistence boundary. It does not accept raw prompts, screenshots, HTML, page copy, source names, or arbitrary model JSON.

## Records and ownership

- `analysis_runs` is append-only. A caller-provided run UUID is the idempotency boundary and records prompt, analyzer, model digest, latency, strategy, attempts, schema version, result hash, and provenance state.
- `page_profiles` keeps every normalized `PageProfile`. A PostgreSQL partial unique index permits exactly one `is_current = true` row per source page.
- `website_profiles` keeps every aggregate `WebsiteProfile` and applies the equivalent current-row rule per source website.
- `section_patterns` stores every page section independently with searchable type, layout, category, language, style tags, confidence, approval, provenance, analyzer, schema, and model fields.

All read and curation queries join through the owning project. Unknown and foreign-owned IDs both return `404`.

## Retrieval safety and duplicates

The section retrieval document is deterministically assembled from controlled schema values: section type, abstract copy purpose, layout, registered component names, responsive behavior, category, language, and controlled style tags. Source URLs, names, extracted sentences, font names, assets, HTML, and executable content cannot enter this document.

`section-pattern-v1` hashes the same controlled structure, excluding source identity and section order. A matching hash on another page from the same source website links through `duplicate_of_id`; source records are never deleted or collapsed.

## Review API

All paths are under `/api/v1/projects/{project_id}/analysis`:

| Method  | Path                                      | Purpose                                                                  |
| ------- | ----------------------------------------- | ------------------------------------------------------------------------ |
| `GET`   | `/page-profiles`                          | List current or historical page profiles                                 |
| `GET`   | `/page-profiles/{profile_id}`             | Inspect one page profile                                                 |
| `PATCH` | `/page-profiles/{profile_id}/curation`    | Approve, reject, or mark for review                                      |
| `GET`   | `/website-profiles`                       | List current or historical website profiles                              |
| `GET`   | `/website-profiles/{profile_id}`          | Inspect one website profile                                              |
| `PATCH` | `/website-profiles/{profile_id}/curation` | Curate one website profile                                               |
| `GET`   | `/section-patterns`                       | Filter and inspect independent sections                                  |
| `GET`   | `/section-patterns/facets`                | Server-side counts for curation filters and charts                       |
| `GET`   | `/section-patterns/{pattern_id}`          | Inspect one section and duplicate lineage                                |
| `GET`   | `/section-patterns/{pattern_id}/detail`   | Inspect safe source, analysis, token, screenshot, and embedding metadata |
| `PATCH` | `/section-patterns/{pattern_id}/curation` | Curate one section pattern                                               |
| `PATCH` | `/section-patterns/bulk-curation`         | Version-check and curate up to 100 patterns atomically                   |

The section-pattern collection supports domain, category, page type, section type, layout,
language, confidence range, approval, and provenance filters. Facet counts are computed in
PostgreSQL and returned as bounded aggregates, so distribution charts do not download the complete
pattern collection.

The detail response contains only normalized `SectionPattern` structures, controlled design tokens,
source metadata, analysis metadata, embedding state, and an identifier for an authorized safe
screenshot. Raw or rendered scanned HTML, object-storage keys, and private storage URLs are never
returned. Screenshot bytes continue to use the existing owner-authorized, provenance-gated endpoint.
| `GET` | `/runs` | Inspect historical analyzer run metadata |

Curation uses optimistic versions and records the actor, timestamp, optional bounded note, and an audit event. Audit details include only the old and new state, never profile JSON or source content.

The project **Analysis** tab uses the generated TypeScript client. It renders typed values as text and has no scanned-HTML rendering path.

## Embedding indexing progress

`POST /embedding-runs` queues an incremental index or full reindex Temporal workflow and returns `202`; FastAPI performs no embedding or Qdrant mutation. `GET /embedding-runs`, `GET /embedding-runs/{run_id}`, and `GET /embedding-runs/{run_id}/failures` expose owner-scoped counts, collection/model identity, alias-switch time, and sanitized failures. An idempotency key prevents duplicate logical runs, and alias promotion is accepted only for a full reindex.
