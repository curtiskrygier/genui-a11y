// Runs axe-core (WCAG 2.0-2.2 A/AA) over every rendered atom example, one page each, in headless Chromium.
// Input: <dir>/html.json  {html:{atom:html}, stage:{atom:stage}}   Output: <dir>/audit.json
import fs from 'node:fs';
import { createRequire } from 'node:module';
import puppeteer from 'puppeteer-core';
import { readInput, namesOf, prepare, open, CHROME_ARGS } from './lib.mjs';
const require = createRequire(import.meta.url);
const dir = process.argv[2];
const dark = process.argv[3] === 'dark';
const shell = fs.existsSync(dir + '/shell.css') ? fs.readFileSync(dir + '/shell.css', 'utf8') : '';   // the real host stylesheet: theme tokens (--muted, --text, --bg ...) as a host paints them
const d = readInput(dir);
const axeSrc = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const b = await puppeteer.launch({ executablePath: process.env.CHROMIUM || '/usr/bin/chromium', headless: 'new', args: CHROME_ARGS });
const page = await b.newPage();
await prepare(page, d);
const out = {};
for (const t of namesOf(d)) {
  const res = {};
  try {
    await open(page, d, t, { shell, dark, kind: 'audit' });
    // Freeze animations at their END state so contrast is not sampled mid-fade: an atom that fades text in would otherwise flip between
    // pass and fail from run to run (seen on big_reveal, kinetic_headline, gmail_unread_count).
    await page.addStyleTag({ content: '*,*::before,*::after{animation-duration:0.001s!important;animation-delay:0s!important;animation-iteration-count:1!important;transition:none!important}' });
    await new Promise(r => setTimeout(r, 200));
    if (d.urls) res.src = (await page.content()).slice(0, 2000000);
    await page.evaluate(axeSrc);
    const ax = await Promise.race([
      page.evaluate(async () => {
        const x = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] }, rules: { region: { enabled: false }, 'td-has-header': { enabled: true }, 'table-fake-caption': { enabled: true }, 'p-as-heading': { enabled: true }, 'css-orientation-lock': { enabled: true } }, resultTypes: ['violations', 'passes'] });
        const cat = (r) => (r.tags.find(t => t.startsWith('cat.')) || 'cat.other').slice(4);
        return { v: x.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, cat: cat(v), help: v.help, url: v.helpUrl,
          pairs: v.id === 'color-contrast' ? v.nodes.map(n => { const d = (n.any[0] || {}).data || {}; return [d.fgColor, d.bgColor, d.contrastRatio]; }) : undefined })),
          p: x.passes.map(p => ({ id: p.id, impact: p.impact || 'moderate', cat: cat(p) })) };
      }),
      new Promise((_, rej) => setTimeout(() => rej(new Error('axe timeout')), +(process.env.A11Y_AXE_TIMEOUT || 25000))),
    ]);
    res.v = ax.v; res.p = ax.p;
  } catch (e) { res.err = String(e.message).slice(0, 100); }
  out[t] = res;
}
await b.close();
fs.writeFileSync(dir + '/audit.json', JSON.stringify(out));
console.log('audited ' + Object.keys(out).length);
