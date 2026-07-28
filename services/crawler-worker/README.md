# Crawler Worker

Runs policy-aware Scrapy discovery and retrieval activities. It enforces authorization, `robots.txt`, rate limits, redirect and SSRF controls, content limits, provenance capture, and source licensing metadata before storing crawl artifacts in object storage.

Every Scrapy request and redirect must pass through `ScrapyRequestSafety`; automatic redirect
following is disabled. The adapter revalidates DNS immediately before connection, validates the peer
when the connector exposes it, rejects non-HTML responses, and streams decoded bodies through shared
limits.

Discovery activities construct `CrawlPolicyEvaluator` from the persisted campaign and robots snapshot.
They must acquire `RedisCrawlLocks` and `RedisDomainRateLimiter` before outbound work, heartbeat while
waiting, and persist the bounded decision provenance on each crawl page. The worker uses the stricter
of campaign and parsed robots crawl delays. `robots.txt` compliance cannot be disabled by a normal API
request.

## Process model

The Temporal worker polls only the `crawl` queue and never imports Scrapy. For each
`crawl-scan-target` activity it launches a dedicated `platform-crawler-subprocess` with the campaign
and target UUIDs. The child loads database configuration, obtains the domain Redis lease and token
bucket, starts one asyncio-backed Twisted reactor, and exits after one target. Cancellation terminates
the child, waits ten seconds, and kills it only if necessary.

The spider fetches robots first, follows only safety-validated redirects, visits bounded declared
sitemaps and same-origin HTML links, and uses conservative AutoThrottle settings in addition to the
distributed token bucket. Sitemap index recursion, aggregate URL count, compressed and decompressed
sizes are bounded; gzip is supported, while XML entities and external DTDs are disabled. Canonical URL
declarations pass normal admission before scheduling, while hreflang declarations remain metadata.
Original, normalized, final, and declared-canonical URLs, sitemap `lastmod`, response metadata,
discovery lineage, and typed failures are persisted idempotently. Raw HTML is disabled by default; when
enabled it is gzip-compressed through a temporary spool and streamed to the private `scan-artifacts`
bucket under a content-addressed immutable key. Each retained response gets a restricted typed
artifact record and mirrors its checksum, source/final URL, scan timestamp, scanner version, source
website, campaign, provenance, content type, and retention metadata into object storage. Raw HTML is
never exposed through ordinary frontend access.

## Page fingerprinting

The crawler computes versioned fingerprints from each bounded HTML response without executing page
content or invoking an LLM. Normalization removes executable/style nodes, analytics noise, volatile
timestamps, random IDs, CSRF values, and obvious dynamic tokens while retaining semantic elements,
stable attributes, headings, and link topology. Response bytes retain a separate SHA-256 fingerprint.

After a target crawl, an advisory-lock-protected campaign pass assigns deterministic exact-content,
near-content, and shared-template representatives. Every source row remains intact. Large repeated
article collections are visible as template groups of at least three pages. To repair group assignments
or upgrade stored fingerprints explicitly, run:

```shell
uv run platform-crawler-fingerprint-backfill --campaign-id <campaign-uuid>
```

Missing fingerprints can be reconstructed only when the page has a retained raw-HTML artifact. The
command verifies object checksums, bounds gzip decompression, updates rows transactionally, and then
recalculates campaign groups idempotently.

## Page classification and visual representatives

Each fetched page is classified without an LLM from bounded path, title, heading, navigation,
schema.org, link-density, form, content-length, semantic-DOM, and repeated-template signals. The
replaceable `PageClassifier` contract and persisted classifier version allow a later learned model
without changing crawler or API boundaries.

After duplicate grouping, a versioned deterministic selector chooses no more than
`max_visual_pages_per_domain`. It prefers the homepage, important commercial and informational page
types, and one content page while choosing at most one automatic representative from a template
cluster. Legal and authentication pages remain excluded unless the campaign explicitly enables them
or an owner manually includes one. Every page stores its selection score and reason, including
rejections. This stage only records candidates; it does not invoke Playwright.
