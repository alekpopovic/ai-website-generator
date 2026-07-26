# ADR 0008: RAG and DSPy Optimization Before Fine-Tuning

- Status: Accepted
- Date: 2026-07-27

## Context

Many output-quality problems can be addressed through better retrieval, structured programs, examples, and evaluation. Fine-tuning adds dataset governance, compute, evaluation, deployment, and rollback complexity.

## Decision

Improve retrieval-augmented generation and optimize structured DSPy programs against versioned evaluations before considering fine-tuning. Fine-tuning with TRL and PEFT, optionally QLoRA, is an explicit later-stage workflow used only when measured gaps persist and an authorized, licensed, provenance-complete dataset exists.

## Consequences

- Early iteration is faster and does not require GPUs in the default development or CI path.
- Retrieval, prompts, DSPy programs, model versions, and evaluation sets must be versioned.
- Training needs a documented business case, baseline, promotion gate, and rollback plan.
- Training remains optional and isolated from request-serving and normal generation workloads.
