---
name: a11y-generated-ui
description: >-
  Audit and ratchet the accessibility of AI-generated or schema-driven UI
  (a component catalog an agent fills in, a declarative-UI renderer, MCP app
  views). Renders each component, runs axe-core plus HTML_CodeSniffer and IBM
  Equal Access in headless Chromium inside the real host theme, adds the
  static and keyboard checks axe misses, and keeps a baseline so new
  components must start clean and old ones cannot get worse. Use when asked to
  "audit accessibility", "check WCAG" or "stop a11y regressing" on generated
  UI, or when adding components to a catalog. Not a substitute for a screen
  reader or disabled-user testing.
license: MIT
compatibility: Needs Python 3, Node 22.23.4+, 24.22.1+ or 26.12.1+ (older is refused) and a Chromium; npm ci in scripts/ once.
---

# a11y-generated-ui

A method and a small harness for one problem: UI that an agent generates tends to inherit the agent's habits, and nobody revisits the rigour an enterprise team would apply. Origin: an audit of a 650-component catalog (Oct 2026). Read `references/lessons.md` before changing the method.

## What a clean result means

"No automated violations". Never "accessible". Automated engines find only a share of real WCAG issues, and how large a share depends on the tool and the content (Deque's 2021 study of 13,000+ pages found 57% of issue *occurrences*, which is not the same as 57% of criteria; this project's own rate is unmeasured). They say nothing about screen-reader output or how a real person uses the thing. Say so in every report you write, and say whether a screen-reader and keyboard pass has been done.

## Which mode

| You have | Use |
|---|---|
| a generator that makes components or fragments | fragment mode: `--items items.json` (write the adapter once) |
| a built site folder | `--dir ./dist` |
| a running site, local or one you own | `--url ... --crawl` |
| a list of pages | `--urls pages.txt` or `--sitemap URL` |
| an agent that should run scans itself | the local MCP server (below) |

## The method

1. **Standard.** WCAG 2.2, levels A and AA.
2. **Render every component** with the real renderer into `items.json` (`{name: html}`). The only code you write is this adapter (`examples/adapter_example.py`). Put the example payloads through the same renderer production uses.
3. **Audit in the real host theme.** Pass the host stylesheet with `--shell`. A bare white page overstates failures, because components read colours from host tokens such as `--muted`. Run light and dark, with a separate baseline each. Tell the scanner how the host goes dark: `A11Y_DARK_CLASS` (a body class, fragment mode), `A11Y_DARK_ATTR=data-theme=dark` (an attribute on the root) or `A11Y_DARK_STORAGE=a2ui-theme=dark` (a localStorage key the page reads), the last two for live sites. If light and dark results are identical, suspect the harness: the first dark scans of a real site never went dark.
4. **Add supplementary heuristics** (checks axe does not make, or makes differently) (static flags in `scripts/ratchet.py`): `click_not_keyboard`, `hidden_input_widget` (CSS radio trick), `svg_no_name`, `canvas_no_text_alt`, `loop_no_reduced_motion`. Axe missed the first two on the original audit and IBM caught them.
5. **Cross-check engines** (`--crosscheck`). One engine is one opinion. Where two or more agree, it is very likely real; where one flags it, look by hand.
6. **Keyboard walk** (`--tabwalk`). Tabs through each component and reads the browser's accessibility tree at each stop: unnamed stops, repeated names, no visible focus, traps, controls Tab never reaches. It is the information a screen reader is built from, not a screen reader.
7. **Ratchet.** `--baseline file --update` records exactly which items are not yet clean. Afterwards a new item must start with no findings, and a baselined item may not get worse. Fixed items are reported so the gain can be locked in.
8. **Fix at the source.** Defaults and shared tokens first (they move the most items), then per-component. Re-run the ratchet after each batch.

## Commands

