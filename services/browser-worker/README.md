# Browser Worker

Runs isolated Playwright rendering activities for approved URLs discovered by the crawler. It captures bounded screenshots and structural metadata while enforcing network interception, SSRF protection, resource limits, and browser sandboxing.

Every navigation, frame, worker, and subresource must pass through `PlaywrightRequestSafety`.
Application interception is backed by a default-deny worker firewall or egress proxy because Chromium
does not expose reliable peer-address pinning for all browser traffic.

## Runtime model

`platform-browser-worker` polls only the Temporal `browser` queue. The
`render-representative-page` activity receives campaign and crawl-page UUIDs, reloads the selected-page
configuration from PostgreSQL, and captures desktop and mobile viewports. One Chromium process remains
warm per worker; every viewport uses a new non-persistent browser context with service workers blocked,
no granted permissions, downloads denied, dialogs dismissed, and popups/new windows closed. Contexts
are closed on success, failure, timeout, and cancellation.
Chromium receives a minimal child environment and does not inherit the worker's database, MinIO,
Temporal, proxy, or cloud credential variables.

The worker uses `domcontentloaded` plus bounded font and layout stabilization and never waits for
`networkidle`. It aborts media, archive-like downloads, and known tracker hosts while retaining CSS and
normal images. Full-page captures are bounded to safe dimensions and carry an explicit truncation flag.
Rendered HTML, full-page and viewport PNGs, and the capture manifest are private checksum-verified
`scan-artifacts` objects.

Each stabilized viewport also produces extractor version `browser-semantic-v1`. The browser selects
visible semantic landmarks, headings, text, lists, links, controls, forms, images, figures, and
deterministically detected repeated cards. Stable local DOM-path identifiers connect nodes to inferred
semantic or geometric sections. Bounded geometry, accessibility metadata, computed typography,
spacing, border, color, shadow, flex/grid, image, and positioning properties feed deterministic style
frequencies and candidate design tokens. The detailed JSON snapshot is gzip-compressed in private
object storage; PostgreSQL stores only its artifact key, checksum, version, counts, truncation state,
and compact summary. No snapshot is sent to Ollama by this worker.

Each successful viewport now creates typed relational records for rendered HTML, the viewport-specific
full screenshot, viewport screenshot, semantic snapshot, extracted nodes, style summary, network
manifest, console diagnostics, and the final scan metadata manifest. All JSON/HTML bodies are gzip
compressed, and every object carries immutable checksum, scanner, URL, campaign, source website,
viewport, timestamp, provenance, and retention metadata.

Default extraction limits are 500 nodes, 240 normalized text characters per node, and 1 MiB of
validated JSON. Selection prioritizes visible semantics when the node limit is reached. Scripts,
styles, templates, hidden or `aria-hidden` descendants, tracking markers, input values, and one-pixel
images are excluded.

Configuration hashes include the capture schema, source identity, viewport, and resource limits.
Successful hashes are skipped on retry; content-addressed artifact filenames tolerate dynamic
re-rendering. Failures are typed and sanitized, activity progress is heartbeat-only, and large content
never enters Temporal history.

## Local execution

Install Chromium explicitly after bootstrap if the host does not already have the locked revision:

```console
uv run playwright install chromium
task browser-worker
```

The hardened container is opt-in:

```console
docker compose --profile workers build browser-worker
docker compose --profile workers up browser-worker
```

It runs as `pwuser`, read-only, without Linux capabilities, with bounded memory, shared memory, CPUs,
and PIDs. Production deployment must add a default-deny egress proxy or firewall and permit only
validated public HTTP(S) destinations.
