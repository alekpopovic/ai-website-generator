# ADR 0007: Scrapy and Playwright Two-Stage Scanning

- Status: Accepted
- Date: 2026-07-27

## Context

Broad discovery is more efficient over HTTP, while selected client-rendered pages need a browser to observe computed layout and visual results. Rendering every discovered page is costly and expands the attack surface.

## Decision

Use Scrapy first for policy-aware discovery and bounded HTTP collection, then Playwright for an approved subset requiring rendered analysis. Both stages run in isolated workers and independently enforce authorization, `robots.txt`, rate limits, redirect limits, SSRF defenses, resource limits, provenance, and cancellation. Browser request interception applies URL policy to every subresource.

## Consequences

- Most pages avoid browser cost while dynamic pages remain observable.
- Selection policy and handoff manifests must be explicit and reproducible.
- Two worker classes can scale and be secured separately.
- Shared URL and provenance policy must behave consistently across both stages.
