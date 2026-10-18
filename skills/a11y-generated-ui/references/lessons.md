# Lessons from the original audit (2026-10-08 to 10-10)

Measured on a catalog of about 650 agent-fillable components, light and dark host pages. Numbers are the audit's own and describe that catalog only.

## Result
Components with an axe violation: 172 to 121 (light) and 245 to 193 (dark). Tab-walk findings: 0. That is progress, not a pass.

## What went wrong, and what it taught
1. **First audit on a bare white page overstated failures.** Components read host tokens (`--muted`), which fell back to a literal grey. Audit in the real host stylesheet.
2. **Blind global grey swap: net harmful.** Components with their own dark surface got worse and components on a dark host lost contrast. The right grey depends on the surface behind it. Four components with their own light card regressed under a theme-aware token and had to be restored.
3. **One default can fail everything.** A default accent of `#6366f1` was 4.46:1 on white (AA needs 4.5:1). Darkening it helped many items at once. No single colour passes AA on both a white and a dark host, so the proper fix is a theme-aware default.
4. **Animated components flipped between pass and fail** because axe sampled contrast mid-fade. Freeze animation at its end state first.
5. **Three engines disagreed.** On contrast-flagged components only 77 were flagged by all three and 29 by one engine alone. IBM found keyboard failures axe missed: `<span onclick>` with no role, tab stop or key handler (WCAG 2.1.1) in eight components, and the CSS radio trick `input[type=radio]{display:none}` which cannot take focus in carousel and tab-style components.
6. **Checks only find a third to half of real issues.** They say nothing about order, focus or what is announced.

## Fixes that held
Darker default accent with a CI test; theme-aware muted text; three corrected host tokens (the biggest single gain); accessible names for SVGs and form fields; keyboard fix (hidden inputs stay focusable, clickable non-controls get a tab stop, a role and Enter/Space); arrow-key handling for menus; a reduced-motion rule for endless CSS loops.

## Still open at the time
Theme-aware default accent; accessible-name contract in the payload guard; text alternatives for canvas components; a TalkBack and screen-reader pass; running the full audit in CI (only a small token test did).

## Lessons from scanning and fixing a real site (2026-10-13)

1. **A score can sit still while the evidence moves.** After a contrast and link pass the site score stayed at 69, because the severity caps hold a site back until enough pages are free of serious failures. Pages with a serious failure fell from 40 to 21, contrast-failing pages from 40 to 13 and points lost to caps from 9.6 to 6.2. Report these underlying numbers beside the score, or a real improvement looks like nothing.
2. **The score counts which checks fail on which pages, not how many elements fail.** Light and dark scans of one site scored the same although contrast failed on 2,958 elements in light and 1,871 in dark. Element counts are in the report; whether the score should use them is open.
3. **A sample is an estimate.** The W3C "before" demo scored 65 on 8 pages and 69 on 20. State the page count every time.
4. **Check the theme actually applied.** The first two dark scans never went dark because the site stores its theme in localStorage and sets it again on load. The worker now records, per page, whether dark was in effect and warns when none were.
5. **Scope crawls.** Two crawls that wander into each other make any before and after comparison meaningless (`--path-scope`).
6. **A rule that covers paragraphs does not cover footers.** The underline rule for in-text links missed the footer, where text and links sit directly in the element. After a fix, rescan before declaring it done.
7. **Dark mode breaks content that sits on a fixed white surface.** Atom previews stayed white while their text took the dark theme's pale colours (1.15:1). Any fixed-colour surface that hosts themed content needs its own pinned tokens.
8. **When debugging with a browser, give each page its own browser context.** A shared profile leaked the dark theme's localStorage into the light runs and made light and dark look identical.
9. **Name what could not be audited.** One page whose axe run timed out was silently dropped until the report listed it.

## Lessons from shipping it (2026-10-17)

10. **A second generator is a second copy of your tokens.** The site passed locally and scored 94, then 84 live: the blog is built by a separate engine with its own hand copy of the brand colours, so it kept the old low-contrast ones and was the eleventh failing page. Fix the source of truth (the blog now reads the single brand file) and add a test that fails when published output carries a stale hash.
11. **Scan your own showcase with your own scanner.** An infographic built from the catalogue's own components scored 84, not 100: callout titles at 3.9:1 and 2.9:1, code blocks with no text colour, and chart cards whose see-through dark background turned mid-grey on a white page. Defects in shared components that site scans missed.
12. **Regenerating can ship more than you meant to.** The blog rebuild also published changes the generator had made since the last build (meta tags, a nav link), and would have published five unreleased posts. Diff the output before you deploy generated pages, and hold unreleased inputs aside.
13. **A threshold in the score makes a result fragile.** The site cap lifts when no more than a quarter of pages carry a serious failure; ten of forty pages is exactly the limit. Say so when you quote the number.

## 14. A tag-selected axe run silently skips the experimental rules

axe marks some WCAG rules `experimental` (`td-has-header`, `table-fake-caption`, `p-as-heading`, `css-orientation-lock` in axe-core 4.14), and `runOnly: { type: 'tag', ... }` never executes them. A scanner that selects by tag reports a clean result for rules it never ran. `audit.mjs` now enables them by name. Cross-check with a second tool (Lighthouse flagged `td-has-header` on 14 pages where this scanner reported nothing) and diff the rule list when you upgrade axe.
