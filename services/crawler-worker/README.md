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
