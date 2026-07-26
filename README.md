# AI Website Generator

Monorepo for a production-grade platform that discovers website design patterns and generates secure static sites from validated specifications.

## Repository map

- `apps/`: user-facing Angular application and FastAPI control plane.
- `services/`: Temporal workflow and specialized activity workers.
- `packages/`: shared Python, TypeScript, and deterministic site-component packages.
- `infrastructure/`: local containers, deployment manifests, and operational scripts.
- `docs/`: architecture, decisions, operations, development, API, and security documentation.
- `tests/`: deterministic shared fixtures and cross-service test suites.

See `AGENTS.md` for permanent engineering constraints and `docs/architecture/system-architecture.md` for system boundaries and data flows.
