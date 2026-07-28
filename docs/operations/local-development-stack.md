# Local Development Stack

The root `compose.yaml` runs infrastructure dependencies by default. The browser worker is an opt-in
`workers` profile and publishes no port. All published ports bind to `127.0.0.1` by default; changing
`DEV_BIND_ADDRESS` expands the trust boundary and requires a deliberate security review.

## Services and published ports

| Service         | Local endpoint           | Purpose                                                                      |
| --------------- | ------------------------ | ---------------------------------------------------------------------------- |
| PostgreSQL      | `127.0.0.1:5432`         | Application data and separate `temporal` and `temporal_visibility` databases |
| Temporal        | `127.0.0.1:7233`         | gRPC endpoint for local control-plane and worker processes                   |
| Temporal UI     | <http://127.0.0.1:8233>  | Workflow inspection                                                          |
| Redis           | `127.0.0.1:6379`         | Cache, locks, and event streams                                              |
| MinIO API       | <http://127.0.0.1:9000>  | S3-compatible endpoint for local processes                                   |
| MinIO Console   | <http://127.0.0.1:9001>  | Object-storage inspection                                                    |
| Qdrant HTTP     | <http://127.0.0.1:6333>  | Vector-store API; gRPC is not published                                      |
| Ollama          | <http://127.0.0.1:11434> | Local model API, enabled by exactly one profile                              |
| Mailpit SMTP    | `127.0.0.1:1025`         | Captures authentication email                                                |
| Mailpit UI      | <http://127.0.0.1:8025>  | Inspects captured email                                                      |
| Fixture website | <http://127.0.0.1:8088>  | Synthetic crawler and browser target                                         |

No service is bound to a non-loopback interface by default. Data services still require credentials where supported because loopback binding is not an authorization mechanism.

## Network boundaries

The `frontend-api` and `backend` networks are Docker-internal networks with no direct external route. Databases and infrastructure APIs attach only to `backend`. Developer-facing UIs and the mail service bridge `frontend-api` to the minimum backend dependency they need.

The fixture website attaches to `scanner-egress`, a distinct network intended for future crawler and browser workers. It has no route to backend data services. The network permits outbound traffic because production-like scanner egress policy requires host-level controls that vary by operating system; future scanner containers must also implement URL validation and SSRF protection.

The optional browser worker joins `backend` for PostgreSQL, Temporal, and MinIO and `scanner-egress`
for hostile-site access. Application URL interception is mandatory but insufficient on its own;
production must enforce default-deny egress so a browser exploit cannot reach backend services or
private networks.

Ollama attaches to `backend` and a separate `model-egress` network so an explicit model pull can reach the registry. It is never attached to `frontend-api`. Angular must use FastAPI rather than a Compose dependency directly.

## First start

1. Copy `.env.example` to `.env`.
2. Supply unique local values for `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, and `QDRANT_API_KEY`. Do not commit `.env`.
3. Ensure enough disk is available for named volumes. Models are not downloaded at startup.
4. Start the CPU-safe profile with `task compose-up`, equivalent to `docker compose --profile cpu up --detach`.
5. Inspect state with `docker compose --profile cpu ps` and `docker compose logs --tail 100 postgres temporal minio-init`.

The MinIO initialization job creates `scan-artifacts`, `datasets`, `generated-sites`, `model-artifacts`, and `user-assets`. It uses `mc mb --ignore-existing`, so reconciliation is idempotent. Rerun it with `docker compose run --rm minio-init`.

## CPU and NVIDIA GPU profiles

`cpu` runs Ollama without accelerator devices. Its default CPU and memory ceilings keep an idle local stack bounded; tune `OLLAMA_CPU_LIMIT` and `OLLAMA_MEMORY_LIMIT` for the workstation. The default 30B generation model may need substantially more memory than the default ceiling. Pull or run it only on suitable hardware, or explicitly configure a smaller development model.

For NVIDIA GPU use, install a compatible NVIDIA driver and NVIDIA Container Toolkit, then run `task compose-up-gpu`, equivalent to `docker compose --profile gpu up --detach`. Never enable both profiles simultaneously because both intentionally claim the same loopback Ollama port and persistent model volume.

## Explicit model downloads

Compose starts an empty Ollama server and never pulls a model. The configured defaults are:

- Vision: `qwen3-vl:8b`
- Generation: `qwen3-coder:30b`
- Embedding: `qwen3-embedding:0.6b`

The generation model is a particularly large download. Pull one role at a time when appropriate:

```console
uv run python infrastructure/scripts/pull_ollama_models.py --only embedding
uv run python infrastructure/scripts/pull_ollama_models.py --only vision
uv run python infrastructure/scripts/pull_ollama_models.py --only generation
```

`task ollama-pull` intentionally pulls all configured models. Override defaults in `.env` or with the corresponding command-line option. The scripts allow only loopback Ollama URLs and constrained model names.

Check server and model readiness with `task ollama-ready`. To check only the server, run `uv run python infrastructure/scripts/check_ollama_readiness.py --server-only`.

## Stop, restart, and inspect

`task compose-down` stops containers while retaining named volumes. Start again with `task compose-up` or `task compose-up-gpu`. Follow all logs with `task compose-logs`, or use `docker compose logs --follow SERVICE`.

Useful non-destructive inspection commands are:

```console
docker compose --profile cpu ps
docker compose config --services
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -c '\l'
docker compose exec redis redis-cli --askpass ping
docker compose exec qdrant curl -fsS http://127.0.0.1:6333/healthz
docker compose exec ollama-cpu ollama list
docker compose top
docker stats
```

Avoid placing secret values directly in shell history; commands that require authentication should obtain them from the process environment or prompt.

## Reset persisted state

Reset is destructive and is not exposed as a routine Taskfile command. First confirm that only this project's development resources are targeted:

```console
docker compose ls
docker compose --profile cpu ps --all
docker volume ls --filter label=com.docker.compose.project=ai-website-generator
```

After confirming the project name and accepting that all local databases, buckets, vectors, captured mail, and downloaded models will be lost, run:

```console
docker compose down --volumes --remove-orphans
```

The data cannot be recovered unless exported separately. A subsequent `task compose-up` recreates empty named volumes, both Temporal databases, and the five MinIO buckets.

## Common failures

- A required-variable error means `.env` is missing or a credential remains blank.
- A port conflict means another process owns a loopback port. Change only the corresponding host-side `*_PORT` value.
- An exited `minio-init` container with exit code zero is expected after bucket reconciliation.
- Ollama being healthy does not mean models are installed; use the readiness script.
- Temporal can take longer than PostgreSQL to become healthy while it initializes schemas.
