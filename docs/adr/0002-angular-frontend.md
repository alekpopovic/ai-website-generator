# ADR 0002: Angular as the Frontend

- Status: Accepted
- Date: 2026-07-27

## Context

The product needs a maintainable application for multi-step project configuration, job monitoring, dataset review, structured site editing, and previews.

## Decision

Use Angular with strict TypeScript and a contract-checked FastAPI client. Angular communicates only with the FastAPI control plane. It does not connect to Ollama, Qdrant, MinIO, Temporal, Redis, or PostgreSQL. Generated-site previews run on an isolated origin without application credentials.

## Consequences

- A single API boundary centralizes authentication, authorization, and compatibility.
- Strict editor models can mirror the approved `SiteSpec` schema.
- API client generation and frontend/backend contract checks become required build steps.
- Preview hosting requires explicit cross-origin and content-security policies.
