# ADR 0001: FastAPI as the Control-Plane API

- Status: Accepted
- Date: 2026-07-27

## Context

The platform needs a typed HTTP API for Angular, authentication and authorization, lifecycle operations, workflow submission, and job queries. Expensive work has different scaling, retry, and isolation needs from request handling.

## Decision

Use FastAPI as the control-plane API. Define strict Pydantic request and response contracts and generate an OpenAPI-based TypeScript client. FastAPI owns bounded validation, policy checks, persistence, and Temporal commands and queries. It never runs crawl, browser, AI, embedding, rendering, validation, or training jobs in request processes.

## Consequences

- API latency and availability are isolated from long-running workloads.
- Python contracts can be shared with workers while service boundaries remain explicit.
- Background operations require asynchronous job resources and status APIs.
- Authorization and idempotency must be enforced before workflow submission.
