# ADR 0016: Deterministic page classification and representative selection

- Status: Accepted
- Date: 2026-07-28

## Context

Rendered scans are materially more expensive than discovery. A campaign therefore needs a bounded,
repeatable way to classify discovered pages and choose a useful, diverse visual sample without using
an LLM or executing page content. Classification must remain explainable, support user correction,
and be replaceable by a learned implementation later.

## Decision

The crawler extracts bounded structural features from already fetched HTML: normalized path, title,
major headings, navigation labels, schema.org types, link-density measurements, form and password
presence, content length, semantic element counts, and the deterministic template group. A
`PageClassifier` protocol separates the feature contract from the initial versioned rule classifier.
The result is one string-backed page type, a normalized score, reasons, classifier name, and version.

A separate versioned selector ranks classifications deterministically by policy score, normalized URL,
and UUID. It prefers the homepage, then pricing, product, services, about, contact, and features, plus
one content page. Automatic choices use at most one member of a template cluster. Legal and
authentication pages are ineligible unless campaign configuration explicitly enables them; an owned,
optimistically versioned manual include or exclude takes precedence. Every candidate receives a score
and a selected or rejected reason, even when the maximum is zero or capacity is intentionally unused.

Classification and selection run in the crawler subprocess after fingerprint grouping. The FastAPI
control plane may only recompute the cheap selection policy when recording a manual override; it does
not crawl, render, or invoke a model. PostgreSQL stores the feature snapshot, decisions, versions, and
manual-override audit metadata. No Playwright work is scheduled by this decision.

## Consequences

- Identical inputs and versions produce identical page types, rankings, and explanations.
- Template diversity can produce fewer selections than the configured maximum; the maximum is a cap,
  not a fill target.
- Rule errors can be corrected without deleting provenance, and stored versions permit later backfills.
- A future learned classifier must implement the same typed interface and persist a new version. Its
  rollout requires evaluation and an explicit reclassification operation.
- Bounded titles and structural labels are retained as scan metadata for deterministic recalculation;
  they are not used as generated-site copy.
