# genui-a11y

**Accessibility regression checks for generated and template-built UI.** Render your components, audit them in the theme they will actually sit in, record what is already broken, and fail the build when something new breaks.

(a11y = accessibility.) Accessibility checks and balances for AI generated UI. The skill in this repo is called `a11y-generated-ui`.

**Status:** early (0.1.1), one author. It has been run on one 650-component catalogue, that catalogue's 593-page site, and two public W3C demo sites. Nobody outside the author has used it yet; [that is the open question](#try-it-and-tell-me).

[Quick start](#quick-start) · [Use with an agent](#use-with-an-agent-mcp) · [Options](#options-and-exit-codes) · [What it does not do](#what-it-does-not-do) · [How far to trust the score](#how-far-to-trust-the-score) · [Alternatives](#alternatives) · [Safety](#safety-defaults)

## Demo

Nine sample components, six of them with a planted defect. This is the real output of the quick start below, trimmed (a test, `tests/test_roast_r2.py`, checks that these lines still match what it prints):

```text
score 69/100  grade C (many automated findings)  9 of 9 page(s)/item(s) scored
   69 C   click_on_span  perc=100 oper=40 unde=100
   69 C   css_radio_tabs  perc=100 oper=40 unde=100 robu=100
   79 B   endless_spinner  perc=100 oper=40 unde=100 robu=100
   82 B   canvas_no_alt  perc=57 oper=100 unde=100
   82 B   unnamed_svg  perc=57 oper=100 unde=100
   84 B   low_contrast_text  perc=67 oper=100 unde=100
  100 A   ok_button  perc=100 oper=100 unde=100 robu=100
pages held down by a severe barrier: 3 (of which blocking, i.e. critical or keyboard: 2)  [a site with any blocking page cannot score above 84; 3 or more, or over a tenth of the pages, cannot score above 69]
fix order (assumes EVERY instance of a check is fixed; each step re-scores the whole site; ...):
  1. fix click_not_keyboard           69 -> 69 (C)
  2. fix hidden_input_widget          69 -> 92 (A)
  3. fix loop_no_reduced_motion       92 -> 94 (A)
  4. fix canvas_no_text_alt           94 -> 96 (A)
  5. fix svg_no_name                  96 -> 98 (A)
  6. fix color-contrast               98 -> 100 (A)
```

The sample `unlabelled_input` also scores 100 A: axe accepts a placeholder as a name. Run `--crosscheck` to see HTML_CodeSniffer and IBM Equal Access flag it.

A clean result means "no automated violations", never "accessible". Automated checks find only a share of real problems, and nothing here tests screen-reader output or involves disabled people.

## Why

When an agent or a template system generates your UI, one default can fail hundreds of pages at once (a pale accent colour, an unlabelled icon, a hidden radio button). Auditing the live site finds the symptoms; fixing them one page at a time never ends. This tool is built for that case:

- **Render each component on its own**, inside the host's real stylesheet and theme (light and dark). A bare white page overstates some failures and hides others.
- **Baseline what you already know about.** A new component must start clean and an old one may not get worse. Existing problems do not block the build; new ones do.
- **Rank the shared defects.** The fix order re-scores the whole site at each step, so the one change that clears 15 pages comes first.
- **Make the audit callable by an agent**, so a generation-and-repair loop can check its own output.

It also scans ordinary sites (a built folder, a running site, a sitemap). That works, but for a one-off check of a typical site, [Lighthouse or pa11y](#alternatives) are more mature and easier. Use this where components come from a generator.

## Quick start

**You need:** Node 20+, Python 3, and a Chromium or Chrome (`sudo apt install chromium` on Debian or Ubuntu; set `CHROMIUM=/path` if it is not at `/usr/bin/chromium`).

```bash
git clone https://github.com/curtiskrygier/genui-a11y.git
cd genui-a11y/skills/a11y-generated-ui/scripts
npm ci
python3 ratchet.py --items ../examples/items.json --score
```

You should see output like the demo above. If Chromium cannot start because its sandbox is unavailable (some containers and CI images), set `A11Y_NO_SANDBOX=1`, and only for content you trust.

Stuck? See [Troubleshooting](#troubleshooting).

## Usage

### Audit your own components (fragment mode)

You write one small adapter that turns your generator's output into `{name: html}`; [`examples/adapter_example.py`](skills/a11y-generated-ui/examples/adapter_example.py) and [`examples/adapter_json_schema.py`](skills/a11y-generated-ui/examples/adapter_json_schema.py) show two. Then:

```bash
python3 ratchet.py --items items.json --shell host.css --score          # score and fix order
python3 ratchet.py --items items.json --shell host.css --baseline b.json --update   # record today's findings
python3 ratchet.py --items items.json --shell host.css --baseline b.json            # fail on anything new or worse
```

`--shell` is your host stylesheet, so components read the same colour tokens they do in production.

### Scan a site

```bash
python3 ratchet.py --dir /path/to/dist --score                         # a built folder, served locally
python3 ratchet.py --url http://localhost:3000 --crawl --score         # a running site you own
python3 ratchet.py --sitemap https://example.com/sitemap.xml --confirm-permission --score
```

Use absolute paths, since relative ones resolve from the folder you run it in. Hosts other than localhost need `--confirm-permission`: scan only sites you own or have permission to test. Add `--path-scope` to stay under the start URL's folder.

### Gate a CI build

```bash
python3 ratchet.py --dir ./dist --score --json --min-score 80 > report.json
```

[`examples/ci/a11y-scan.yml`](skills/a11y-generated-ui/examples/ci/a11y-scan.yml) is a GitHub Actions template (not yet run on a third-party repository).

## Use with an agent (MCP)

[`scripts/mcp_server.py`](skills/a11y-generated-ui/scripts/mcp_server.py) is a local stdio MCP server using only the standard library. Its tools are `scan_start`, `scan_status`, `scan_result` and `explain_check`. Scans take minutes, so a scan is a job you poll.

```json
{ "mcpServers": { "a11y-scan": { "command": "python3", "args": ["/path/to/genui-a11y/skills/a11y-generated-ui/scripts/mcp_server.py"] } } }
```

As a Claude Code plugin the repo registers the server itself via [`.mcp.json`](.mcp.json). The server runs on your machine with your network access. Other hosts need `confirm_permission` in the call **and** `A11Y_ALLOW_REMOTE=1` set by whoever starts the server, because an agent can set the first itself. Agent-facing guidance is in [`SKILL.md`](skills/a11y-generated-ui/SKILL.md). A hosted public version is not part of this repo; it would need its own abuse and permission design.

## Options and exit codes

| Option | Default | What it does |
|---|---|---|
| `--items FILE`, `--dir DIR`, `--url URL`, `--urls FILE`, `--sitemap URL` | none (give one) | what to audit |
| `--score` / `--json` | off | score 0 to 100 with grade, layers, points lost per check, fix order / the same as JSON |
| `--min-score N` | none | exit 1 below N. Combined with `--baseline`, both run (the score, then the ratchet) and the worse exit code wins |
| `--min-coverage PCT`, `--allow-partial` | 90 | with `--min-score`: exit 3 if fewer than PCT of the requested pages could be audited |
| `--baseline FILE`, `--update` | none | the ratchet; a missing baseline is an error unless you pass `--update` |
| `--max-pages N` | 30 for `--crawl`; no cap for `--dir`, `--urls`, `--sitemap` | page cap; pages beyond a cap you set count as not audited |
| `--theme light\|dark` | light | colour scheme to request |
| `--tabwalk`, `--crosscheck` | off | separate modes (Tab key walk; HTML_CodeSniffer and IBM Equal Access cross-check); they print findings and set the exit code (1 on a finding; for `--crosscheck`, a finding two or more engines agree on; if the comparison itself crashes, `crosscheck_report.py` exits 2 and `ratchet.py --crosscheck` passes it on as 3, so a crash never looks like "the engines agree") but do not feed the score |
| `A11Y_JOB_TIMEOUT` | 7200 s | stop a run and score the pages finished so far |
| `A11Y_NAV_TIMEOUT`, `A11Y_AXE_TIMEOUT` | 40000, 25000 ms | per page until its DOM is parsed (a page past it is not audited; the settle wait below comes after it) and per axe run; raise for very heavy pages |
| `A11Y_IDLE_TIMEOUT`, `A11Y_SETTLE_MS` | 10000, 1500 ms | live URLs: after load, the page must be quiet (no request awaiting a response, no short timer pending, no DOM change) for `A11Y_SETTLE_MS` before it is audited, so content rendered after a slow fetch or a timer is seen; `A11Y_IDLE_TIMEOUT` bounds that wait, and a page that never settles is audited as it stands and named in the report. Content that appears later than the bound is not audited; raise it for slow apps, set `A11Y_SETTLE_MS=0` to skip the quiet window. Motion does not hold the wait: `style` changes, a node that has already changed 3 times (a ticking clock, a carousel) and a timer callback armed a second time stop counting, so an animated page settles in a few seconds. A long poll or a request that is never answered still waits the full bound; lower it for such sites. The crawl waits at most `A11Y_CRAWL_IDLE_TIMEOUT` (3000 ms) per page, because it only needs the links; the full wait is paid once, in the audit. The quiet window costs every page about `A11Y_SETTLE_MS` in the crawl and again in the audit (a 40-page crawl: about 180 s instead of 100 s); set `A11Y_SETTLE_MS=0` when no content renders late. Pages that never settled are listed in `pages_slow` in `--json` and the MCP report |
| `A11Y_NO_SANDBOX=1`, `A11Y_ALLOW_PRIVATE=1` | off | see [Safety](#safety-defaults) |

Exit codes: **0** ok, **1** score below `--min-score` (or new findings against a baseline), **3** the audit could not be trusted (too little coverage, items that could not be audited or were never reached, no pages, a missing baseline, a missing Chromium or `node_modules`, or an engine crash). A ratchet run cut short by `A11Y_JOB_TIMEOUT` exits 3 and `--update` refuses to write a baseline from it. Progress prints as pages finish and results are saved as they go, so a timeout keeps what finished and the headline says `PARTIAL`. Full details: [`SKILL.md`](skills/a11y-generated-ui/SKILL.md).

## What it does not do

- It does not test with a screen reader, a keyboard user or any disabled person. Automated checks find only a share of real problems, and that share varies by tool and content.
- It does not log in, follow single-page-app routes, or test states that need interaction beyond the Tab walk.
- The static checks are regexes over HTML. They miss some barriers (a listener added by script) and flag some non-barriers. A flag is a prompt to look; a clean result is not proof.
- It does not cover every WCAG 2.2 success criterion. Selecting A and AA tags in axe is not criterion-level coverage.
- The Tab walk reports heuristics (focus-style differences, a stop limit of 60). It does not prove a keyboard trap or a missing focus indicator. It does not report a clickable `<span>` or a CSS-only radio tab set that Tab never reaches (it prints how many composite widgets it never reached, not which are defective).
- Known limitations: stopping a run (timeout, or SIGTERM from the MCP server) finds the run's Chromium through `/proc`, so that cleanup works on Linux only; on macOS and Windows a Chromium that outlives its node process is not reaped (the run's temp dir is still removed); the engines were tested on Chromium 153 (the version in use is printed as `browser: ...` on stderr; other versions are untested); the MCP `scan_status` progress shows pages done, not a time estimate; the vetting proxy has no authentication (it listens on 127.0.0.1 only; it times out a connect after 10 s and an idle socket after 60 s, `A11Y_PROXY_CONNECT_TIMEOUT` and `A11Y_PROXY_IDLE_TIMEOUT`); in live mode Chromium's own background requests go through the proxy to public hosts.
- Performance, SEO and best-practice audits are out of scope.

## How far to trust the score

It is a scale this project made up. The four layer weights (35/35/15/15), the severity caps (59, 69 and 84) and the grade cut-offs (90/75/55/35) are judgement calls, not a standard, and the caps do most of the work: a site is held at 69 or 84 until enough pages are free of serious failures (a site with any page held down by a critical or keyboard barrier cannot reach an A however many clean pages it has, and three such pages, or more than a tenth of the site, hold it at 69), so a real improvement can show as no change, and one shared defect can move the whole site by 25 points. Use the score to track one site over time, and the **failing checks and the fix order** to decide work. Do not compare scores between sites, and do not quote one as a conformance claim. It is a secondary summary; the baseline and the fix order are the point.

Layers follow the WCAG principle of each rule's success criterion. An earlier version grouped by axe's own categories, which put 31 of the 68 rules it runs in a different layer from their principle; the site scores on every dataset below were identical under both, because the caps decide them, but the per-layer numbers moved (for example Perceivable 66 to 72 on the 8 October catalogue).

What it has been checked against (author-reported: the raw captures and comparison scripts are not in this repository, so these cannot be reproduced from it):

| | pages | Lighthouse accessibility (mean) | this score |
|---|---|---|---|
| W3C "before" demo (made inaccessible on purpose) | 20 | 78 | 69 |
| W3C "after" demo | 15 | 93.6 | 84 |
| the 650-component catalogue's site | 39 | 98.7 | 94 |

The two tools rank pages the same way (Spearman 0.94 across the W3C "before" pages, 0.79 across the catalogue's), and both score the fixed demo well above the broken one. They disagree on level; this is stricter by design. The W3C figures were measured on captured page source, because the live site answers Lighthouse with a redirect page.

That comparison also caught a real gap: Lighthouse flagged `td-has-header` on 14 pages where an earlier version of this scanner reported nothing, because axe marks some WCAG rules experimental and a run that selects rules by tag never executes them. The same site then scored 69 instead of 94 (one empty `<th>` in a shared template). The scanner now switches on every experimental rule that carries a WCAG tag ([lesson 14](skills/a11y-generated-ui/references/lessons.md)).

## Alternatives

| If you want | Use | Why not this |
|---|---|---|
| a quick check of a deployed page | Lighthouse, or the axe CLI | more established, nothing to set up |
| axe on components you already have in Storybook, failing CI | Storybook's accessibility addon | it is built for exactly that. This repo is for components that have no Storybook, because a generator produces them |
| multi-page runs with scripted actions | pa11y / pa11y-ci | handles interactions; this does not |
| guided manual and keyboard testing | Accessibility Insights | assisted keyboard review is more complete than the Tab walk here |
| content-author feedback in a CMS | Sa11y | different audience |

What this adds, narrowly: a small adapter to enter an audit from any generator, the host-theme render, a per-component baseline, and a fix order across the whole site. None of that is novel in itself; whether the combination helps anyone else is untested.

## Safety defaults

A scan loads someone's page and runs its scripts, so:

- The Chromium sandbox is **on**. Containers and some CI images cannot create it; there, set `A11Y_NO_SANDBOX=1`, and only for content you trust, because a page that escapes an unsandboxed Chromium runs as you.
- Every request the browser makes, including redirects and subresources, is checked. Link-local and cloud-metadata addresses are never reached. Private and special-use ranges (10/8, 172.16/12, 192.168/16, 100.64/10, multicast, fc00::/7, Teredo and others) are blocked unless you set `A11Y_ALLOW_PRIVATE=1`. Addresses are parsed to bytes, so every form that wraps an IPv4 address (IPv4-mapped, NAT64, 6to4) is judged by the IPv4 inside it.
- Loopback is reachable only at the exact origin being scanned: a local build on `127.0.0.1:8777` can load its own files, and a remote page cannot probe another local port. Every name the kernel routes to this machine counts as loopback, never as "private": `0.0.0.0`, `0`, `::`, `127.x` other than `127.0.0.1`, `[::ffff:127.0.0.1]`, so `A11Y_ALLOW_PRIVATE=1` does not open them. (`A11Y_ALLOW_PRIVATE=1` does open this machine's own LAN, docker and tailscale addresses, because they are private addresses: a service listening on all interfaces is then reachable from a scanned page.)
- Only http, https, data, blob and about URLs are allowed; file and ftp are blocked and service workers are bypassed. The `robots.txt` and sitemap fetches do not follow redirects.
- **What is routed through the check, and what is not.** The harness starts a small local proxy and launches Chromium with `--proxy-server` and `--proxy-bypass-list=<-loopback>`, so **every TCP connection the browser makes goes through it**: page loads, subresources, `fetch`, beacons, iframes, **WebSockets (ws and wss), SharedWorker, Worker and service-worker traffic**, and the browser's own requests. The proxy applies the rules above to each one and connects to the address it checked. A browser-level test (`tests/test_egress.py`) serves a probe page from a non-loopback address and from loopback; it tries image, fetch, beacon, iframe, WebSocket, EventSource, Worker, SharedWorker, WebRTC and WebTransport against another local port and asserts that neither a TCP nor a UDP listener there saw anything. **UDP is not proxied.** WebRTC (STUN/ICE) is shut off with `--webrtc-ip-handling-policy=disable_non_proxied_udp` (measured: a STUN probe sent 5 datagrams to a local UDP port without the flag and none with it), and `WebTransport` is removed from pages and iframes. **Not covered:** any other UDP a future browser feature might open, and a WebTransport opened from inside a Worker (no datagram reached a local port in the test with the harness flags, but that is a measurement on one Chromium build, not a guarantee). The harness checks only what the browser does: it does not firewall the machine.
- The proxy connects to the address the check resolved, for every host (starting page, redirects and subresources alike), so a hostile DNS server cannot answer the browser differently from the check. **For untrusted sites, scan from a container with no sensitive network access.**
- A folder scan serves only files that really live under the folder; a symlink pointing outside it is a 404.
- The MCP server scans only folders under its working directory (or `A11Y_SCAN_ROOT`), allows at most `A11Y_MAX_JOBS` (default 2) scans at once, enforces its argument bounds, kills a scan's whole process group on timeout, and negotiates the protocol version.

## Try it and tell me

I want to know whether this is useful beyond my own catalogue. If you maintain a generated or template-built UI (especially one that already uses Storybook's accessibility tests), try it for an afternoon and tell me, in an issue:

1. Could you connect your renderer without my help?
2. Did it catch a real regression your current workflow missed?
3. Did the baseline cut noise without hiding failures?
4. Did the fix order change what you fixed first?
5. Would you keep it in CI after the experiment?

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `no node_modules next to ...` | dependencies not installed | `cd skills/a11y-generated-ui/scripts && npm ci` |
| `Failed to launch the browser process` | no Chromium, or its sandbox cannot start | install Chromium, set `CHROMIUM=/path`; in a container add `A11Y_NO_SANDBOX=1` (trusted content only) |
| `resolves to a private address ... blocked` | the host is on a private network | `A11Y_ALLOW_PRIVATE=1`, for hosts you own |
| exit 3, `only N% of the requested pages were audited` | pages timed out or the run was stopped | raise `A11Y_NAV_TIMEOUT` / `A11Y_JOB_TIMEOUT`, scan in batches with `--urls`, or pass `--allow-partial` |
| exit 3, `no baseline at ...` | the baseline file does not exist | create it with `--update` |

## Credit and provenance

The scoring idea (a layered 0 to 100 score with grades, a list of failing checks with fix hints, a CI gate and a scan, fix, rescan loop) comes from [ora.ai](https://ora.ai), whose scanner scores how ready a domain is for AI agents ([methodology](https://ora.ai/methodology), [CLI](https://ora.ai/docs/cli)). This project is not affiliated with Ora and shares no code with it. What is mine: the accessibility checks (axe-core plus supplementary heuristics and a Tab walk), the four layers (each rule's WCAG principle) and their weights, the severity caps, the grade cut-offs, and the rule that a grade only ever claims "automated findings", never "accessible". `--min-score` is a common convention in audit tools.

The ratchet and the cross-engine method come from an audit of an AI-generated component catalogue in October 2026; see [`references/lessons.md`](skills/a11y-generated-ui/references/lessons.md). Two independent reviews (Gemini 3.8 Flash and a second reviewer) found real defects before release; the fixes are in [`CHANGELOG.md`](CHANGELOG.md).

## Licence

MIT: see [`LICENSE`](LICENSE). It installs, and does not bundle, these tools under their own licences:

| Tool | Licence |
|---|---|
| axe-core | MPL-2.0 |
| HTML_CodeSniffer | BSD-3-Clause |
| IBM Equal Access (accessibility-checker-engine) | Apache-2.0 |
| puppeteer-core | Apache-2.0 |
