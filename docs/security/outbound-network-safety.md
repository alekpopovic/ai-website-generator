# Outbound URL and network safety

`platform_clients.network_safety` is the mandatory boundary for crawler seeds, Scrapy requests,
Playwright navigation and subresources, redirects, asset inspection, webhooks, and publishing targets.
It performs no allow-on-error fallback.

## Required integration sequence

1. Create the consumer adapter and a context containing the activity/request identifiers. Only a
   control-plane command that has already enforced administrator authorization may set
   `administrator_port_access`; the port must also exist in the configured administrator allowlist.
2. Call `initial()` before scheduling an outbound request. This resolves and validates every current A
   and AAAA answer. A mixed public/private answer blocks the complete hostname.
3. Disable framework-level automatic redirects. Call `redirect()` for each `Location`, including
   relative locations. Each hop receives a new DNS validation and consumes the redirect budget.
4. Call `before_connection()` as close to socket creation as the framework permits. A changed answer
   set is `dns_rebinding`. Native connectors should connect to one of the approved IPs, preserve the
   hostname for TLS SNI/certificate verification, and pass the actual peer IP back for comparison.
5. Validate response headers before downloading or rendering. Only `text/html` and
   `application/xhtml+xml` proceed to expensive work. Stream the decoded body through the bounded body
   iterator so compressed responses cannot become decompression bombs after client decoding.
6. Apply the typed connect, read, total, and browser-navigation timeout values. Persist sanitized
   `network.request_blocked` events; never log URL credentials or query strings.

The default policy allows ports 80 and 443, five redirects, 64 KiB of headers, and 5 MiB of decoded
body data. Limits are ceilings, not download targets. Consumers may use tighter limits.

## Browser-level residual risks

Playwright request routing is important but is not a complete network sandbox. Chromium may maintain
its own DNS cache and connection pool; the browser API does not reliably expose every connected peer
IP. Navigation can trigger speculative preconnect, redirects, frames, workers, service workers,
WebSockets, WebTransport, WebRTC/STUN, downloads, `data:`/`blob:` indirection, DNS prefetch, and QUIC.
New browser features can introduce request paths before interception libraries expose controls.

Browser workers therefore must use a fresh isolated browser context, disable service workers,
downloads, extensions, WebRTC, QUIC, speculative networking, proxy auto-discovery, and background
network services where supported. Intercept every document, frame, worker, script, stylesheet, font,
image, media, XHR, fetch, EventSource, and WebSocket URL. Reject unhandled schemes and close contexts
after each bounded job. Never grant browser processes platform credentials or mount secret-bearing
files.

The implemented browser worker applies these context and routing controls, uses a capability-free,
read-only `pwuser` container, and bounds Chromium contexts, memory, PIDs, screenshots, HTML, and time.
Compose network separation is a development topology rather than a production egress firewall. A
deployment is incomplete until scanner policy permits only DNS plus validated public TCP 80/443 and
denies backend, cluster, metadata, RFC1918, link-local, and other private address ranges independently
of Chromium interception.

## Production firewall and proxy policy

Application checks must be backed by a fail-closed egress layer:

- place crawler and browser workers in dedicated subnets/namespaces with no route to backend, control
  plane, node, container-runtime, Kubernetes service, or cloud control networks;
- deny IPv4 and IPv6 loopback, RFC1918, link-local, carrier-grade NAT, multicast, reserved,
  documentation, unspecified, and cloud metadata ranges at the firewall regardless of destination
  port;
- allow DNS only to a controlled resolver that blocks internal zones and logs answer changes; block
  direct UDP/TCP 53 and encrypted-DNS bypass to other destinations;
- prefer an authenticated egress proxy that resolves hostnames itself, checks all answers, pins the
  selected IP, enforces TLS verification, response limits, destination ports, and redirect policy;
- default-deny outbound ports, UDP, QUIC, STUN/TURN, and raw sockets. Open 80/443 TCP only for scanner
  identities; maintain exceptional ports as reviewed, expiring administrator policy;
- do not use host networking. Run non-root with dropped capabilities, read-only filesystems, seccomp,
  AppArmor/SELinux, resource quotas, and short-lived workload identities;
- alert on blocked metadata/internal destinations, mixed-scope DNS, answer-set changes, peer mismatch,
  unexpected ports, and repeated policy failures.

Kubernetes `NetworkPolicy` alone usually cannot express hostname policy and may not cover traffic
before the CNI is active. Cloud security groups alone cannot detect DNS rebinding. Use layered CNI or
host firewall rules plus an egress proxy, and test both IPv4 and IPv6 paths continuously.
