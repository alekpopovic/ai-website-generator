# Platform schemas

`platform-schemas` owns versioned Pydantic contracts at the AI-output trust boundary. Version 1
normalizes deterministic scan observations into abstract design tokens, page structure, controlled
component patterns, accessibility observations, confidence, and identifier-only provenance. It has
no model-provider dependency and performs no inference.

The contract intentionally has no fields for raw copy, HTML, source URLs, brand/customer names,
logos, image bytes, source assets, templates, or executable code. Copy is represented only by the
controlled `CopyPurpose` registry. Section and component types are enums, so arbitrary component
names cannot reach later rendering stages.

## Schemas and fields

Every field also has a `description` in its generated JSON Schema.

| Schema                       | Field                        | Meaning and bounds                                                                 |
| ---------------------------- | ---------------------------- | ---------------------------------------------------------------------------------- |
| Every public analysis schema | `schema_version`             | Literal version `1`, inherited from the shared versioned base.                     |
| `WebsiteProfile`             | `schema_version`             | Literal version `1`.                                                               |
|                              | `design_tokens`              | Cross-page `DesignTokens`.                                                         |
|                              | `pages`                      | 1–100 unique representative `PageProfile` records; at most one homepage.           |
|                              | `confidence`                 | Aggregate `AnalysisConfidence`.                                                    |
|                              | `provenance`                 | Identifier-only `AnalysisProvenance`.                                              |
| `PageProfile`                | `schema_version`             | Literal version `1`.                                                               |
|                              | `source_page_id`             | Internal crawl-page UUID.                                                          |
|                              | `page_type`                  | Controlled page classification.                                                    |
|                              | `sections`                   | 1–64 zero-based, contiguous `SectionPattern` records.                              |
|                              | `accessibility_observations` | Up to 100 controlled findings.                                                     |
|                              | `confidence`                 | Per-page confidence dimensions.                                                    |
| `DesignTokens`               | `colors`                     | Validated `ColorTokens`.                                                           |
|                              | `typography`                 | `TypographyTokens` normalized to CSS pixels and numeric weights.                   |
|                              | `spacing`                    | `SpacingTokens` normalized to CSS pixels.                                          |
|                              | `style_tags`                 | Up to 24 unique values from the controlled non-brand visual-style registry.        |
| `ColorTokens`                | `palette`                    | Up to 24 unique color tokens ordered by nonincreasing frequency.                   |
| `ColorToken`                 | `name`                       | Stable kebab-case token name, never a brand label.                                 |
|                              | `value`                      | Hex, RGB(A), or HSL(A) color; CSS URLs and declarations are rejected.              |
|                              | `frequency`                  | 1–100,000 deterministic observations.                                              |
| `TypographyTokens`           | `font_families`              | Up to eight controlled generic font categories; source family names are discarded. |
|                              | `font_sizes_px`              | Up to 20 unique ascending values from 1–512 px.                                    |
|                              | `font_weights`               | Up to 12 unique ascending numeric weights from 1–1000.                             |
|                              | `line_heights_px`            | Up to 20 unique ascending values from 1–512 px.                                    |
| `SpacingTokens`              | `scale_px`                   | Up to 24 unique ascending values from 0–2048 px.                                   |
|                              | `radius_px`                  | Up to 16 unique ascending values from 0–1024 px.                                   |
| `SectionPattern`             | `section_type`               | Controlled section registry value.                                                 |
|                              | `order`                      | Zero-based page order, bounded to 255.                                             |
|                              | `copy_purpose`               | Controlled abstract communication goal.                                            |
|                              | `layout`                     | Controlled high-level layout category.                                             |
|                              | `components`                 | Up to 64 contiguous `ComponentPattern` records.                                    |
|                              | `responsive_behaviors`       | Up to 16 ordered, non-overlapping viewport behaviors.                              |
| `ComponentPattern`           | `component_name`             | Controlled component registry value.                                               |
|                              | `order`                      | Zero-based section order, bounded to 255.                                          |
|                              | `copy_purpose`               | Controlled abstract communication goal.                                            |
|                              | `repeat_count`               | Bounded repetition count from 1–100.                                               |
|                              | `layout`                     | Controlled component layout category.                                              |
| `ResponsiveBehavior`         | `minimum_width_px`           | Inclusive lower width from 240–7680 px.                                            |
|                              | `maximum_width_px`           | Inclusive upper width from 240–7680 px and not below the minimum.                  |
|                              | `behavior`                   | Controlled responsive transformation.                                              |
|                              | `affected_components`        | Up to 24 unique controlled component names.                                        |
| `AccessibilityObservation`   | `category`                   | Controlled accessibility review category.                                          |
|                              | `code`                       | Stable finding code without source text.                                           |
|                              | `severity`                   | `positive`, `info`, `warning`, or `error`.                                         |
|                              | `affected_count`             | 1–10,000 deterministic observations.                                               |
|                              | `confidence`                 | Normalized confidence from 0–1.                                                    |
| `AnalysisConfidence`         | `overall`                    | Aggregate confidence from 0–1, bounded by dimension scores.                        |
|                              | `structure`                  | Section/component confidence from 0–1.                                             |
|                              | `design_tokens`              | Token confidence from 0–1.                                                         |
|                              | `responsive_behavior`        | Responsive inference confidence from 0–1.                                          |
|                              | `accessibility`              | Accessibility finding confidence from 0–1.                                         |
| `AnalysisProvenance`         | `source_website_id`          | Internal source website UUID.                                                      |
|                              | `campaign_id`                | Owning campaign UUID.                                                              |
|                              | `page_scan_ids`              | 1–100 unique input page-scan UUIDs.                                                |
|                              | `artifact_sha256`            | Up to 500 artifact-role/SHA-256 pairs; no keys or URLs.                            |
|                              | `scanner_version`            | Bounded scanner version.                                                           |
|                              | `extractor_version`          | Bounded extractor version.                                                         |
|                              | `analyzer_version`           | Bounded analyzer version.                                                          |
|                              | `analyzed_at`                | Timezone-aware completion timestamp.                                               |
|                              | `deterministic_only`         | Whether no model inference contributed.                                            |

The initial `SectionType` registry contains header, navigation, hero, logo-cloud, features,
services, stats, content, gallery, testimonials, case-studies, pricing, comparison, faq, cta,
contact, footer, and unknown. `logo-cloud` describes only layout structure; logo identities and
assets are never represented.

## Deterministic conversion and versions

`design_tokens_from_style_summary` consumes the browser extractor's bounded style-frequency
projection. It validates input sizes, rejects unsafe colors, accepts pixel dimensions only, sorts
and deduplicates scales, and returns the same tokens for equivalent input.

`migrate_website_profile` copies and validates payloads. Future versions register explicit
one-version-at-a-time transformations through `register_website_profile_migration`; downgrades,
unknown gaps, and migrations that do not advance exactly one version fail closed.

Regenerate committed schemas with `task generate-analysis-schemas`. Root verification executes
`task verify-analysis-schemas` and fails if any artifact is stale.
