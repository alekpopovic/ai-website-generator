# Web Application

Standalone Angular application for project setup, authorized scan requests, dataset curation,
generation controls, job monitoring, previews, and review. It communicates only with the
FastAPI control plane and never directly with databases, workflow infrastructure, object storage,
vector storage, Redis, or model providers.

## Commands

Run these from the repository root:

```text
pnpm --filter @platform/web start
pnpm --filter @platform/web build
pnpm --filter @platform/web unit-test
pnpm --filter @platform/web e2e-test
```

The browser loads `public/config/runtime-config.json` before application bootstrap. Replace that
file when deploying an already-built image; never put secrets in it because it is public.
