# Browser Worker

Runs isolated Playwright rendering activities for approved URLs discovered by the crawler. It captures bounded screenshots and structural metadata while enforcing network interception, SSRF protection, resource limits, and browser sandboxing.

Every navigation, frame, worker, and subresource must pass through `PlaywrightRequestSafety`.
Application interception is backed by a default-deny worker firewall or egress proxy because Chromium
does not expose reliable peer-address pinning for all browser traffic.
