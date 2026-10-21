---
name: roast-panel
description: >-
  Run an adversarial review panel (a "roast") over an accessibility audit, a
  fix or a change to generated UI before you call it done or publish a score.
  Named reviewers each attack it from one angle (screen-reader user,
  keyboard-only user, low-vision reader, motion-sensitive viewer, score
  sceptic, grumpy maintainer, and a security researcher when the change
  crawls or serves anything), every finding is checked by running something or
  marked unverified, and the gaps are fixed and roasted again in rounds. Use
  when asked to "roast", "red-team", "review before publishing" or "sanity
  check the score", and after any audit round whose number moved. Not a
  substitute for testing with disabled people.
license: MIT
---

# roast-panel

A score that moved is a claim, and a fix is a claim. This skill turns "I fixed it" into findings someone can check. It came out
of the audit behind `a11y-generated-ui`, where every scan agreed on three things that were wrong:

- the site scored 94 until a second tool showed four axe rules had never run (the honest number was 69);
- a keyboard fix passed every scanner while the focus ring was invisible on eight of ten components (WCAG 2.4.7);
- two of the author's own contrast fixes broke something else (a link colour that overrode a button, a white-on-white clock).

Each of those was found by someone asking a hostile question from one user's point of view and then running something to
answer it. The panel makes that routine.

## When to run it

- Before publishing a score, a grade, a before/after or a claim such as "keyboard accessible".
- After any audit round where the score moved (up or down), and after any change to the scoring, the rules or the harness.
- Before merging a fix that touches shared templates, tokens or a generator: one shared defect can move many pages.
- When someone outside asks "how do you know?".

## Rules for every reviewer

1. **Verify or label.** A finding is **verified** (you ran something: give the command and what it printed, or the screenshot
   and what it shows) or **unverified** (say so, and say what would verify it). Never present a guess as a finding, and never
   mark something fixed without re-running the check that found it.
2. **Severity.** **Critical**: a user is blocked, or a published number or claim is wrong. **Significant**: a real barrier or a
   misleading number with a workaround, or a guard that exists only as a comment. **Minor**: friction, wording, or an
   edge case. **Acknowledged, not a gap**: something the reviewer checked and found sound; record it, because it is evidence.
3. **Rescope in the open.** If a finding turns out narrower or wider than first reported, change its severity in place and say
   why ("rescoped from Critical, same day: ..."). Do not quietly delete it.
4. **One angle each.** A reviewer stays in role. The keyboard user does not comment on copy; the score sceptic does not fix CSS.
5. **Independence.** At least one reviewer must not have written the change. If you can run reviewers as separate agents or
   another model, do; give each only the change, the claim and this file, not the author's reasoning.
6. **Say what no tool can tell you.** Every roast ends by stating what only testing with disabled people, or with real
   assistive technology, would show, and whether that has been done.

## The panel

Pick the reviewers that fit the change; the first five apply to almost any UI change, the score sceptic to any published number.

### The Screen-Reader User
Can I find, name and operate everything without seeing it?
- Dump the accessibility tree for the changed components (Chromium DevTools protocol `Accessibility.getFullAXTree`, or
  Playwright `page.accessibility.snapshot()`) and read it top to bottom: every control has a role and a name, images have
  text alternatives or are hidden on purpose, headings are real headings, lists are lists, tables have headers.
- Label in name (WCAG 2.5.3): an `aria-label` must contain the visible text, not replace it.
- State changes are announced (`aria-expanded`, `aria-selected`, live regions for async results).
- If a real screen reader is available (NVDA, VoiceOver, TalkBack), use it on the changed components and write down what it
  said. If not, mark every screen-reader claim unverified.

### The Keyboard-Only User
Can I reach, see and operate everything with Tab, Shift+Tab, Enter, Space and the arrow keys?
- Run the keyboard walk from `a11y-generated-ui` on the changed items (`python3 ratchet.py --items items.json --tabwalk --only
  <names>`), then screenshot each focus stop in a real browser and look at it: focusable is not the same as visibly focused
  (WCAG 2.4.7), and the walk reads the accessibility tree, not pixels. Check the focus rule matches the real DOM (a `input:focus + label`
  rule draws nothing when the label is not the next sibling).
- Focus order follows the reading order; no traps; Escape closes what opened; custom widgets answer Enter and Space.
- Clickable elements that are not buttons or links: role, tab stop and key handler, or they are a barrier (WCAG 2.1.1).

