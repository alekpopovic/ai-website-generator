# Local LLM Gateway

## Boundary and providers

`platform_clients.llm.LLMGateway` is the provider-neutral boundary for chat generation, Pydantic
JSON Schema generation, structured vision analysis, embeddings, model listing, model metadata,
capability probing, readiness, and warm-up. Domain and worker code must not depend on Ollama response
types. A future vLLM adapter must implement the same contracts and return the same inference metadata.

Ollama is the initial adapter. It uses only its configured private service root and fixed model roles:

- vision: `qwen3-vl:8b`;
- generation: `qwen3-coder:30b`;
- embedding: `qwen3-embedding:0.6b`.

Callers cannot provide an endpoint or arbitrary model name. The client disables redirects and proxy
environment inheritance. Angular never receives the Ollama URL and never calls Ollama directly.

## Structured output and metadata

Structured and vision methods pass `BaseModel.model_json_schema()` to Ollama's `format` field and
validate the returned JSON with that exact Pydantic model. Invalid JSON, transport response shapes,
non-finite embeddings, and schema violations fail closed. Model output remains inert data and must
never be evaluated as HTML, JavaScript, templates, Python, SQL, shell commands, or URLs.

Every successful inference result records the provider, returned model name, installed model digest,
wall latency, provider total/load duration, and prompt or completion token counts when Ollama supplies
them. Prompt bodies, images, output bodies, tokens, credentials, and proprietary content are never
logged.

## Limits and resilience

Before transport, known bearer credentials, key assignments, AWS access-key IDs, and private-key
blocks are replaced with `[REDACTED]`. Prompt, schema, per-image, combined-image, and provider-response
byte limits are mandatory. Requests use a bounded semaphore, acquisition timeout, request timeout,
and connection pool.

Only transport failures, transient HTTP statuses, malformed provider responses, or schema-invalid
model responses are retried. Authentication, validation, missing-model, and other non-transient 4xx
responses are not retried. Repeated retryable failures open a process-local circuit for the configured
recovery interval.

`GET /api/v1/models/readiness` reports whether each configured model is installed and advertises its
required capability. The general dependency health endpoint treats missing or incapable models as a
non-critical Ollama degradation.

## Warm-up and model installation

`POST /api/v1/admin/models/{model_role}/warm-up` requires a bearer-authenticated email listed in
`SECURITY_ADMINISTRATOR_EMAILS` and an idempotency key. FastAPI starts `ModelWarmupWorkflow`; the
workflow delegates model loading to the `ai-analysis` activity worker. FastAPI never loads the model
inside the request process.

The worker sends an empty generation request, or an empty embedding request for the embedding role,
with `keep_alive` only after model listing and capability metadata confirm that the configured model
is installed. No public API handler or gateway method calls Ollama's pull endpoint. Model installation
remains the explicit operator action documented in the local stack guide.

Run the workflow and activity workers locally:

```sh
task workflow-worker
task ai-worker
```

## Tests

`FakeLLMGateway` is deterministic and performs no I/O. Adapter unit tests use an in-process fake
Ollama HTTP server and cover structured validation retries, redaction, embeddings, vision, metadata,
readiness, warm-up, transient and non-transient failures, circuit breaking, concurrency, and timeouts.
Default CI requires neither installed models nor a GPU.