```
cd scripts && npm ci                    # once: axe-core, HTML_CodeSniffer, IBM Equal Access, puppeteer-core (needs Chromium; set CHROMIUM=/path if not /usr/bin/chromium)
python3 ratchet.py --items items.json --shell host.css --baseline baseline.json            # ratchet
python3 ratchet.py --items items.json --shell host.css --baseline baseline.json --update   # lock in a fixing batch
python3 ratchet.py --items items.json --shell host.css --theme dark --baseline baseline-dark.json
python3 ratchet.py --items items.json --report | --static | --tabwalk | --crosscheck
```

### Score, grade and a CI gate

`--score` turns a scan into a number a person can act on: 0 to 100, a grade, a layer breakdown and the failing checks with a fix link. The idea of a layered score with a CI gate for a scan-fix-rescan loop comes from ora.ai (see the README); the layers, weights, caps and cut-offs here are our own.

```
python3 ratchet.py --url http://localhost:3000 --crawl --score
python3 ratchet.py --dir ./dist --score --min-score 70      # exits 1 below 70, so a plain CI step fails the build
python3 ratchet.py --dir ./dist --score --json              # full report for scripting
```

- Four layers, weighted: perceivable 35, operable 35, understandable 15, robust 15. A check's layer is the WCAG principle of its success criterion (axe's `wcag131` tag: the first digit, 1 perceivable, 2 operable, 3 understandable, 4 robust). A rule tagged under criteria of more than one principle (`area-alt`, `link-name`: 2.4.4 and 4.1.2) takes the lowest-numbered one. A rule with no criterion tag falls back to its axe category and is listed under `layer_fallback_rules` in the report. The weights are a judgement: with this mapping Understandable holds few rules, so its 15 points mostly sit unused on pages without forms or `lang` problems (a layer with nothing applicable is left out and the others are rescaled). Each layer is the weight of the checks that passed over the weight of those that applied; a failed check weighs by axe impact. Five static checks (keyboard, SVG and canvas names, endless motion) are added to the matching layers.
- **Severity caps stop many passing checks hiding a barrier:** a critical failure or a keyboard barrier caps the page at 69, a serious failure at 84, and three or more of either at 59. Site rules count pages by what held them down: more than a tenth of pages (or three or more pages) held by a critical or keyboard barrier cap the site at 69; any one such page caps it at 84, so adding clean pages cannot lift a site with a real barrier to an A; more than a quarter of pages held by a serious failure or worse cap it at 84. The headline prints how many pages are held down by a severe barrier.
- Grades: A 90+, B 75+, C 55+, D 35+, F below; there is no A+. The labels always say "automated findings". Never present a grade as "accessible" or "compliant", and print the banner the report ends with: automated checks find only a share of real issues, and keyboard order, screen-reader output and content are not scored.
- The tab-walk is not part of the score yet.

### As an MCP tool

`scripts/mcp_server.py` is a local stdio MCP server (standard library only) so an agent can run scans itself. Installed as a Claude Code plugin it registers as `a11y-scan` (see `.mcp.json`); elsewhere run `python3 scripts/mcp_server.py` as a stdio server. Run `npm ci` in `scripts/` first.

Tools: `scan_start` (a URL or a built folder, with `crawl`, `max_pages`, `depth`, `theme`, `confirm_permission`) returns a job id at once; `scan_status`; `scan_result` (score, grade, layers, worst pages, failing checks, the coverage note); `explain_check`. Scans take minutes, hence the job. Localhost and local folders scan freely; any other host needs `confirm_permission` in the call and `A11Y_ALLOW_REMOTE=1` in the environment of whoever starts the server (an agent cannot grant itself that), and link-local and cloud-metadata addresses are never scanned. When you report a result, include its coverage note.

### In CI

`examples/ci/a11y-scan.yml` is a GitHub Actions workflow: build, scan the output folder, fail below `--min-score`, and keep the JSON report. `scripts/package-lock.json` pins the engines, so `npm ci` gives the same versions each run.

### Scanning a site

Point it at pages instead of fragments. The real page loads with its own CSS and scripts; the dark theme is requested with `prefers-color-scheme`. Every live mode takes `--report`, `--baseline`, `--theme`, `--tabwalk` and `--crosscheck` like the fragment mode.

