// Second and third opinions: runs HTML_CodeSniffer (Squiz) and IBM Equal Access (ACE) over the same rendered atoms, in the same
// host stylesheet, so crosscheck_report.py can compare them with axe-core. Input <dir>/html.json + shell.css, output <dir>/<engine>.json.
// usage: node crosscheck.mjs <dir> <light|dark> <htmlcs|ibm> [atom,atom,...]
import fs from 'node:fs';
import { createRequire } from 'node:module';
import puppeteer from 'puppeteer-core';
import { readInput, namesOf, rootSel, prepare, open, launchBrowser } from './lib.mjs';
const require = createRequire(import.meta.url);
const [dir, theme, engine, only] = process.argv.slice(2);
const d = readInput(dir);
const shell = fs.existsSync(dir + '/shell.css') ? fs.readFileSync(dir + '/shell.css', 'utf8') : '';
const src = engine === 'htmlcs' ? fs.readFileSync(require.resolve('html_codesniffer/build/HTMLCS.js'), 'utf8')
                                : fs.readFileSync(require.resolve('accessibility-checker-engine/ace.js'), 'utf8');
const b = await launchBrowser(puppeteer, d);
const page = await b.newPage();
await prepare(page, d);
const names = only ? only.split(',') : namesOf(d);
const ROOT = rootSel(d);
const out = {};
for (const t of names) {
  const res = {};
  try {
    await open(page, d, t, { shell, dark: theme === 'dark', kind: 'cross' });
    await new Promise(r => setTimeout(r, 120));
    await page.evaluate(src);
    res.v = await Promise.race([
      page.evaluate(async (engine, ROOT) => {
        if (engine === 'htmlcs') {
          return await new Promise((resolve, reject) => {
            try {
              HTMLCS.process('WCAG2AA', document.querySelector(ROOT), function () {
                resolve(HTMLCS.getMessages().filter(m => m.type === 1).map(m => ({ rule: m.code, msg: String(m.msg).slice(0, 90) })));
              });
            } catch (e) { reject(e); }
          });
        }
        const checker = new ace.Checker();
        const rep = await checker.check(document.querySelector(ROOT), ['IBM_Accessibility']);
        return rep.results.filter(r => r.value[0] === 'VIOLATION' && r.value[1] === 'FAIL').map(r => ({ rule: r.ruleId, msg: String(r.message || '').slice(0, 90) }));
      }, engine, ROOT),
      new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), +(process.env.A11Y_NAV_TIMEOUT || 40000))),
    ]);
  } catch (e) { res.err = String(e.message).slice(0, 120); }
  out[t] = res;
}
await b.close();
fs.writeFileSync(dir + '/' + engine + '-' + theme + '.json', JSON.stringify(out));
console.log(engine + ' ' + theme + ': ' + Object.keys(out).length + ' items, ' + Object.values(out).filter(v => v.err).length + ' errors');
process.exit(0);
