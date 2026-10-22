// Same-origin crawler for the live scan. Reads the real, rendered DOM (so JavaScript-built links count), stays on the start URL's origin,
// respects robots.txt (User-agent: * Disallow lines), waits between pages, and stops at --max pages and --depth links from the start.
// usage: node crawl.mjs <outdir> <startUrl> [--max 30] [--depth 2] [--delay 500] [--path-scope]
// --path-scope: stay under the start URL's own folder (so /docs/v2/index.html only follows links below /docs/v2/), not just on its origin.
import fs from 'node:fs';
import puppeteer from 'puppeteer-core';
import { launchBrowser, prepare, go, landedOnLinkLocal, vetUrl, declareTargets, recover } from './lib.mjs';
const [dir, start, ...rest] = process.argv.slice(2);
const opt = (k, d) => { const i = rest.indexOf('--' + k); return i >= 0 ? Number(rest[i + 1]) : d; };
const MAX = opt('max', 30), DEPTH = opt('depth', 2), DELAY = opt('delay', 500);
const origin = new URL(start).origin;
const PATH_SCOPE = rest.includes('--path-scope');
const scopePrefix = (() => { const p = new URL(start).pathname; return p.endsWith('/') ? p : p.slice(0, p.lastIndexOf('/') + 1); })();
const SKIP = /\.(pdf|zip|png|jpe?g|gif|webp|svg|ico|css|js|json|xml|mp4|webm|mp3|woff2?|ttf|txt|csv|docx?|xlsx?)$/i;
let disallow = [];
declareTargets({ urls: { start } });
await vetUrl(start);   // refuse a bad scheme, link-local / private / rebinding targets before any request, including robots.txt
try {
  // redirect: 'manual' on purpose: a redirect here could point the fetch at an address the checks above never saw. A redirected robots.txt is treated as absent.
  const r = await fetch(origin + '/robots.txt', { redirect: 'manual', signal: AbortSignal.timeout(15000) });
  if (r.ok && r.type !== 'opaqueredirect') {
    let applies = false;
    for (const raw of (await r.text()).split('\n')) {
      const line = raw.split('#')[0].trim();
      const m = line.match(/^([A-Za-z-]+)\s*:\s*(.*)$/); if (!m) continue;
      const k = m[1].toLowerCase(), v = m[2].trim();
      if (k === 'user-agent') applies = v === '*';
      else if (applies && k === 'disallow' && v) disallow.push(v);
    }
  }
} catch {}
const allowed = (u) => !disallow.some(p => new URL(u).pathname.startsWith(p));
const norm = (u) => { const x = new URL(u); x.hash = ''; if (x.pathname.length > 1) x.pathname = x.pathname.replace(/\/+$/, ''); return x.toString(); };
const b = await launchBrowser(puppeteer, { urls: { start } });
let page = await b.newPage();
await prepare(page, { urls: { start } });   // viewport plus the per-request network check
await page.setViewport({ width: 1100, height: 800 });
const seen = new Map(), queue = [[norm(start), 0]];
const skipped = [];
while (queue.length && seen.size < MAX) {
  const [url, depth] = queue.shift();
  if (seen.has(url)) continue;
  if (!allowed(url)) { skipped.push(url + '  (robots.txt)'); continue; }
  try {
    const resp = await go(page, url, { crawl: true });
    if (landedOnLinkLocal(page.url())) { skipped.push(url + '  (redirected to a link-local address)'); continue; }
    const type = (resp && resp.headers()['content-type']) || '';
    if (!/html/i.test(type)) continue;
    { const pu = new URL(url); seen.set(url, (pu.pathname || '/') + pu.search); }
    if (depth < DEPTH) {
      const links = await page.evaluate(() => [...document.querySelectorAll('a[href]')].map(a => a.href));
      for (const l of links) {
        let u; try { u = new URL(l); } catch { continue; }
        if (u.origin !== origin || !/^https?:$/.test(u.protocol) || SKIP.test(u.pathname)) continue;
        if (PATH_SCOPE && !u.pathname.startsWith(scopePrefix)) continue;
        const n = norm(l); if (!seen.has(n)) queue.push([n, depth + 1]);
      }
    }
  } catch (e) { skipped.push(url + '  (' + String(e.message).slice(0, 60) + ')'); page = await recover(b, page, { urls: { start } }, e); await page.setViewport({ width: 1100, height: 800 }); }
  await new Promise(r => setTimeout(r, DELAY));
}
await b.close();
const urls = {}; for (const [u, p] of seen) urls[p === '/' ? '/' : p] = u;
fs.writeFileSync(dir + '/html.json', JSON.stringify({ urls }));
console.log(`crawled ${seen.size} page(s) on ${origin}${PATH_SCOPE ? ' under ' + scopePrefix : ''} (max ${MAX}, depth ${DEPTH}, ${DELAY} ms apart)` + (disallow.length ? `; robots.txt disallows ${disallow.length} path(s)` : '') + (skipped.length ? `; skipped ${skipped.length}:\n  ` + skipped.slice(0, 8).join('\n  ') : ''));
process.exit(0);
