# The end-to-end pattern

One loop, from "what is wrong" to "it can't come back". Each step is a command or a tool in this skill.

1. **Scan.** Point it at pages: a built folder (`--dir`), a live site (`--url --crawl --path-scope`), a sitemap, or rendered component fragments (`--items`). Real CSS and scripts load; the dark theme is requested the way the site expects (`prefers-color-scheme`, or `A11Y_DARK_ATTR` / `A11Y_DARK_STORAGE`).
2. **Check.** axe-core, plus five static checks axe cannot make, plus (optionally) two more engines and a keyboard walk.
3. **Score.** Four layers (perceivable 35, operable 35, understandable 15, robust 15). Failures weigh by axe impact. Severity caps stop many passing checks hiding a barrier. The grade only ever says "automated findings".
4. **See where the points went.** Each failing check shows the points it cost and the score gain if it alone were fixed.
5. **Fix in the right order.** A greedy fix order re-scores the whole site at each step, so you see which combination crosses a cap, not just which check is biggest. Fix shared things first (stylesheet, defaults, templates): they move the most pages.
6. **Rescan and ratchet.** `--baseline` records what is not yet clean. After that a new page or component must start clean and an old one may not get worse; fixed items are reported so the gain can be locked in (`--update`).
7. **Gate.** `--score --min-score N` fails a CI step below a threshold; `--static` runs in seconds with no browser, for fast checks.
8. **Let an agent drive it.** The local MCP server (`scan_start`, `scan_status`, `scan_result`, `explain_check`) lets an agent run the loop: scan, read the fix order, make the change, rescan.
9. **Run it hosted, privately.** The same scanner runs as a Cloudflare Worker using Browser Run (a Durable Object per scan, a monthly browser-seconds budget, REST and MCP endpoints, owner token only), so CI and agents can call it without a local Chromium. A JavaScript scorer is held equal to the Python one by a parity test. See `build-runbook.md` and the worker's README.
10. **Say what it does not cover.** Every report ends with the coverage note: automated checks find roughly a third to half of real issues; keyboard order, screen-reader output, content and anything behind a login are not scored. A high score is never a conformance claim.

## CI

A CI step posts a scan to the worker with an extra token, polls until the report is ready, saves it as a build artifact, and fails below a minimum score (the same `--min-score` rule as the local tool). A stored baseline gives the ratchet across builds. The worker is private for now; a deploy-your-own template for other Cloudflare accounts is a later option.

## Pattern worked example (numbers from one local site scan, 13 pages)

Score 69 (C). Where the points went: colour contrast (-8.2 points per page), links distinguished only by colour (-7.0). Fix order: contrast 69 to 84, in-text links 84 to 94, then four small items to 97. The first two are fixes in a shared stylesheet.

## Credit

The idea of a layered score with a CI gate and a scan, fix, rescan loop comes from ora.ai (which scores agent-readiness). Everything else, the checks, layers, weights, caps, cut-offs and the wording of grades, is ours.
