# genui-a11y: accessibility checks for AI-generated UI

Accessibility checks and balances for AI generated UI. (a11y = accessibility.) The skill in this repo is `a11y-generated-ui`: a skill and small harness for auditing the accessibility of AI-generated or schema-driven UI, and for keeping it from regressing.

You render each component to an HTML fragment, and the harness:

- runs axe-core, then HTML_CodeSniffer and IBM Equal Access, in headless Chromium, inside the host's real theme (light and dark);
- adds static checks axe cannot make (clickable elements with no keyboard route, the CSS radio trick, unnamed SVGs and canvases, endless animation with no reduced-motion rule);
- scores the result 0 to 100 with a grade, a layer breakdown and the failing checks, and can fail a CI step below a minimum (`--score --min-score 70`);
- walks each component with the Tab key and reads the browser's accessibility tree;
- records a baseline, so a new component must start clean and an old one may not get worse.

**A clean result means "no automated violations", never "accessible".** There is no screen-reader or disabled-user testing here. See `skills/a11y-generated-ui/SKILL.md`.

## Use

```
cd skills/a11y-generated-ui/scripts && npm install      # needs Node 20+ and a Chromium (set CHROMIUM=/path if not /usr/bin/chromium)
python3 ratchet.py --items ../examples/items.json --report
```

`examples/adapter_example.py` shows the only part you write for fragments: turning your generator's output into `{name: html}`.

To scan a site instead: `python3 ratchet.py --dir ./dist --report`, or `--url http://localhost:3000 --crawl`. Add `--path-scope` to stay under the start URL's folder. Hosts other than localhost need `--confirm-permission`: scan only sites you own or have permission to test.

## As an MCP tool

`skills/a11y-generated-ui/scripts/mcp_server.py` is a local stdio MCP server (standard library only): `scan_start`, `scan_status`, `scan_result`, `explain_check`. As a Claude Code plugin it registers itself via `.mcp.json`. It runs on your machine with your network access: other hosts need `confirm_permission` in the call and `A11Y_ALLOW_REMOTE=1` set by whoever starts the server, and link-local addresses are never scanned. A hosted, public version would need its own abuse and permission design and is not part of this.

## Layout

- `.claude-plugin/plugin.json`: Claude Code plugin manifest. `.mcp.json`: registers the local MCP server. `plugin.json`: Agent Plugins manifest.
- `skills/a11y-generated-ui/SKILL.md`: the Agent Skill (method, commands, limits).
- `skills/a11y-generated-ui/references/`: lessons from the original audit; the end-to-end pattern; a build runbook; a draft checklist for agent-driven UI.

## Why this and not axe CLI, pa11y or Lighthouse

If you only need a quick check of a deployed page, use Lighthouse or the axe CLI; they are more established and need less setup. This project is for a narrower case:

| | axe CLI | pa11y / pa11y-ci | Lighthouse (CI) | this |
|---|---|---|---|---|
| Needs a running page | yes | yes | yes | no: fragment mode renders each component on its own |
| Engines | axe | HTML_CodeSniffer or axe | a subset of axe audits | axe, HTML_CodeSniffer and IBM Equal Access, plus static and Tab-walk checks |
| Remembers what you already know about | no | thresholds | budgets and assertions | a per-component baseline: new components start clean, old ones cannot get worse |
| Tells you what to fix first | no | no | lists failed audits | a fix order that re-scores the whole site at each step |
| Keyboard and reduced motion | no | no | not scored | static checks for clickable spans, hidden radios and endless animation, and a Tab walk |

What it does not do: performance, SEO, login flows, single-page-app routing, or anything a screen reader or a disabled user would tell you.

## How far to trust the score

It is a scale this project made up. The four layer weights (35/35/15/15), the severity caps (59, 69 and 84) and the grade cut-offs (90/75/55/35) are judgement calls, not a standard, and the caps do most of the work: a site is held at 69 or 84 until enough pages are free of serious failures, so a real improvement can show as no change, and one shared defect can move the whole site by 25 points. Use the score to track one site over time and the **failing checks and the fix order** to decide work; do not compare scores between sites or quote one as a conformance claim.

What it has been checked against, on one catalogue and two public demo pages:

