# Local Development

## Prerequisites

Install these tools before bootstrapping the repository:

- Git;
- Python 3.12, 3.13, or 3.14;
- uv 0.11.28 or a compatible newer patch release;
- Node.js 22.22.3+, 24.15+, or 26.x;
- pnpm 11.17.0, normally activated from the root `packageManager` declaration;
- Task 3.51.1;
- Docker with Docker Compose v2-compatible commands for the local service stack.

The JavaScript toolchain deliberately uses TypeScript 6.0.x because Angular 22 supports TypeScript from 6.0.0 up to, but not including, 6.1.0. Do not upgrade to TypeScript 7 until Angular and the lint toolchain support it together.

Infrastructure-specific start, stop, profile, port, reset, and inspection procedures are documented in [Local development stack](../operations/local-development-stack.md).

## Initial setup

Copy `.env.example` to `.env`, then provide local values for the blank credential fields. The committed example files contain no secrets. Never put server credentials in `apps/web/.env` because Angular-bundled values are public.

Install the exact dependency graph and local Git hooks:

```text
task bootstrap
```

`bootstrap` synchronizes the uv workspace from `uv.lock`, installs the pnpm workspace from `pnpm-lock.yaml`, and installs pre-commit and commit-message hooks. It requires package-registry access on the first run. Committed lockfiles make later installs reproducible.

Confirm the development toolchain:

```text
task verify
```

Verification formats nothing and requires no running containers, internet access, GPU, or real Ollama model. It succeeds while application workspaces contain no tests and begins running each test category automatically as test files are added. Dependencies must already be installed or available in the local package caches.

## CPU-only development

CPU-only is the default development mode. Formatting, linting, type checking, deterministic unit tests, fake model responses, synthetic crawl fixtures, static rendering tests, and most control-plane work require no GPU or real Ollama instance. Default CI follows the same constraint.

When inference behavior must be exercised locally, use a small explicitly selected model and keep Ollama on the private container network. Never expose its port on a public interface. Prefer the deterministic fixtures in `tests/fixtures/ollama` for routine development and tests.

## Optional NVIDIA GPU support

GPU inference and training are optional and separate from the default workflow. A compatible NVIDIA driver, `nvidia-smi`, NVIDIA Container Toolkit, and a Docker runtime configured for GPU access are required. Verify GPU access with a vendor-provided diagnostic container before enabling a future GPU-specific Compose profile.

GPU-enabled services must retain the same private network boundaries as CPU services. Do not add public Ollama ingress. Training workers need separate resource limits and queues and must not share FastAPI request processes. Do not enable optional training merely to run tests or normal site generation.

## Root commands

| Command                       | Purpose                                                                                  |
| ----------------------------- | ---------------------------------------------------------------------------------------- |
| `task bootstrap`              | Install locked uv and pnpm dependencies and Git hooks.                                   |
| `task format`                 | Apply Ruff and Prettier formatting.                                                      |
| `task lint`                   | Run Ruff, ESLint, Prettier checks, and offline secret scanning.                          |
| `task typecheck`              | Run strict mypy and implemented workspace TypeScript checks.                             |
| `task unit-test`              | Run deterministic Python and web unit tests.                                             |
| `task integration-test`       | Run integration tests against explicitly started local services.                         |
| `task e2e-test`               | Run bounded end-to-end tests.                                                            |
| `task generate-api-client`    | Generate the web API client after that workspace is implemented.                         |
| `task compose-up`             | Start the Compose dependency stack with CPU-only Ollama.                                 |
| `task compose-up-gpu`         | Start the stack with the optional NVIDIA Ollama profile.                                 |
| `task compose-down`           | Stop the local Compose stack without deleting persisted data.                            |
| `task compose-logs`           | Follow local Compose logs.                                                               |
| `task ollama-pull`            | Explicitly pull configured Ollama models; may download many gigabytes.                   |
| `task ollama-ready`           | Verify Ollama availability and configured model presence.                                |
| `task workflow-worker`        | Run Temporal workflow orchestration on the `control` queue.                              |
| `task storage-test-artifacts` | Inspect explicitly tagged development test objects.                                      |
| `task clean`                  | Remove allowlisted local caches, dependencies, and generated outputs.                    |
| `task audit`                  | Query vulnerability services for synchronized Python and locked JavaScript dependencies. |
| `task licenses`               | Print Python and JavaScript dependency license reports.                                  |
| `task verify`                 | Run offline lint, formatting checks, type checks, and unit tests.                        |

Audit commands intentionally run separately from `verify` because current vulnerability data requires network access. Review audit findings and license reports; never apply automated dependency fixes without inspecting the resulting manifests and lockfiles.

## Commit validation and secrets

The commit-message hook validates Conventional Commits but never creates a commit. Examples include `feat(api): add project endpoint` and `docs: clarify local setup`.

The pre-commit hook formats and lints staged source files and compares potential secrets with `.secrets.baseline`. A baseline entry is not permission to commit a credential. Investigate every finding, rotate any exposed credential, and use an inline allowlist only for a reviewed false positive.
