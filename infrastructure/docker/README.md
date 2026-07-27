# Docker Infrastructure

Local and CI container definitions belong here. Defaults must keep Ollama and data services on private networks, use fake or lightweight dependencies for CI, and avoid exposing internal service ports publicly.

The root `compose.yaml` contains the development dependency stack. This directory holds trusted container configuration only:

- `postgres/init-temporal-databases.sh` creates separate `temporal` and `temporal_visibility` databases during first-time PostgreSQL initialization.
- `fixture-site/nginx.conf` serves the synthetic website fixture as an unprivileged, read-only container.
- `qdrant/Dockerfile` adds only a pinned BusyBox health-probe binary to the pinned upstream Qdrant image because the upstream image deliberately contains no HTTP client.

No application or worker image is defined at this stage.
