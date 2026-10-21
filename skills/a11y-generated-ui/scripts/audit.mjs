// Runs axe-core (WCAG 2.0-2.2 A/AA) over every rendered atom example, one page each, in headless Chromium.
// Input: <dir>/html.json  {html:{atom:html}, stage:{atom:stage}}   Output: <dir>/audit.json
import fs from 'node:fs';
import { createRequire } from 'node:module';
import puppeteer from 'puppeteer-core';
import { readInput, namesOf, prepare, open, launchBrowser } from './lib.mjs';
const require = createRequire(import.meta.url);
const dir = process.argv[2];
const dark = process.argv[3] === 'dark';
const shell = fs.existsSync(dir + '/shell.css') ? fs.readFileSync(dir + '/shell.css', 'utf8') : '';   // the real host stylesheet: theme tokens (--muted, --text, --bg ...) as a host paints them
const d = readInput(dir);
const axeSrc = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const b = await launchBrowser(puppeteer, d);
const page = await b.newPage();
await prepare(page, d);
const out = {};
const names = namesOf(d);
const save = () => { fs.writeFileSync(dir + '/audit.json.tmp', JSON.stringify(out)); fs.renameSync(dir + '/audit.json.tmp', dir + '/audit.json'); };   // results so far survive a timeout or a crash
let n = 0;
for (const t of names) {
  const res = {};
  try {
    await open(page, d, t, { shell, dark, kind: 'audit' });
    // Freeze animations at their END state so contrast is not sampled mid-fade: an atom that fades text in would otherwise flip between
    // pass and fail from run to run (seen on big_reveal, kinetic_headline, gmail_unread_count).
    await page.addStyleTag({ content: '*,*::before,*::after{animation-duration:0.001s!important;animation-delay:0s!important;animation-iteration-count:1!important;transition:none!important}' });
    await new Promise(r => setTimeout(r, 200));
    if (page._a11ySlow) res.slow = page._a11ySlow;          // the network never went idle (stream, long poll, request never answered); audited as it stood
    if (d.urls) res.src = (await page.content()).slice(0, 2000000);
    await page.evaluate(axeSrc);
    const ax = await Promise.race([
      page.evaluate(async () => {
        // axe tags some WCAG rules 'experimental' and a tag-selected run never executes them (td-has-header, table-fake-caption, p-as-heading and
        // css-orientation-lock in axe-core 4.14). Switch on every experimental rule that carries a WCAG tag, so a newer axe cannot silently drop one.
        const W = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
        const rules = { region: { enabled: false } };
        for (const r of axe.getRules()) if (r.tags.includes('experimental') && !r.tags.includes('deprecated') && r.tags.some(t => W.includes(t))) rules[r.ruleId] = { enabled: true };
        const x = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] }, rules, resultTypes: ['violations', 'passes', 'incomplete'] });
        const cat = (r) => (r.tags.find(t => t.startsWith('cat.')) || 'cat.other').slice(4);
        const sc = (r) => r.tags.filter(t => /^wcag\d{3,}$/.test(t));   // success-criterion tags, e.g. wcag131: the first digit is the WCAG principle
        return { v: x.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, cat: cat(v), sc: sc(v), help: v.help, url: v.helpUrl,
          pairs: v.id === 'color-contrast' ? v.nodes.map(n => { const d = (n.any[0] || {}).data || {}; return [d.fgColor, d.bgColor, d.contrastRatio]; }) : undefined })),
          p: x.passes.map(p => ({ id: p.id, impact: p.impact || 'moderate', cat: cat(p), sc: sc(p) })),
          inc: x.incomplete.map(i => ({ id: i.id, nodes: i.nodes.length })) };   // axe could not decide these (needs a person): kept, not scored
      }),
      new Promise((_, rej) => setTimeout(() => rej(new Error('axe timeout')), +(process.env.A11Y_AXE_TIMEOUT || 25000))),
    ]);
    res.v = ax.v; res.p = ax.p; res.inc = ax.inc;
  } catch (e) { res.err = String(e.message).slice(0, 100); }
  out[t] = res;
  n++;
  console.error('[' + n + '/' + names.length + '] ' + t + (res.err ? '  NOT AUDITED: ' + res.err : ''));
  if (n % 5 === 0) save();
}
await b.close();
save();
console.log('audited ' + Object.keys(out).length);
process.exit(0);   // never wait for a socket a page left open
