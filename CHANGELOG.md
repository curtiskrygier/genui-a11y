# Changelog

## 0.1.1 (unreleased)

Release steps (maintainer):

1. Merge `fix/roast-r2`, then cut the tag **v0.1.1** at the merge commit. `examples/ci/a11y-scan.yml` pins `A11Y_REF: v0.1.1`, so the CI example cannot install until this tag exists.
2. Do **not** move or re-tag `v0.1.0`: it points at pre-hardening code. Say in its release notes that it is withdrawn and v0.1.1 replaces it.
3. Replace "(unreleased)" with the release date.

Fixes from the fifth roast review: live pages are audited once quiet (no request awaiting a response, no short timer pending, no DOM change for `A11Y_SETTLE_MS`, bounded by `A11Y_IDLE_TIMEOUT`, now 10 s), so content rendered after a slow fetch, chained fetches or a 2-5 s timer is audited; SIGTERM removes the run's temp dir; a sitemap is limited to its own host and port; `crosscheck_report.py` exits 2 on a crash; `--json` with `--baseline` carries a `ratchet` object; the Tab-walk count wording says it counts ARIA-role widgets only; the Linux-only `/proc` reaping is documented.

Fixes from the fourth roast review:

- **One slow request no longer holds the run.** The proxy tracks every socket, destroys the upstream when the browser side closes, drops a page's sockets before the next page and at exit, and times out a connect (10 s) and an idle socket (60 s). The engines exit explicitly. A page now loads until the DOM is parsed (`A11Y_NAV_TIMEOUT`, else "NOT AUDITED: Navigation timeout") and then gets `A11Y_IDLE_TIMEOUT` (15 s) to go network-idle; a page with an SSE stream or a request that is never answered is audited as it stands and listed as "never went idle". The report names pages that hit the deadline, and says "the engine did not exit" instead of a false STOPPED when every page was audited.
- A crawl that runs past `A11Y_JOB_TIMEOUT` exits 3 with a message, not a traceback. An MCP job timeout now SIGTERMs ratchet, which stops its node and Chromium; no process of the job survives. "the score below" is not printed in ratchet mode.
- The quick start prints no "blocked google.com" lines (Chromium background features are off; browser-internal blocks are not logged in fragment mode). Loopback origins are compared with the port spelled out, so a scan on :80 no longer opens :443 or the reverse. One version string (0.1.1) everywhere, with a test.

Fixes from the third roast review:

