# Changelog

## 0.1.0 (unreleased)

- Scan a built folder, a URL, a sitemap or a crawl, or render components as fragments; axe-core, HTML_CodeSniffer and IBM Equal Access, plus static and Tab-walk checks.
- Score 0 to 100 with a grade, a layer breakdown, points lost per check and a fix order; a baseline ratchet; `--min-score` gate.
- Static checks count towards a page's score only when the page contains that kind of element.
- Experimental axe rules that carry a WCAG tag are switched on, derived from the installed axe (a tag-selected run skips them).
- Safety: Chromium sandbox on for remote hosts; every request checked against link-local and private ranges; resolved address pinned; MCP server limited to a scan root.
- Big scans: progress lines, results saved as pages finish, partial results on timeout, `scored N of M` headline, exit code 3 on low coverage (`--min-coverage`, `--allow-partial`).
- Local MCP server (`scan_start`, `scan_status`, `scan_result`, `explain_check`).
