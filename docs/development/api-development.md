# API Development

## Scope and boundaries

`apps/api` is the FastAPI control plane. Request handlers validate commands, persist application metadata, and interact with Temporal using compact identifiers. They must never perform crawling, browser rendering, inference, embedding, site rendering, validation, repair, or training. Those operations belong in Temporal workers.

The application is packaged from `apps/api/src/platform_api`. `platform_api.application:create_app` is the composition root, while `platform_api.main:app` is the ASGI import target. Tests use `platform_api.testing:create_test_app`, which forces fake dependencies and accepts standard FastAPI dependency overrides.

## Configuration

Copy `apps/api/.env.example` to `apps/api/.env`, then supply local secrets. Settings are immutable and grouped into application, database, Redis, Temporal, MinIO, Qdrant, Ollama, security, email, scanning, and generation sections. Each group has its own environment prefix.

Required local credentials remain blank in the committed example. At minimum, configure `DATABASE_URL` with the `postgresql+asyncpg://` scheme and `REDIS_URL` with the Compose password before using real dependencies. `APP_FAKE_DEPENDENCIES=true` is intended only for deterministic development and CI checks; it makes dependency probes healthy without connecting to services.

Authentication requires `SECURITY_ACCESS_TOKEN_SECRET` with at least 32 bytes of entropy. Production defaults disable interactive API documentation, require HTTPS redirection, reject wildcard Host policies, allow no CORS origin, require secure refresh cookies, cap request bodies, and emit defensive headers. The development example explicitly relaxes HTTPS and enables documentation for loopback use. Configure `APP_CORS_ALLOWED_ORIGINS` as a JSON array of complete trusted origins; wildcard origins are not accepted.

## Run locally

Install the locked workspace and start the dependency stack:

```console
task bootstrap
task compose-up
```

Run migrations, then start the API:

```console
uv run alembic -c apps/api/alembic.ini upgrade head
uv run uvicorn platform_api.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000
```

With development documentation enabled, OpenAPI JSON is at <http://127.0.0.1:8000/openapi.json> and Swagger UI is at <http://127.0.0.1:8000/docs>.

## Database migrations

Every schema change requires an Alembic revision. Import new SQLAlchemy models into the metadata path before generating a revision, inspect generated operations, and test upgrade and downgrade against disposable local data:

```console
uv run alembic -c apps/api/alembic.ini revision --autogenerate -m "describe change"
uv run alembic -c apps/api/alembic.ini upgrade head
uv run alembic -c apps/api/alembic.ini downgrade -1
```

Never run migrations automatically inside request handling. Deployment orchestration applies reviewed migrations as a separate operation.

The shared persistence layer uses request-scoped async sessions with one explicit transaction.
Repositories and services stage or flush changes but never commit. UUID primary keys, UTC-aware
timestamps, named constraints, string status fields, safe JSONB values, and optimistic versions for
editable records are defined under `platform_api.persistence`.

To create the single local developer identity after migrations, run the explicit idempotent seed:

```console
task seed-local-user
```

The command is rejected outside `APP_ENV=development` and accepts only `@localhost` or
`@local.test` email addresses. It creates no sample projects, jobs, tokens, or product data. The
seed remains intentionally non-login-capable; use registration and the Mailpit verification
message when testing authentication locally.

## First-party authentication

Authentication routes live under `/api/v1/auth`. Password hashing uses Argon2id outside the async
event-loop thread. Access tokens are short-lived signed bearer JWTs; opaque refresh tokens rotate
through an HttpOnly cookie and are stored only as SHA-256 hashes. Redis enforces a bounded login
rate window. Registration verification and password recovery send one-time links through the SMTP
settings; local Compose routes these messages to Mailpit at <http://127.0.0.1:8025>.

The database transaction dependency normally rolls back error responses. A refresh-token reuse
exception is deliberately committed after the entire family is revoked and the audit event is
staged, then returned as `401`. This narrow boundary prevents a rejected replay from undoing its
security response.

PostgreSQL integration tests require an explicitly disposable database whose name ends in `_test`:

```console
INTEGRATION_DATABASE_URL=postgresql+asyncpg://127.0.0.1/ai_website_generator_test \
INTEGRATION_DATABASE_RESET_ALLOWED=true task integration-test
```

The integration fixture upgrades and downgrades the Alembic graph in that database. Never point it
at a development, staging, or production database.

## Request and error contracts

All domain routes belong below `/api/v1` and use Pydantic request and response models with forbidden unknown fields where appropriate. Dependencies are regular functions in `platform_api.dependencies`, making infrastructure replacement explicit and testable.

The request-context middleware accepts a bounded safe `X-Request-ID` or creates a UUID, binds it to JSON logs and OpenTelemetry spans, and returns it in the response. Framework, validation, database, expected application, and unexpected exceptions map centrally to RFC-style `application/problem+json` responses. Logs retain internal exception information; responses do not.

OpenTelemetry exporters are deliberately not configured inside the package. The telemetry boundary uses the global API provider, allowing deployment to install an SDK, resource attributes, sampler, processor, and exporter without coupling unit tests or default CI to a collector.

## Health semantics

- `/health/live` performs no dependency I/O and answers whether the process serves HTTP.
- `/health/ready` checks critical dependencies: PostgreSQL, Redis, Temporal, and MinIO.
- `/health/dependencies` also checks Qdrant and Ollama. Worker-facing failures degrade the report without making the control plane unready.

Checks are concurrent, bounded by per-service timeouts, redact credentials and exception messages, disable HTTP redirects, and never download models or execute work. Fake mode replaces all checks with deterministic in-process probes.

## Tests and verification

Run API unit tests alone with:

```console
uv run pytest apps/api/tests
```

The root `task verify` runs formatting checks, linting, strict mypy, and deterministic unit tests without internet, containers, GPUs, or real models. Integration tests that need Compose must be explicitly categorized and run separately.
