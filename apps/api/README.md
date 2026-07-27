# Control-Plane API

FastAPI application responsible for authenticated commands and queries, resource lifecycle management, authorization, validation, and starting or signalling Temporal workflows. It returns job state and artifact references; it never runs crawl, browser, AI, embedding, generation, validation, or training workloads in request processes.

The application provides the control-plane and shared persistence foundations: a factory and
lifespan, typed settings, transaction-scoped SQLAlchemy async sessions, reviewed Alembic migrations,
JSON logging, OpenTelemetry-compatible spans, secure middleware, problem responses, health
diagnostics, pagination contracts, and `/api/v1/version`. Authentication and domain routes remain
intentionally deferred.

See [API development](../../docs/development/api-development.md) for setup and commands.