### The Low-Vision Reader
Can I read it in my theme, at my size, without colour?
- Contrast in the real host stylesheet, light and dark (a bare white page overstates and hides failures).
- Reflow at 320 CSS px and 200% text (WCAG 1.4.10, 1.4.4); text spacing overrides (1.4.12) do not clip anything.
- No information by colour alone (1.4.1): links in body text are underlined or otherwise marked; states have a shape or a word.
- Forced colours / high contrast mode keeps borders and focus visible.

### The Motion-Sensitive Viewer
Will it make me unwell, or keep moving when I cannot stop it?
- With `prefers-reduced-motion: reduce` emulated, nothing loops, slides or parallaxes; the end state still shows.
- No more than three flashes in any second (WCAG 2.3.1); count brightness swings, not only opacity.
- Anything that moves for more than five seconds can be paused (2.2.2).

### The Score Sceptic
Is the number honest, and what is it not counting?
- Which rules did not run? (A tag-selected axe run skips the experimental rules; list them.) Which pages were not scanned, and
  is the sample big enough? The same broken site scored 65 on 8 pages and 69 on 20.
- Second opinion on what is checked, not only on what is found: run a second engine or a second tool (Lighthouse, IBM Equal
  Access, HTML_CodeSniffer) and explain every disagreement.
- Known twins: a deliberately broken page must score well below its fixed twin; if not, the scoring is wrong.
- Caps and weights: does a big move come from one fix lifting a cap? Report the evidence (pages with a serious failure, failing
  elements) beside the score, every time.
- Wording: grades say "automated findings", never "accessible" or "compliant".

### The Grumpy Maintainer
Is it in the spec, or will it come back?
- A test that failed before the fix and passes after, on the committed code. Name it.
- Does it run in CI, or only on the author's machine?
- One source of truth: tokens, brand colours and templates read from one place; copies drift (the blog kept its own colours).
- The baseline or ratchet was updated because things got better, not to make a red build green.
- Blind find-and-replace or bulk colour swaps: re-scan everything they touched.

### The Paranoid Security Researcher (when the change crawls, fetches or serves)
Can this tool be pointed at something it should not touch?
- Scope: one origin, robots.txt honoured, private and link-local addresses refused, permission confirmed for remote hosts.
- The browser sandbox is on for untrusted content; served folders cannot escape through symlinks.
- Anything an agent can call (an MCP server) has bounded arguments, timeouts and a scan root.

## The process

1. **Scope.** Write down what is being roasted (commits, PRs, the score and its date, the pages or components) and the claim
   it makes ("94, grade A", "keyboard reachable").
2. **Gather evidence first**: the scan output, the before/after numbers, screenshots, the diff.
3. **Run each reviewer** with its checklist. Record every finding with its severity, problem and fix direction.
4. **Fix** the Critical and Significant findings, or state plainly why one is accepted. Re-run the check that found each one.
5. **Roast again** (round 2, 3, ...) on the fixes: fixes break things. Stop when a round finds no new Critical or Significant
   gap, or the owner accepts what is left in writing.
6. **Publish the roast** next to the claim. A score without its roast is a draft.

## Output

Write `ROAST-YYYY-MM-DD-<topic>.md` (add `-R2`, `-R3` for later rounds):

```markdown
# Roast Panel — <topic>

**Date:** YYYY-MM-DD
**Round:** 1
**Scope:** <commits / PRs / pages / the score and the claim being roasted>

Verified claims below were checked directly (<how: commands, real browser runs, screen reader used>) this session, not accepted
on prose. Where something was not verified it is marked as such.

---

## The Keyboard-Only User

**Gaps:**

| Severity | Problem | Fix direction |
|---|---|---|
| Critical | <what fails, for whom, with the evidence> | <what would fix it> / **Fixed this round:** <commit, and the re-run that shows it> |
| *(acknowledged, not a gap)* | <what was checked and found sound, and how> | — |

<one section per reviewer>

---

## Fixed this round
- <finding> — <commit> — <the check re-run and its result>

## Left open
- <finding> — <why: accepted, out of scope, or not verifiable here>

## What no tool here can tell you
<screen reader and disabled-user testing: done or not, by whom, on what>
```

## Anti-patterns

- Roasting your own prose instead of the running thing.
- "Fixed" with no re-run, or a re-run of a different check.
- Dropping an awkward finding instead of rescoping it.
- A panel where every reviewer is the author in a different hat, with the author's notes in front of them.
- Treating a clean roast as "accessible". It means this panel found nothing more with what it could run.
