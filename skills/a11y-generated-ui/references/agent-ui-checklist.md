# Checklist for agent-driven UI (DRAFT)

Drawn from the public WebMCP accessibility discussion (webmachinelearning/webmcp issues 272 and 277, Sept-Oct 2026). That discussion is unsettled; treat this as questions to ask, not requirements. Implementation reports there are explicitly not screen-reader or disabled-user validation.

When a person must discover, review, approve, monitor or cancel what an agent does:

1. **Discovery.** Can a person perceive which tools or actions the agent has, by more than a programmatic registry?
2. **Review and approval.** For consequential actions, is there an accessible review, confirm and correct step that a user preference can require (WCAG 3.3.4)? A page-side approval is not a security boundary when the same host can automate the page, and anti-automation defences (CAPTCHAs, timing, dwell) are themselves accessibility barriers.
3. **Operation.** Can all of it be done by keyboard and assistive technology?
4. **Status.** Are start, progress, completion, failure, cancel and undo all perceivable, including under reduced motion (a static end state; WCAG 2.2.2 for moving content over five seconds; 2.3.1 for flashing)? Page-authored live-region announcements are useful non-normative guidance.
5. **Provenance.** Can a person tell which values an agent supplied? Do not state "you did this" or "the agent did this" unless that is actually known: from the page, caller attribution of an imperative call is not reliable.
6. **Privacy.** Behaviour must follow explicit user preference and must not detect or reveal assistive-technology use.
7. **Labels survive.** In form-like UI built from schemas, accessible labels, help and error relationships must be preserved, not reduced to schema strings. Agent-facing descriptions are not a substitute for the control's accessible label.