- **Egress (Critical):** `0.0.0.0/8` (`0.0.0.0`, `0`, ...) was classified as a private range, so with `A11Y_ALLOW_PRIVATE=1` a scanned page could reach a localhost port through it (fetch, img, WebSocket, SharedWorker; 8 hits in the roast). It is now loopback, like `::`, in `lib.mjs`, `ratchet.py` and `mcp_server.py`. `tests/test_egress.py` now probes 0.0.0.0, 0, `[::]`, `[::1]`, `[::ffff:127.0.0.1]`, 127.0.0.2 and numeric forms with `A11Y_ALLOW_PRIVATE=1` set.
- **CI template (Critical):** pins the tag `v0.1.1` instead of a placeholder; a test checks it parses and names the tag the CHANGELOG release steps cut.
- `--json` with `--baseline` keeps stdout a single JSON document (the ratchet text goes to stderr).
- A job timeout stops Chromium as well as node (Puppeteer starts Chromium in its own process group, so it is found by the run's own `--user-data-dir`); node also closes the browser on SIGTERM.
- `--crosscheck` exits 1 when two or more engines agree on a finding (3 if the comparison failed); `[::1]` needs no `--confirm-permission`; a sitemap scan keeps only the sitemap's own host (others are listed and skipped); `crosscheck.mjs` honours `A11Y_NAV_TIMEOUT`; the engine prints the Chromium version; the MCP `scan_status` reports `progress`; `--tabwalk` prints how many composite widgets Tab never reached; plugin descriptions no longer imply three engines score. Removed the stray `scripts/t.mjs`.

## 0.1.0 (superseded, see 0.1.1)

Fixes from the second roast review (branch `fix/roast-r2`):

- **Egress (Critical):** WebSockets and SharedWorker fetches were NOT blocked (the earlier "WebSockets blocked" claim was false in a real browser: `Network.setBlockedURLs` is ignored for ws, and worker traffic is invisible to page-level interception). All browser TCP traffic now goes through a local vetting proxy (`scripts/proxy.mjs`, `--proxy-server` plus `--proxy-bypass-list=<-loopback>`), which applies the address rules to every connection and connects to the address it checked (this also pins redirect and subresource hosts). WebRTC is disabled with `--webrtc-ip-handling-policy=disable_non_proxied_udp` and `WebTransport` is removed from pages. New browser-level test `tests/test_egress.py`. Not covered: other UDP, and WebTransport from inside a Worker (see README, Safety).
- **Ratchet fails closed (Critical):** items requested but never audited (a run stopped by `A11Y_JOB_TIMEOUT`) used to count as unchanged and the ratchet exited 0. It now exits 3, and `--update` refuses to write a baseline from a partial run.
- `--score` / `--min-score` together with `--baseline` used to skip the baseline silently; both now run and the worse exit code wins.
- Site score no longer dilutes: any page held down by a critical or keyboard barrier caps the site at 84 (B), three or more (or more than a tenth) at 69 (C). Two keyboard-barrier pages plus 60 clean ones scored 98 A before; now at most 84. The headline prints the barrier count. Scores of sites with no blocking page are unchanged.
- Environment and engine failures (no Chromium or `node_modules`, engine crash) exit 3, not 1. Wrong `--items` / `--shell` paths give one-line errors. `npm ci` everywhere. `crawl.mjs` honours `A11Y_NAV_TIMEOUT`.
- README demo regenerated from the real quick start; CI example no longer pins the stale `v0.1.0` tag.

Hardening after two independent reviews (Gemini 3.8 Flash and a second reviewer):

- Network guard: addresses are parsed to bytes (IPv4-mapped, NAT64, 6to4, Teredo, `::` and the other special forms are classified by what they contain; the old classifier missed the hex forms), loopback only at the exact scanned origins, scheme allowlist, WebSockets blocked, service workers bypassed, `robots.txt` and sitemap fetches do not follow redirects, sitemap host vetted and permission-checked before the fetch, Chromium sandbox on by default (`A11Y_NO_SANDBOX=1` to opt out).
- Layers now follow the WCAG principle of each rule's success criterion (audit.mjs records the `wcagNNN` tags; the layer is the lowest principle digit; no tag: axe-category fallback, reported). Re-scored on six datasets (W3C demo pair, the catalogue site at five points between 8 and 18 October): site scores unchanged, per-layer numbers moved.
- Static checks rewritten around parsed attributes: `role="img"` alone no longer counts as a name, `aria-hidden="false"` is not "hidden", canvas fallback text counts, `tabindex="-1"` clickables are flagged.
- Scoring: site rules follow the real severity cap, not the page score; a what-if fix weighs like a real pass; pages with nothing assessable are `not assessed`, not 100; axe `incomplete` results are reported under `needs_manual_review`.
- Coverage: a capped scan cannot report 100%; folder, URL-list and sitemap scans are exhaustive by default; `--min-score` checks coverage first (exit 3); page keys no longer collapse query variants or hosts.
- Baseline fails closed: a missing baseline needs `--update`, and items that could not be audited fail the run.
- Folder scans confine served files to the folder (symlinks pointing outside are a 404).
- MCP server: bounded arguments, at most `A11Y_MAX_JOBS` concurrent scans, process-group kill on timeout, protocol-version negotiation.
- MCP server: scans stop after 30 minutes unless the operator sets `A11Y_JOB_TIMEOUT`. CI example sets `A11Y_NO_SANDBOX` (the sandbox is now on by default). `<svg>` names may follow `<desc>`/`<defs>` before the `<title>`.
- Docs: modes and defaults spelled out, comparison corrected, detection-rate claim softened and cited, review-found limitations listed.

- Scan a built folder, a URL, a sitemap or a crawl, or render components as fragments; axe-core, HTML_CodeSniffer and IBM Equal Access, plus static and Tab-walk checks.
- Score 0 to 100 with a grade, a layer breakdown, points lost per check and a fix order; a baseline ratchet; `--min-score` gate.
- Static checks count towards a page's score only when the page contains that kind of element.
- Experimental axe rules that carry a WCAG tag are switched on, derived from the installed axe (a tag-selected run skips them).
- Safety: Chromium sandbox on for remote hosts; every request checked against link-local and private ranges; resolved address pinned; MCP server limited to a scan root.
- Big scans: progress lines, results saved as pages finish, partial results on timeout, `scored N of M` headline, exit code 3 on low coverage (`--min-coverage`, `--allow-partial`).
- Local MCP server (`scan_start`, `scan_status`, `scan_result`, `explain_check`).
