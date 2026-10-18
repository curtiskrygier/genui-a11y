# Retrospective: the same scanner, the same pages, five points in time

Author-reported, from one catalogue's public site (40 pages sampled from the home page). Built so a change of scoring method can be judged on real history, not on a promise. The earlier two rows were scanned from the site as committed on those dates (a local build of the built pages); the later three from the live site.

Both columns score the same raw axe data. **Old** groups checks into layers by axe's own category; **new** assigns each check the WCAG principle of its success criterion.

| State | Pages | Old: site / page mean | New: site / page mean | Pages held by a serious or critical failure | Layers (new): perceivable / operable / understandable / robust |
|---|---|---|---|---|---|
| 8 Oct, before any accessibility fix | 39 | 69 C / 73.6 | 69 C / 73.7 | 36 | 72 / 96 / 100 / 99 |
| 13 Oct, the published baseline | 39 | 69 C / 71.6 | 69 C / 71.6 | 38 | 71 / 96 / 100 / 99 |
| 17 Oct live, rules as then run | 40 | 94 A / 93.5 | 94 A / 93.6 | 10 | 95 / 96 / 100 / 99 |
| 17 Oct live, with four hidden WCAG rules switched on | 39 | 69 C / 83.9 | 69 C / 83.9 | 23 | 90 / 98 / 100 / 100 |
| 18 Oct live, after fixes | 37 | 99 A / 99.1 | 99 A / 99.2 | 1 | 99 / 100 / 100 / 100 |

What it shows:

- **The site score did not change under the new mapping on any of these.** The severity caps decide it (more than a tenth of pages held at 69 gives 69, more than a quarter at 84 gives 84), so a re-grouping of layers cannot move it. On the full 550-page catalogue scan the page mean moved from 97.6 to 97.7 and 25 of 550 pages changed by 3 points or more.
- **The per-layer numbers did move**, and are now meaningful: table and list failures (WCAG 1.3.1) count against Perceivable, not Robust.
- **8 to 13 October dips (page mean 73.6 to 71.6) and I have not investigated why.** Both were scanned with the same rules. The 13 October build is the state behind the published baseline; between the two dates there were accessibility commits, new pages and atoms, so the content differs. Treat page means across states as a trend, not a measurement.
- **The 94 on 17 October was real for the rules then run and wrong as a measure.** Switching on four WCAG rules that axe marks experimental (`td-has-header` among them) took the same pages to 69, because one empty `<th>` in a shared template put a critical failure on 14 pages.
- The first two rows were scanned with today's audit (hidden rules on) and the third without, so rows 2 and 3 are not directly comparable; row 4 is row 3's data with the extra rules.

Reading the series, the useful signal is the **count of pages held down** (36, 38, 10, 23, 1) and the **top failing checks**, not the site score alone. At the start the catalogue had 2,241 failing contrast elements on 36 pages, 35 pages with links told apart by colour only, and 14 pages with the table-header defect.

Limits: one site, one author, local builds for the earlier rows, `/blog` excluded (it lives in a different repository), one page (`/surfaces/android`) did not finish scanning in the earlier rows.
