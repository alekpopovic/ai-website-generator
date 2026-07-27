# Scan Campaign API

Scan campaign routes are nested under `/api/v1/projects/{project_id}/scan-campaigns`. Every query
joins through project ownership; another user's project or campaign is returned as not found.

## Campaign configuration

Creation requires a name and timezone-aware authorization-attestation timestamp. Defaults retain
`robots.txt` enforcement and bound discovery, visual scans, depth, per-domain and overall
concurrency, crawl delay, desktop/mobile viewports, content types, URL globs, network/browser/
campaign timeouts, and artifact retention. Configuration is editable only while the campaign is a
draft and uses an optimistic `version`.

URL include/exclude patterns are bounded forward-slash globs, not executable regular expressions.
Targets permit only credential-free HTTP(S), ports 80/443, and statically public destinations.
Literal private, loopback, link-local, multicast, reserved, localhost, `.local`, and `.internal`
destinations are rejected. This is an initial control-plane check; workers must re-resolve and apply
SSRF policy at every URL and redirect boundary.

## Routes

| Method   | Path                                 | Purpose                                      |
| -------- | ------------------------------------ | -------------------------------------------- |
| `POST`   | `/`                                  | Create a draft campaign                      |
| `GET`    | `/`                                  | List/search/filter owned campaigns           |
| `GET`    | `/{campaign_id}`                     | Read campaign configuration and state        |
| `PATCH`  | `/{campaign_id}`                     | Optimistically edit a draft                  |
| `DELETE` | `/{campaign_id}`                     | Delete a draft only                          |
| `POST`   | `/{campaign_id}/start`               | Queue and dispatch a control-only workflow   |
| `POST`   | `/{campaign_id}/pause`               | Commit `pausing`, then signal Temporal       |
| `POST`   | `/{campaign_id}/resume`              | Commit `running`, then signal Temporal       |
| `POST`   | `/{campaign_id}/cancel`              | Commit `cancelling`, then signal Temporal    |
| `POST`   | `/{campaign_id}/retry-failures`      | Queue a new idempotent workflow attempt      |
| `GET`    | `/{campaign_id}/summary`             | Return bounded status and failure counts     |
| `POST`   | `/{campaign_id}/targets`             | Add a validated draft target                 |
| `GET`    | `/{campaign_id}/targets`             | List target projections                      |
| `DELETE` | `/{campaign_id}/targets/{target_id}` | Delete an optimistically versioned draft URL |
| `GET`    | `/{campaign_id}/pages`               | List page and viewport-scan projections      |
| `GET`    | `/{campaign_id}/failures`            | Filter sanitized failure projections         |

The table paths are relative to the campaign prefix. Collection responses are bounded and paged.
Private object-storage keys are not exposed by page responses.

Start and retry require an idempotency key. Temporal receives only UUIDs and compact control data.
The workflow currently performs no crawling; it holds durable control state and accepts pause,
resume, and cancel signals.
