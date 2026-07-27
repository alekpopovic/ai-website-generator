# Web Application Development

## Architecture boundary

`apps/web` is a standalone, zoneless Angular 22 application. It calls only the FastAPI control
plane. Browser code must never connect directly to PostgreSQL, Redis, Temporal, MinIO, Qdrant, or
Ollama.

First-party authentication uses the generated API client. The access token is held only in an
Angular signal-backed in-memory store; it is never written to local or session storage. The
HttpOnly refresh cookie is browser-managed. Protected requests make one coordinated refresh and
one retry after `401`; auth endpoints are excluded to prevent recursion. Route guards initialize
the session before allowing protected features. Typed problem details supply form-level and
field-level validation messages.

The generated client workflow and contract propagation rules are documented in
[API client generation](api-client-generation.md).

Signals hold synchronous view state, such as responsive navigation and notifications. RxJS is used
for asynchronous event streams and HTTP boundaries. Feature routes use lazy component loading.

## Start and build

After `task bootstrap`, run:

```text
pnpm --filter @platform/web start
pnpm --filter @platform/web build
pnpm --filter @platform/web build:development
```

The development server listens on `http://127.0.0.1:4200`. Production and development builds use
separate Angular configurations.

## Public runtime configuration

Angular loads `/config/runtime-config.json` with `no-store` caching before bootstrap. A deployment
can replace this file in an already-built image without recompiling JavaScript. The schema is:

```json
{
  "apiBaseUrl": "https://api.example.test",
  "previewBaseUrl": "https://preview.example.test",
  "supportUrl": null
}
```

Only HTTP and HTTPS URLs are accepted. All runtime values are visible to browser users; secrets,
internal service endpoints, and credentials must never be written to this file. `.env.example`
documents variables that a later container entrypoint may use to render the public JSON file.

## Quality checks

```text
pnpm --filter @platform/web typecheck
pnpm --filter @platform/web unit-test
pnpm --filter @platform/web e2e-test
```

Unit tests use Vitest through Angular's supported test builder. Playwright runs desktop and mobile
Chromium projects; install its browser binary explicitly before the first local E2E run with
`pnpm --filter @platform/web exec playwright install chromium`. Default CI verification does not
download or require a browser.

Accessibility foundations include semantic landmarks and navigation, a keyboard skip link, visible
focus states, labelled forms, live-announced notifications, reduced-motion support, and responsive
navigation. Preserve these behaviors when adding feature implementations.
