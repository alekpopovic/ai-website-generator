# Temporal Workers

## Boundaries

`platform-workflows` is the shared Temporal foundation used by FastAPI and worker services. Workflow
code contains deterministic orchestration only. It must not open databases, call Redis, fetch URLs,
read object storage, invoke Ollama, access Qdrant, inspect the local clock, or generate random values.
Those operations belong in idempotent activities.

Workflow and activity contracts carry UUID strings and bounded object-storage keys. HTML, screenshots,
model responses, datasets, generated files, and binary data remain in object storage and are referenced
by key.

## Queues

| Queue         | Responsibility                                       |
| ------------- | ---------------------------------------------------- |
| `control`     | workflow orchestration and short metadata activities |
| `crawl`       | policy-aware Scrapy discovery and retrieval          |
| `browser`     | isolated Playwright scans                            |
| `ai-analysis` | structured vision and analysis                       |
| `embedding`   | embedding inference and vector updates               |
| `generation`  | structured `SiteSpec` generation                     |
| `render`      | deterministic registered-component rendering         |
| `validation`  | static, browser, accessibility, and security checks  |
| `training`    | explicitly authorized optional training              |

Each activity category uses a bounded retry policy. Policy, authorization, schema, and invalid-input
errors are non-retryable. Long-running activity implementations must configure a heartbeat timeout,
use `ActivityHeartbeat`, and check cooperative cancellation between bounded units of work.
Job events use the durable `(job_id, sequence)` identity as their semantic deduplication key; Redis
Streams provide ephemeral fan-out while PostgreSQL remains the durable event projection.

## Starting locally

Start the dependency stack and wait for Temporal to become healthy:

```sh
task compose-up
docker compose ps temporal
```

Then start the workflow worker in a separate terminal:

```sh
task workflow-worker
```

The service registers `ScanCampaignWorkflow`, `DatasetBuildWorkflow`, `SiteGenerationWorkflow`,
`TrainingRunWorkflow`, and the administrator-only `ModelWarmupWorkflow` on `control`. Other business
activities remain future work except for the target-level Scrapy crawl activity.

`ScanCampaignWorkflow` is intentionally control-only in the current increment. It retains durable
queued/paused/cancelling control state and accepts pause, resume, and cancel signals, but it has no
campaign fan-out, browser, AI, embedding, or completion activities. The implemented
`crawl-scan-target` activity is registered separately on `crawl` and receives only campaign and target
UUIDs.

Start the crawler activity worker in another terminal:

```sh
task crawler-worker
```

Each activity creates a dedicated `platform-crawler-subprocess`, heartbeats bounded page counts, and
terminates that child on cancellation. The child owns one Twisted reactor lifecycle, reloads campaign
configuration from PostgreSQL, and writes through crawler repository services. Its stdout protocol is
bounded JSON progress only; stderr is drained and never copied into application logs.

Model warm-up requires the private AI activity worker in another terminal:

```sh
task ai-worker
```

It polls `ai-analysis`, heartbeats during model loading, and uses the provider-neutral gateway. It
never downloads models and never runs model work inside FastAPI. Future activity-worker entry points
use the shared `WorkerConfig`, their assigned queue, and `WorkerHealthIndicator` for explicit
ready/stopping/failed process state.

Stop the foreground worker with `Ctrl-C`, then stop dependencies with `task compose-down`.

## Testing

Unit tests use fake dispatchers, fake event publishers, and Temporal's in-process activity test
environment. They never contact Temporal or download binaries.

Workflow integration tests use Temporal's time-skipping test environment only when an existing test
server executable is explicitly configured:

```sh
TEMPORAL_TEST_SERVER_PATH=/absolute/path/to/temporal-test-server task integration-test
```

If the variable is absent, these tests skip. This prevents default CI from downloading tools or
requiring internet access. The executable should be provisioned and checksum-verified separately by
the development or CI environment.

## Duplicate prevention

Dispatch IDs follow `aiwg:{workflow-kind}:{resource-uuid}:{idempotency-key}`. The real dispatcher uses
Temporal's reject-duplicate reuse policy and fail-on-conflict policy. API handlers must authorize and
persist their compact command before dispatch and reuse the same idempotency key when retrying the
same logical request.
