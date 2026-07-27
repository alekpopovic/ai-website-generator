# Crawl policy

The crawler evaluates each target in this order: canonicalize it, collapse fragment-only duplicates,
detect query permutations, apply depth and project include/exclude patterns, reject known action,
download, session, facet, pagination, repeated-path, and calendar traps, evaluate the fetched robots
policy, and reserve the per-domain page budget. Denied decisions use typed codes; workers persist those
codes instead of raw parser or transport exceptions.

## Robots retrieval

The worker requests only the origin's `/robots.txt` with the configured crawler user agent. The shared
network-safety boundary validates the URL and every redirect, resolves all A/AAAA answers, detects DNS
changes before connection, enforces redirect and timeout limits, and can validate the connected peer.
The response is streamed into a 512 KiB default bound. UTF-8 BOM is accepted; NUL-containing or
undecodable data is invalid. Status 404/410 means no policy was published. Other non-success responses,
unsafe redirects, transport failures, invalid data, and oversized bodies fail closed.

The provenance record includes requested and final robots URLs, fetch status/time, content SHA-256,
redirect count, crawler identity, parsed crawl delay, sitemap declarations, and the effective campaign
limits. The body is not stored in PostgreSQL.

## URL normalization and exclusions

Canonical URLs lowercase schemes, lowercase and IDNA-normalize hosts, remove default ports and
fragments, apply RFC 3986 dot-segment and percent-encoding normalization, and preserve path case and
meaningful repeated slashes. Campaigns can sort query fields for maximum deduplication or preserve
their input order; either mode removes configured tracking parameters such as `utm_*` and `gclid`.
Preserve mode also reserves an order-independent query signature so permutations are rejected before
Scrapy schedules them.

Canonical link declarations are stored separately from the fetched URL. A same-origin canonical target
is treated as a new discovery and must pass URL safety, robots, trap, budget, and duplicate checks.
Hreflang targets are normalized and retained as bounded metadata but are not scheduled. Each page keeps
the submitted or discovered URL, normalized URL, final redirect URL, discovery source, parent URL,
canonical declaration, hreflang declarations, and available last-modified time.

## Sitemap limits

Robots-declared sitemap documents are classified separately from URLs found in nested sitemaps.
Sitemap URLs are normalized and deduplicated before request. Index recursion, aggregate location count,
compressed size, and decompressed size are bounded. Gzip streams must terminate cleanly inside the
decompressed limit. XML DTDs, entities, external resolution, and oversized trees are rejected. Valid
ISO 8601 `lastmod` values are stored in UTC; malformed timestamps are ignored without accepting an
otherwise unsafe document.

## Distributed courtesy controls

Workers use an atomic Redis TIME-based token bucket per normalized domain and an expiring ownership
token lock. Lock renew/release scripts compare the random owner token, preventing one worker from
releasing another worker's lease. Effective delay is the stricter of the campaign delay and a parsed
robots delay. Activities heartbeat while waiting and release leases during cancellation cleanup.

Scrapy runs in a one-target subprocess. Automatic redirects, cookies, and telnet are disabled; the
project downloader middleware validates every initial request and redirect before download and rejects
page responses outside the configured HTML MIME allowlist. Production scanner firewall policy remains
required because Scrapy's standard downloader cannot guarantee application-level socket pinning on
every supported platform.

Network firewalls remain mandatory: crawler workers should have scanner-egress access only, while
Redis remains on the backend network. See [outbound network safety](outbound-network-safety.md) for
browser-level residual risks and firewall policy.