```
python3 ratchet.py --dir ./dist --report                                   # a built site: served on localhost, every .html page audited (no page cap unless you pass --max-pages)
python3 ratchet.py --url http://localhost:3000 --crawl --max-pages 30 --depth 2
python3 ratchet.py --url https://example.com/docs/v2/ --crawl --path-scope --confirm-permission   # stay under /docs/v2/ only
python3 ratchet.py --sitemap https://example.com/sitemap.xml --confirm-permission
python3 ratchet.py --urls pages.txt --confirm-permission                   # one URL per line
```

- **Permission.** A host other than localhost is refused unless you pass `--confirm-permission`: scan only sites you own or have permission to test.
- **Scope.** By default a crawl follows any same-origin link. Use `--path-scope` to stay under the start URL's folder, or two crawls of neighbouring sections will overlap and any comparison between them is meaningless.
- **Politeness.** The crawler stays on one origin, follows robots.txt (`User-agent: *` Disallow lines), waits `--delay` ms between pages, and stops at `--max-pages` and `--depth`.
- **Limits.** Pages behind a login, pages that need interaction or live data to show their content, and single-page-app routes that are not reachable by link are not covered. A whole page is scored, so expect shared header and footer findings to repeat on every page: fix them once, at the source.

`--static` needs no browser and runs in seconds, so it is the one to put in fast CI. The full audit takes minutes on hundreds of components.

## Rules from the original audit (details in references/lessons.md)

- Audit in the host's real theme tokens, not a bare page.
- A blind global colour swap makes things worse: a component that paints its own surface must keep its own text colours; only components that inherit the host surface inherit the host text colour.
- Freeze animations at their end state before running axe, or contrast results flip from run to run.
- A single default (such as an accent colour a hair under 4.5:1) can run through hundreds of components. Fix defaults first.
- A required accessible name belongs in the payload contract: a renderer cannot invent a good label for a field the agent omitted.
- Respect the user's own settings as the floor: reduced motion, contrast, text size, keyboard, screen reader. They always win.

## When the UI is driven by an agent

If a person has to discover, review, approve, monitor or cancel what an agent does, also read `references/agent-ui-checklist.md`. It is a draft checklist drawn from a live standards discussion (WebMCP issues 272 and 277), not settled rules.

## Reporting

Report: counts before and after with the date, what each count measures (items with an axe violation, failing contrast nodes), what was fixed at the source, what is still open, and the caveat above. Do not call anything "accessible" or "compliant".

## Safety

