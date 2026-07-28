# AI Worker

Runs private Ollama inference and DSPy programs for visual interpretation, structured extraction,
planning, and repair proposals. Outputs must validate against shared Pydantic schemas and may never
be executed as code, templates, commands, SQL, or arbitrary URLs.

The process polls the Temporal `ai-analysis` queue. Its page analyzer defines DSPy signatures for
copy-free deterministic observations plus desktop and optional mobile screenshots, validates a
strict `PageAnalysisPayload`, and records prompt, schema, model, digest, strategy, attempt, and
latency metadata. A capability probe must prove that the installed DSPy/LiteLLM path can carry a
local image to the configured Ollama vision model. If that probe fails, the same `PageAnalyzer`
boundary uses the provider-neutral direct Ollama structured-vision method and records the reason.

The currently registered `warm-up-model` activity receives only IDs and a configured model role,
heartbeats during model loading, and never pulls a model. Page-analysis orchestration likewise
belongs in this worker: Temporal payloads carry IDs/object keys and repository code resolves artifact
bodies inside the activity process. Start the worker with `task ai-worker` after Temporal and private
Ollama are available. See [page analysis](../../docs/development/page-analysis.md).
