# Build runbook: from an audit to a hosted scanner

How the scanner was built, in the order that worked, with the reason for each step and what went wrong. Written so the same sequence can be repeated for another tool, not only this one.

## 0. Principles that decided the order

- **Measure before you fix, and keep the measurement.** The audit became a ratchet before any fixing started.
- **One scorer, two languages.** The local tool (Python) and the hosted worker (JavaScript) must give the same score. A parity test, not care, keeps them equal.
- **Prove the risky thing first.** Whether the hosted browser could run our checks was the only real unknown, so it was tested with a small throw-away Worker before anything else was built.
- **Private first.** One owner token, no public tier. Abuse and permission design is deferred, not forgotten.
- **Say what the score does not cover, every time.**

## 1. Audit the thing you own (the original audit)

Render every component, run axe-core in the host's real theme (light and dark), add static checks axe cannot make, cross-check with two more engines, keep a baseline. See `lessons.md`.

## 2. Make it a skill with a stable input

Input contract: `{name: html}` fragments plus an optional host stylesheet. The only code a new user writes is the adapter. Add live modes later without changing the contract (`--dir`, `--url`, `--sitemap`).

## 3. Score it

Layers (perceivable 35, operable 35, understandable 15, robust 15), failures weighted by impact, static checks added to the matching layer, severity caps, grades that only ever say "automated findings", no A+. Print the coverage note on every report. Credit the idea (ora.ai) and keep the checks, weights, caps and wording our own.

## 4. Show where the points went

Per check: points lost, and the score gain if that check alone were fixed. Then a greedy fix order that re-scores the whole site at each step. Needed because the severity caps flatten scores: fixing one check can show +0 while another check still holds the page down.

## 5. Validate against a known answer

- **A known-bad site against its fixed twin.** W3C's Before and After Demonstration: before scored 65 (C), after 84 (B), and the findings matched the barriers the demo documents.
- **Scope the crawl.** The first attempt followed links between "before" and "after" and gave both the same score. `--path-scope` fixed it. Any comparison needs the two crawls kept apart.
- **Your own site last.** It found real issues (brand accent contrast, links distinguished only by colour).
- **Theme switching differs per site.** Three dark scans in a row were identical because the site stores its theme in `localStorage`, not in the browser's colour-scheme setting. `A11Y_DARK_ATTR` and `A11Y_DARK_STORAGE` exist because of this. If light and dark results are identical, suspect the harness, not the site.
- **Report what was not audited.** A page whose axe run timed out was silently dropped until the report was changed to name it.

## 6. Let an agent drive it

A stdio MCP server (standard library only): `scan_start`, `scan_status`, `scan_result`, `explain_check`. Scans are jobs. One bug the tests caught: a child process inherited the server's input pipe and could swallow protocol messages; give children no stdin.

## 7. Port the scorer, then prove it matches

Change the Python first so it is deterministic: JavaScript-style rounding (`floor(x + 0.5)`), sorted tie-breaks in the fix order, an importable module. Port to JavaScript. Generate fixtures by running the real audit on sample fragments and real pages, have Python produce the expected report, and assert deep equality in a Node test (`npm test` in the worker). The parity test passed on the first run because the determinism fixes came first.

## 8. Spike the risky part

A throw-away Worker, locked by a secret token, refusing private addresses. Questions and answers (2026-10-13): axe runs in Browser Run (same findings as local); the Tab key and the CDP accessibility tree work; a 15-page crawl in one request took 30 s. Pass condition fixed in advance: same findings, under 10 minutes of browser time for 20 pages. Then delete it when the real worker exists.

## 9. Build the worker

A front-door Worker (auth, REST, MCP), a Durable Object per scan (an alarm runs the crawl, saving progress after each page), a Budget Durable Object (monthly browser-seconds counter), the shared scorer, report kept for 7 days. Refused targets: non-http(s), credentials in the URL, localhost, `.local`, `.internal`, private, loopback and link-local addresses, including after a redirect. Follow `robots.txt`. See `a11y-worker/README.md`.

## 10. Deploy and secure

`wrangler deploy` with the config, then `wrangler secret put OWNER_TOKEN`. Generate the token with a random source, pipe it into `secret put` (no trailing newline, never in a file in the repo or in chat), and store a copy in a secrets manager (here: GCP Secret Manager, `a11y-scanner-owner-token`, read with `gcloud secrets versions access latest`). Verify the stored copy matches by comparing, not printing; then delete any scratch copy. Rotation: new value into the Worker secret first, then a new Secret Manager version. A Worker with no token configured returns 503, never "open". Check: no token gives 401; refused targets give an error; a scan of a known page gives the same score as the local tool.

## 11. Changing the scorer later (checklist)

1. Change `scripts/ratchet.py` (skill) and `a11y-worker/src/score.js` together.
2. Regenerate fixtures: `npm run fixtures` (needs the skill's `scripts/node_modules` and Chromium).
3. `npm test` must pass; if a deliberate change alters expected scores, check the fixture diff by eye before accepting it.
4. Run the skill tests, then redeploy the worker.
5. Update the grade wording and the coverage note only if the claim changes.

## 12. Fix and rescan a real site (worked example: a2uicatalog.ai)

1. **Baseline** the live site (light and dark), save the report, and write it up with the points lost and the fix order.
2. **Choose fixes by the fix order**, fixing shared things first. For a colour change, render before and after with contrast ratios computed from the token source, and pick from the render, not from numbers alone.
3. **Change the source of truth** (here `atoms/brand-tokens.yaml`), regenerate (`ops.py run catalog-rebuild`), and run the brand tests: pages that carry a hand-pasted brand block need restamping.
4. **Rescan the rebuilt local copy** before deploying: same pages, same options, both themes. Compare pages-with-a-serious-failure, not only the score (lessons 1 and 2).
5. **Trace what is left** with a short browser script that groups failing contrast pairs and link failures by colour and by container; fresh browser context per page.
6. Commit locally; deploy and re-baseline the live site only on explicit go-ahead.

## 13. What was deliberately left for later

A public tier (ownership checks, public quotas), a deploy-your-own template with a CI action, a declared deploy process, the tab-walk in the score, screen-reader testing.
