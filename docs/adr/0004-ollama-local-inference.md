# ADR 0004: Ollama as the Initial Local Inference Provider

- Status: Accepted
- Date: 2026-07-27

## Context

Initial vision, generation, repair, and embedding workflows need locally controlled inference with replaceable model choices and no dependency on a public model endpoint.

## Decision

Use Ollama as the initial inference provider behind typed internal clients and dedicated workers. Ollama remains on a private network with no public ingress and is never called directly by Angular. Model identity, digest, parameters, and prompt or DSPy program version are recorded with outputs. Default CI uses deterministic fakes.

## Consequences

- Data stays within the controlled deployment boundary.
- Hardware capacity, model distribution, warm-up, and concurrency require operations support.
- Provider abstractions must avoid leaking Ollama response formats into domain contracts.
- Structured responses are validated against caller-owned Pydantic JSON Schemas, and safe results
  record model digest and timing/token metadata without logging prompt or content bodies.
- Readiness may perform bounded list/show calls from the control plane. Inference and model warm-up
  remain worker activities; warm-up never implies model installation.
- A later provider can be introduced without changing API or workflow contracts.
