# Workflow Event Streaming

The control plane exposes authenticated workflow progress at
`GET /api/v1/projects/{project_id}/jobs/{job_id}/events`. The same cursor can be
used with `/events/poll?after={sequence}` when an intermediary cannot carry a
long-lived response.

PostgreSQL `job_events` is the authoritative append-only projection. Each job
uses a Redis Stream named `aiwg:job-events:{job_id}` only as a low-latency wakeup
channel. The PostgreSQL `(job_id, sequence)` uniqueness constraint and explicit
Redis IDs such as `42-0` keep retries idempotent and ordering monotonic. A client
reconnects with `Last-Event-ID: 42`; the API reads every later event from
PostgreSQL before waiting on Redis, so Redis trimming cannot create a gap.

The public event contract supports scan campaigns, dataset builds, generation,
validation, and training. Payloads pass through an explicit progress-field
allowlist. Prompts, scanned content, object keys, source URLs, model internals,
and secrets are never serialized to clients.

## Authentication and connection lifecycle

Every initial connection and polling request verifies project ownership. During
an SSE response, the API periodically revalidates the user, project ownership,
access-token expiry, and backing refresh-token session. Logout, logout-all,
account disablement, session rotation, or authorization loss therefore closes
the stream. The Angular client also aborts all active connections immediately
when its in-memory access token is cleared and reconnects with the newly rotated
token when appropriate.

Redis leases enforce `REDIS_JOB_EVENT_MAX_STREAMS_PER_USER` across API replicas.
The leases expire after an unclean disconnect and are renewed during normal
heartbeats. Fake-dependency tests use the equivalent process-local limiter.

## Reverse proxy requirements

The API sends `Content-Type: text/event-stream`, `Cache-Control: no-cache,
no-store`, `X-Accel-Buffering: no`, and periodic comment heartbeats. Proxies and
ingresses must additionally be configured to:

- disable response buffering and compression for the event path;
- stream chunks immediately rather than waiting for a minimum response size;
- allow an idle/read timeout longer than the configured heartbeat interval;
- preserve `Authorization` and `Last-Event-ID` headers;
- avoid caching or transforming the response;
- keep HTTP/2 stream and per-client connection limits compatible with the API
  limit.

For NGINX, use `proxy_buffering off`, `proxy_cache off`, and a
`proxy_read_timeout` comfortably above 15 seconds on this location. Equivalent
settings are required for Kubernetes ingress controllers, CDNs, and managed
load balancers. Verify reconnect behavior through the full production proxy
chain, not only against Uvicorn directly.

## Inspection

Use the polling endpoint to inspect a job without keeping a connection open.
Redis data may be inspected with `XRANGE aiwg:job-events:{job_id} - +`, but it is
not a source of record. Investigate missing durable transitions in PostgreSQL or
the activity that owns the transaction; do not reconstruct them from Redis.
