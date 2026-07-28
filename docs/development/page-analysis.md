# DSPy Page Analysis

## Boundary and output

`platform_ai_worker.page_analyzer.PageAnalyzer` is a worker-only interface. FastAPI may dispatch an
identifier-only Temporal command but must never construct an analyzer or perform inference. The AI
activity that integrates this boundary must load private scan artifacts by database ID and object
key, call the analyzer, and persist the validated result and safe run metadata. Screenshots and
snapshots must not cross Temporal workflow history.

The v1 output is `PageAnalysisPayload`. It contains a schema-valid `PageProfile`, normalized
`DesignTokens`, ordered section-derived responsive observations, accessibility observations, and
controlled uncertainty codes. Its validator rejects conflicting top-level and `PageProfile`
projections. Free-text uncertainty, arbitrary component names, HTML, code, URLs, source prose, and
source assets are not valid output.

Every successful result includes:

- prompt version `page-analysis-v1`;
- analyzer version `dspy-page-analyzer-v1`;
- analysis schema version;
- DSPy or direct-Ollama strategy;
- configured model name and installed digest;
- bounded attempt count and wall latency;
- a typed fallback reason when DSPy was not used.

Prompt bodies, screenshots, extracted content, and model response bodies are never logged.

## Input compaction and source-use policy

Before transport, deterministic compaction removes node text, heading text, ARIA labels, raw font
family names, image references, attributes, URLs, and unknown fields. It retains only bounded
geometry, semantic roles, generic layout values, aggregate counts, and at most 160 nodes and 64
sections. Style frequencies are converted through the deterministic shared normalizer, which emits
generic font categories and validated CSS values. The combined deterministic prompt contribution is
limited to 192 KiB; each image is limited to 10 MiB and both images together to 20 MiB.

Both the DSPy signature and direct fallback explicitly prohibit copying brand names, original
sentences, logos, image assets, proprietary source code, or a complete composition. Screenshot pixels
remain untrusted evidence and never become reusable source assets.

## DSPy and direct fallback

DSPy 3.2.1 runs `AnalyzePageSignature` through `PageAnalysisModule` with the configured
`OLLAMA_VISION_MODEL` (default `qwen3-vl:8b`) and the private `OLLAMA_URL`. Calls run off the asyncio
event loop because DSPy/LiteLLM is synchronous. Invalid structured output and recognized transient
provider errors receive at most two total attempts by default. Pydantic validation then checks the complete output again,
and the analyzer rejects any attempt to change the source page ID or deterministic page type.

The analyzer does not infer DSPy vision compatibility from package presence. It first checks Ollama's
installed-model metadata and advertised `vision` capability, checks the DSPy image and structured
APIs, and executes a one-pixel local image probe with a typed literal response. The result is cached
per analyzer. A failed or disabled probe selects the existing direct Ollama structured-vision method
behind the same interface and records a bounded reason. Missing models are never pulled.

LiteLLM is forced to use its bundled local model-cost map so imports do not access the internet.
Set `DSPY_CACHEDIR` to a private writable worker directory in production; the default local value is
`/tmp/ai-platform-dspy-cache`. Inference caching is disabled for this program.

## Tests

Default unit tests use `FakeLLMGateway` and a deterministic fake DSPy program. They require no model,
GPU, network, Temporal, or object storage and cover compaction, capability truthfulness, direct
fallback, metadata, identity preservation, and hostile output fields.

The explicit local compatibility test verifies the actual DSPy/LiteLLM/Ollama image path:

```sh
RUN_OLLAMA_INTEGRATION=1 \
  OLLAMA_URL=http://127.0.0.1:11434 \
  OLLAMA_VISION_MODEL=qwen3-vl:8b \
  uv run pytest services/ai-worker/tests/integration/test_local_ollama_page_analysis.py
```

This test is opt-in because it requires a private running Ollama service and an installed vision
model. It never pulls a model.
