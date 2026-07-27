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
distributed token bucket. Sitemap indexes are bounded to three levels; XML entities and external DTDs
are disabled. Requested/final/canonical URLs, response metadata, discovery lineage, and typed failures
are persisted idempotently. Raw HTML is disabled by default; when enabled it is gzip-compressed through
a temporary spool and streamed to the private `scan-artifacts` bucket with checksum and retention
metadata.
