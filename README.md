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

## Status

Early (0.1.0). Dependencies are pinned (`scripts/package-lock.json`), there is a CI example (`examples/ci/a11y-scan.yml`), and the dark-mode options for live sites are documented in `SKILL.md`. Developed on one 650-component catalog; site mode has been tried only on local static pages. No login, no single-page-app routes, no screen-reader testing.

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
