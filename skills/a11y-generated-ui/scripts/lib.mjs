// Shared by the engine scripts. Two modes: FRAGMENTS (html.json {html:{name:html}}: each fragment is put on a clean page inside the host's
// stylesheet, with the network blocked so results are deterministic) and LIVE (html.json {urls:{name:url}}: each real page is loaded with its
// own CSS and scripts, and the dark theme is requested with prefers-color-scheme).
import fs from 'node:fs';
export const DARK = process.env.A11Y_DARK_CLASS || 'dark';   // body class a host uses for its dark theme (fragment mode)
const DARK_ATTR = process.env.A11Y_DARK_ATTR || '';
const DARK_STORE = process.env.A11Y_DARK_STORAGE || '';       // live mode, for sites that remember the theme in localStorage, e.g. a2ui-theme=dark          // live mode, for sites that switch theme with an attribute, e.g. data-theme=dark (otherwise prefers-color-scheme is used)
// A page that redirects to a cloud-metadata or link-local address is never read. (This checks the URL the browser landed on; it cannot see a hostname that
// resolves there. Scan untrusted sites from a container or a machine with no sensitive network access.)
export function landedOnLinkLocal(u) {
  try { const h = new URL(u).hostname.replace(/^\[|\]$/g, '').toLowerCase(); return /^169\.254\./.test(h) || /^fe80:/.test(h) || h === 'metadata.google.internal'; } catch { return false; }
}
export const readInput = (dir) => JSON.parse(fs.readFileSync(dir + '/html.json', 'utf8'));
export const namesOf = (d) => Object.keys(d.urls || d.html);
export const rootSel = (d) => (d.urls ? 'body' : 'main');
export const CHROME_ARGS = ['--no-sandbox', '--disable-gpu', '--mute-audio', '--use-gl=swiftshader'];
export async function prepare(page, d) {
  await page.setViewport({ width: 900, height: 700 });
  if (!d.urls) {
    await page.setRequestInterception(true);
    page.on('request', r => (r.url().startsWith('data:') || r.url().startsWith('about:')) ? r.continue() : r.abort());   // offline, deterministic
  }
}
// kind: 'audit' | 'cross' | 'tab' (the small differences between the three scripts' wrapper pages)
export async function open(page, d, t, { shell, dark, kind }) {
  if (d.urls) {
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: dark ? 'dark' : 'light' }]);
    if (dark && (DARK_ATTR || DARK_STORE)) {
      const [ak, av] = DARK_ATTR.split('='), [sk, sv] = DARK_STORE.split('=');
      await page.evaluateOnNewDocument((ak, av, sk, sv) => { try { if (sk) localStorage.setItem(sk, sv || 'dark'); } catch (e) {} if (ak) document.documentElement.setAttribute(ak, av || 'dark'); }, ak, av, sk, sv);
    }
    await page.goto(d.urls[t], { waitUntil: 'networkidle2', timeout: +(process.env.A11Y_NAV_TIMEOUT || 40000) });
    if (landedOnLinkLocal(page.url())) throw new Error('redirected to a link-local or metadata address: not audited');
    if (dark && DARK_ATTR) { const [k, v] = DARK_ATTR.split('='); await page.evaluate((k, v) => document.documentElement.setAttribute(k, v), k, v || 'dark'); }
    return;
  }
  const body = kind === 'tab' ? 'margin:0;background:var(--bg,#fff)' : 'margin:0;background:var(--bg,#fff);color:var(--text,#111)';
  const wrap = kind === 'tab' ? '<main style="padding:16px">' : '<main>';
  await page.setContent('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title><style>' + shell + '</style></head><body class="' + (dark ? DARK : '') + '" style="' + body + '">' + wrap + d.html[t] + '</main></body></html>',
    kind === 'tab' ? { waitUntil: 'load' } : { waitUntil: 'domcontentloaded', timeout: 20000 });
}
