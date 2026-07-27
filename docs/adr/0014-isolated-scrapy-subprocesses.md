# ADR 0014: Isolated Scrapy subprocesses

- Status: Accepted
- Date: 2026-07-28

## Decision

The persistent Temporal crawl worker never imports or starts Scrapy or Twisted. Its
`crawl-scan-target` activity starts one dedicated Python subprocess with only `campaign_id` and
`scan_target_id` arguments. That process reads authoritative configuration from PostgreSQL, acquires
Redis domain coordination, runs exactly one asyncio-backed Twisted reactor, persists normalized
discoveries and failures through repository services, optionally streams compressed HTML to private
object storage, and exits.

The activity accepts only bounded JSON progress lines, drains stderr without logging hostile content,
heartbeats progress, and terminates then kills the subprocess on cancellation. Retrying the activity is
safe because pages, robots snapshots, failures, and artifact keys use stable database identities or
semantic uniqueness constraints.

## Consequences

Reactor lifecycle and crawler memory are isolated from the long-lived Temporal poller. Subprocess
startup adds bounded overhead, but failures and leaks are contained per target. Campaign fan-out and
the later browser/analysis stages remain separate orchestration work; this decision implements only the
crawl activity boundary.
