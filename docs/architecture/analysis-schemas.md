# AI-normalized analysis contracts

The versioned `WebsiteProfile` family is the only supported structured boundary between scan
artifacts and later AI workflows. Deterministic browser observations remain immutable source
artifacts; normalization creates abstract patterns rather than a reconstruction of the scanned
website.

The boundary enforces four properties:

1. Structural vocabulary is controlled through section, component, page, copy-purpose, layout,
   responsive, and accessibility registries.
2. Content-bearing source concepts are absent. There are no schema fields for brand or customer
   names, logos, photographs, source assets, raw copy, HTML, code, templates, or source URLs.
3. Provenance contains database UUIDs, versions, timestamps, and SHA-256 digests only. Workers pass
   these IDs and object keys separately through Temporal rather than embedding artifacts.
4. All collections, strings, dimensions, confidence scores, colors, and ordering relationships are
   bounded and validated before persistence or downstream use.

JSON Schema artifacts are generated directly from Pydantic and committed under
`packages/python/platform-schemas/json-schema`. They may be supplied to a structured inference
provider in later work, but this schema implementation and its deterministic style conversion make
no model calls.