| | pages | Lighthouse accessibility (mean) | this score |
|---|---|---|---|
| W3C "before" demo (made inaccessible on purpose) | 20 | 78 | 69 |
| W3C "after" demo | 15 | 93.6 | 84 |
| the 650-component catalogue's site | 39 | 98.7 | 94 |

The two tools rank pages the same way (Spearman 0.94 across the W3C "before" pages, 0.79 across the catalogue's), and both score the fixed demo well above the broken one. They disagree on level: this is stricter by design. The W3C figures were measured on captured page source, because the live site answers Lighthouse with a redirect page.

The comparison also caught a real gap: Lighthouse flagged `td-has-header` on 14 pages where an earlier version of this scanner reported nothing, because axe marks some WCAG rules experimental and a tag-selected run never executes them. The same site then scored 69 instead of 94 (one empty `<th>` in a shared template). The scanner now switches on every experimental rule that carries a WCAG tag (`references/lessons.md`, lesson 14).

## Safety defaults

A scan loads someone's page and runs its scripts, so:

- The Chromium sandbox is **on** for remote hosts. It is off only for content you control (fragments, a local folder, localhost), or when you set `A11Y_NO_SANDBOX=1` yourself (some containers and CI images cannot create it).
- Every request the browser makes, including redirects and subresources, is checked: link-local and cloud-metadata addresses are never reached, private ranges (10/8, 172.16/12, 192.168/16, 100.64/10, fc00::/7) are blocked unless you set `A11Y_ALLOW_PRIVATE=1`, and a public name that resolves to loopback is blocked. The address checked for each target host is the address pinned for the browser.
- Not covered: a name that changes its answer between the check and the request for a *subresource* host. For untrusted sites, scan from a container with no sensitive network access.
- The MCP server scans only folders under its working directory (or `A11Y_SCAN_ROOT`), and remote hosts only if whoever starts it sets `A11Y_ALLOW_REMOTE=1`.

## Big scans, partial results and exit codes

Progress is printed as pages finish (`[12/593] /path`). Results are saved as they go, so a run that hits `A11Y_JOB_TIMEOUT` (seconds, default 7200) keeps the pages it finished and says `PARTIAL`. The headline reads `scored N of M`, pages that errored (for example a navigation timeout) are listed as `NOT AUDITED`, and with `--min-score` the exit code is **1** below the minimum, **3** when fewer than `--min-coverage` percent (default 90) of the requested pages could be audited (override with `--allow-partial`). Very heavy pages need `A11Y_NAV_TIMEOUT` and `A11Y_AXE_TIMEOUT` (milliseconds, defaults 40000 and 25000), or scan them in small batches with `--urls`.

## Status

Early (0.1.0). Dependencies are pinned (`scripts/package-lock.json`), and there is a CI example (`examples/ci/a11y-scan.yml`, not yet run on a real repository) and CI for this repo.

What it has actually been run on, honestly: one 650-component catalogue (fragment mode, light and dark), that catalogue's public site (a sampled live crawl and a full scan of its 593 built pages), and the two W3C demo sites. The second adapter, `examples/adapter_json_schema.py`, is a small worked example, not a second real system. No login, no single-page-app routes, no screen-reader testing.

## Provenance and credit

The scoring idea, a layered 0 to 100 score with grades, a list of failing checks with fix hints, a CI gate (`--min-score`) and a scan, fix, rescan loop, comes from [ora.ai](https://ora.ai), whose scanner scores how ready a domain is for AI agents ([methodology](https://ora.ai/methodology), [CLI](https://ora.ai/docs/cli)). This project is not affiliated with Ora and shares no code with it. What is ours: the accessibility checks (axe-core plus static and keyboard checks), the four WCAG-based layers and their weights, the severity caps, the grade cut-offs, and the rule that a grade only ever claims "automated findings", never "accessible". `--min-score` is a common convention in audit tools.

The ratchet and the cross-engine method come from an audit of an AI-generated component catalog (October 2026); see `skills/a11y-generated-ui/references/lessons.md`.

## Licences

This project is MIT (see `LICENSE`). It installs, and does not bundle, these tools under their own licences:

| Tool | Licence |
|---|---|
| axe-core | MPL-2.0 |
| HTML_CodeSniffer | BSD-3-Clause |
| IBM Equal Access (accessibility-checker-engine) | Apache-2.0 |
| puppeteer-core | Apache-2.0 |
