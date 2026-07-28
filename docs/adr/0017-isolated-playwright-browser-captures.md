# ADR 0017: Isolated Playwright browser captures

- Status: Accepted
- Date: 2026-07-28

## Context

Representative pages require rendered observations that an HTTP crawler cannot provide. Browser work
processes hostile scripts, consumes substantial CPU and memory, and can create outbound requests not
visible in the initial document. It must not run in FastAPI or share site state across captures.

## Decision

The `browser` Temporal activity receives only campaign and crawl-page UUIDs. A browser worker keeps one
Chromium process warm, subject to a bounded context semaphore, and creates a new non-persistent context
for each viewport capture. Contexts have no storage state or granted permissions, block service
workers, deny downloads and permission prompts, dismiss dialogs, close popups and new pages, and are
always closed after success, failure, timeout, or cancellation.
The Chromium child receives a minimal environment rather than inheriting worker database, storage,
Temporal, proxy, or cloud credentials.

Every routed HTTP(S) navigation, redirect, frame, worker request, and subresource passes through the
shared `PlaywrightRequestSafety` adapter immediately before continuation. Media, archive-like
downloads, and known tracking hosts are aborted. Production additionally requires default-deny scanner
egress because Playwright cannot pin Chromium's connected peer for every protocol.

Navigation waits for `domcontentloaded`, followed by a bounded font and document-dimension stability
check. It never waits for `networkidle`. Desktop and mobile captures use campaign viewports defaulting
to 1440x1000 and 390x844. Rendered HTML, full-page-or-bounded screenshots, viewport screenshots, and a
typed capture manifest are checksum-verified private objects. Page height, width, HTML bytes,
screenshot bytes, navigation time, total time, context concurrency, container memory, and PIDs are
bounded.

Rendered pages are also converted by a deterministic, versioned browser-side extractor. It prefers
visible semantic landmarks and controls, detects repeated card structures, assigns identifiers derived
from local DOM paths, records bounded geometry and computed-style fields, infers section boundaries,
aggregates style frequencies, and proposes candidate design tokens without model inference. Node count,
per-node text, and serialized payload size are hard limited. Scripts, non-visible content, tracking
markers, input values, and executable behavior are excluded. The detailed snapshot is a private
checksum-verified object; PostgreSQL retains only its key, checksum, extractor version, bounded counts,
and compact abstract summary.

PostgreSQL owns viewport scan state and sanitized metadata. A versioned configuration hash uniquely
identifies `(page, viewport, configuration)`. Content-addressed artifact filenames make retries safe
when dynamic pages render differently. Typed browser failures are persisted without raw exceptions or
URLs, and cancellation marks an in-progress scan cancelled.

## Consequences

- Cookies, local storage, cache state, service workers, and permissions cannot cross scanned sites.
- A warm process avoids repeated Chromium startup cost while preserving context isolation.
- Very tall or wide pages receive a bounded top-of-page capture and an explicit truncation flag rather
  than an unsafe unbounded image.
- Browser routing reduces exposure but is not a network sandbox; hardened containers, restricted
  credentials, and firewall or egress-proxy enforcement remain mandatory.
- Captured source HTML and text remain private scan artifacts and cannot be reused as generated copy.
- Extractor and capture schema versions participate in the configuration hash, so algorithm or limit
  changes produce a new idempotent capture instead of silently changing an existing artifact.
