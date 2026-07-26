# ADR 0005: SiteSpec as the Generation Contract

- Status: Accepted
- Date: 2026-07-27

## Context

Arbitrary model-generated HTML, scripts, or templates are difficult to validate, reproduce, secure, edit, and migrate. Generated sites require deterministic behavior and a strong security boundary.

## Decision

Models produce strict, versioned Pydantic structures such as `WebsiteProfile`, `PageSpec`, and `SiteSpec`. A deterministic renderer maps `SiteSpec` discriminators to versioned registered components, escaped Jinja2 templates, design tokens, and project-authored controlled JavaScript. Unknown fields, components, behaviors, and unsafe URLs are rejected. Model-authored code or templates are never executed.

## Consequences

- Outputs are reproducible, testable, editable, and policy-checkable.
- Expressiveness is limited to the component registry by design.
- Schema and component migrations require compatibility rules.
- Adding a visual capability requires an audited component rather than prompt changes alone.
