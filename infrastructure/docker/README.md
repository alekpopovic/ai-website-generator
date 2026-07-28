# Docker Infrastructure

Local and CI container definitions belong here. Defaults must keep Ollama and data services on private networks, use fake or lightweight dependencies for CI, and avoid exposing internal service ports publicly.

The root `compose.yaml` contains the development dependency stack. This directory holds trusted container configuration only:

- `postgres/init-temporal-databases.sh` creates separate `temporal` and `temporal_visibility` databases during first-time PostgreSQL initialization.
- `fixture-site/nginx.conf` serves the synthetic website fixture as an unprivileged, read-only container.
- `qdrant/Dockerfile` adds only a pinned BusyBox health-probe binary to the pinned upstream Qdrant image because the upstream image deliberately contains no HTTP client.
- `browser-worker/Dockerfile` pins the official Playwright runtime, installs only the browser worker
  and its workspace dependencies, and runs Chromium as the unprivileged `pwuser` identity.

The browser worker is opt-in through the Compose `workers` profile. Its runtime is read-only,
capability-free, bounded by CPU/memory/PID limits, and split across backend and scanner-egress
networks. Production must additionally enforce a default-deny egress proxy or firewall.