The scanner opens pages in a real browser, so it runs their JavaScript. Scan untrusted sites from a container or a machine with no sensitive network access. It refuses anything but localhost without `--confirm-permission`, never reads link-local or cloud-metadata addresses (every browser connection, WebSockets and workers included, goes through a local proxy that checks the host and connects to the address it resolved; UDP is not proxied, WebRTC is disabled and WebTransport removed: see the README's Safety section), and follows robots.txt. The MCP server adds a second switch an agent cannot flip: remote scanning needs `A11Y_ALLOW_REMOTE=1` in the environment of whoever starts the server.

## What this does NOT do

No screen-reader testing, no testing with disabled people, no interactive states (open menus, dialogs, invalid forms, live regions are only seen as the page loads), no check of many WCAG 2.2 criteria that engines cannot test (for example focus not obscured, dragging alternatives, accessible authentication), no reflow or zoom checks, no cognitive-accessibility review, no content review (alt text quality, reading level). In fragment mode it runs on rendered HTML with the network blocked, so anything that depends on live data or interaction state is only checked in its default state. In site mode it sees what a fresh, signed-out visitor sees.

## Options and environment

| Setting | What it does |
|---|---|
| `--min-score N` | exit 1 below N; exit 3 when fewer than `--min-coverage` percent (default 90) of the requested pages could be audited, unless `--allow-partial` |
| `A11Y_JOB_TIMEOUT` | seconds before a run is stopped and its finished pages scored (default 7200) |
| `A11Y_NAV_TIMEOUT`, `A11Y_AXE_TIMEOUT` | milliseconds per page until its DOM is parsed (a page past it is not audited; the settle wait comes after it) and per axe run (defaults 40000, 25000); raise for very heavy pages |
| `A11Y_IDLE_TIMEOUT`, `A11Y_SETTLE_MS` | milliseconds (defaults 10000, 1500): live URLs are audited once quiet (no request awaiting a response, no short timer pending, no DOM change) for `A11Y_SETTLE_MS`, waiting at most `A11Y_IDLE_TIMEOUT`; a page that never settles is audited as it stands and named. Content later than the bound is not audited. Activity is waited on for a while, content for longer. Activity (an open WebSocket, EventSource or Worker, a `setInterval` or a re-armed timer, a `requestAnimationFrame` loop, an attribute change such as `style` or `class` on an element that has already changed 3 times) holds the wait for at most `A11Y_ACTIVITY_MS` (6000 ms) after load: an AI answer that streams in, a job-status poll or an intro animation that ends in a reveal within that time is waited for; an endless carousel or animation costs about 6 s, not the full bound. Content always counts, up to the full bound: an element or text that is added or changed (also inside shadow roots), a fetch whose body is still arriving, a pending one-shot timer or `scheduler.postTask`. So a page whose content keeps changing (a ticking clock, a live feed) waits the full bound and is listed in `pages_slow` (in `--json` and the MCP report); lower `A11Y_IDLE_TIMEOUT` for such sites (that also stops the wait for timers longer than the new bound). Content that arrives after a silent stream or poll longer than `A11Y_ACTIVITY_MS` is not audited: raise it for slow AI answers. Same-origin and cross-origin iframes are audited with the page. The crawl waits for new elements only, so activity and text cost the full wait once, in the audit. The quiet window costs every page about `A11Y_SETTLE_MS` in the crawl and again in the audit; set `A11Y_SETTLE_MS=0` only when no content renders late |
| `A11Y_NO_SANDBOX=1` | run Chromium without its sandbox (containers and CI images that cannot create it); the sandbox is on by default, so use this only for content you trust |
| `A11Y_MAX_JOBS` | MCP server only: concurrent scans allowed (default 2) |
| `A11Y_ALLOW_PRIVATE=1` | allow private address ranges (your own internal hosts); link-local and metadata addresses are never allowed |
| `A11Y_ALLOW_REMOTE=1` | MCP server only: allow hosts other than localhost (a human decision) |
| `A11Y_SCAN_ROOT` | MCP server only: the folder local scans may read (default: its working directory) |

## What each mode does, and how they interact

- **Default scan** (`--items`, `--dir`, `--url`, `--urls`, `--sitemap`): axe-core plus the static heuristics, one theme (`--theme light` unless you ask for dark). Axe's `incomplete` results (things it could not decide) are kept in the report under `needs_manual_review`, not scored.
- **`--tabwalk`** and **`--crosscheck`** are separate modes that return early. Their findings are printed and set the exit code, but do **not** feed the score or the baseline.
- **`--max-pages`**: crawls default to 30; `--dir`, `--urls` and `--sitemap` are exhaustive unless you pass it. Pages beyond a cap you set count as not audited, so a capped scan cannot report full coverage.
- **Pages with nothing assessable** are reported as `pages_not_assessed`, not as a perfect 100.
- **Baseline** (`--baseline FILE`): a missing file is an error unless you pass `--update` (a typo in the path must not silently become the baseline); items that could not be audited fail the run (exit 3) instead of counting as fixed. Static findings are per item (present or not), so a second instance of a defect already in the baseline does not register.
- **`--audit-out FILE`** writes the raw audit data (for offline rescoring). **`--only`** limits tabwalk/crosscheck to named items.
- **Keys:** pages are named by path plus query on a single host, and by full URL when hosts are mixed.
- **Tab walk** reports heuristics (focus-style differences, a stop limit of 60, a return to the first stop) as prompts for a person to check; it does not prove a trap or a missing focus indicator.

