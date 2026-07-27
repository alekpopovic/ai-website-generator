# API Client Generation

The FastAPI application is the only source of HTTP request and response contracts. Angular and
TypeScript packages must import generated types from `@platform/api-client`; they must not recreate
Pydantic request, response, pagination, or problem-detail interfaces by hand.

## Propagating an API contract change

1. Change the FastAPI route and Pydantic models, including a stable `operation_id` and explicit
   response models.
2. Run `task generate-api-client` from the repository root.
3. Review both `packages/web/api-client/openapi.json` and `src/generated/`. Generated files are
   committed but never edited manually.
4. Update authored client adapters or Angular consumers only when behavior, rather than the schema,
   changed.
5. Run `task verify`.

`infrastructure/scripts/export_openapi.py` creates the deterministic fake-mode FastAPI application
and calls `app.openapi()` directly. It neither starts Uvicorn nor performs dependency I/O. Canonical
sorted JSON makes the schema diff reproducible.

Hey API consumes that local JSON and emits an Angular `HttpClient` SDK. Its version is pinned in the
workspace lockfile. `task verify-generated-api-client` independently exports the schema and
regenerates the SDK in a temporary directory. Any byte-level difference fails verification, and the
root `task verify` includes this check for CI.

## Auth and transport behavior

`providePlatformApi()` installs the generated Angular client. After public runtime configuration is
loaded, `PlatformApiConfiguration.configure()` supplies the API base URL and credential policy.
The authored transport layer provides:

- in-memory bearer access-token storage and an API-origin-scoped bearer interceptor;
- a refresh strategy injection token that coalesces concurrent refresh attempts;
- an opt-out context token for the eventual refresh request itself;
- API-origin-scoped request IDs;
- a mapper for the generated RFC 7807 `ProblemDetail` type;
- safe API-relative SSE URL construction, while generated clients also expose SSE support;
- generated `PaginationParams` and `PaginationMeta` primitives.

Refresh tokens should be carried by secure, HTTP-only cookies. A future authentication prompt will
implement the FastAPI refresh endpoint and an `ApiRefreshStrategy` using its generated operation;
the client package deliberately defines no handwritten refresh DTO.

## UI-only fakes

Production application configuration has no fake API switch. UI unit tests may explicitly import
`@platform/api-client/testing` and call `provideFakePlatformApiForTesting()` with fixtures checked
against generated types. Playwright tests intercept requests locally with the same generated types.
Neither mechanism is reachable from a production runtime configuration file.
