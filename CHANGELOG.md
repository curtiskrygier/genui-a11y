# Changelog

## 0.1.0 (unreleased)

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
