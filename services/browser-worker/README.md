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
