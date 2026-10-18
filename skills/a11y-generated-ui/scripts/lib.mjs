// Shared by the engine scripts. Two modes: FRAGMENTS (html.json {html:{name:html}}: each fragment is put on a clean page inside the host's
// stylesheet, with the network blocked so results are deterministic) and LIVE (html.json {urls:{name:url}}: each real page is loaded with its
// own CSS and scripts, and the dark theme is requested with prefers-color-scheme).
import fs from 'node:fs';
import dns from 'node:dns/promises';
import net from 'node:net';
export const DARK = process.env.A11Y_DARK_CLASS || 'dark';   // body class a host uses for its dark theme (fragment mode)
const DARK_ATTR = process.env.A11Y_DARK_ATTR || '';          // live mode, for sites that switch theme with an attribute, e.g. data-theme=dark (otherwise prefers-color-scheme is used)
const DARK_STORE = process.env.A11Y_DARK_STORAGE || '';      // live mode, for sites that remember the theme in localStorage, e.g. a2ui-theme=dark

// ---- Network safety --------------------------------------------------------------------------------------------------------------------------
// A scan loads someone's page and runs its scripts, so every request the browser makes (the page, redirects, images, scripts) is checked:
//   * link-local and cloud-metadata addresses (169.254.0.0/16, fe80::/10, metadata.google.internal) are never reached;
//   * private ranges (10/8, 172.16/12, 192.168/16, 100.64/10, fc00::/7) are blocked unless A11Y_ALLOW_PRIVATE=1;
//   * a public hostname that resolves to loopback is blocked (a rebinding trick); only localhost / 127.0.0.1 / ::1 themselves are loopback targets.
// Each target host is resolved once here and pinned for the browser (--host-resolver-rules), so the address checked is the address used.
// Residual risk: subresource hosts are checked per request but not pinned; for untrusted sites still scan from a container with no sensitive network access.
const LOCAL_NAMES = new Set(['localhost', '127.0.0.1', '::1']);
export const isLocalName = (h) => LOCAL_NAMES.has(String(h).replace(/^\[|\]$/g, '').toLowerCase());
export function classify(ip) {
  let a = ip.split('%')[0].toLowerCase();
  const mapped = a.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
  if (mapped) a = mapped[1];
  if (net.isIPv4(a)) {
    const [o1, o2] = a.split('.').map(Number);
    if (o1 === 127) return 'loopback';
    if (o1 === 169 && o2 === 254) return 'link-local';
    if (o1 === 10 || o1 === 0 || (o1 === 172 && o2 >= 16 && o2 <= 31) || (o1 === 192 && o2 === 168) || (o1 === 100 && o2 >= 64 && o2 <= 127)) return 'private';
    return 'public';
  }
  if (a === '::1') return 'loopback';
  if (/^fe[89ab]/.test(a)) return 'link-local';
  if (/^f[cd]/.test(a)) return 'private';
  return 'public';
}
const vetted = new Map();   // hostname -> Promise<string[]> of addresses, or a rejection
export function vetHost(hostname) {
  const h = String(hostname).replace(/^\[|\]$/g, '').toLowerCase();
  if (!vetted.has(h)) {
    vetted.set(h, (async () => {
      if (h === 'metadata.google.internal') throw new Error(h + ' is a cloud-metadata address: never scanned');
      const addrs = net.isIP(h) ? [h] : (await dns.lookup(h, { all: true })).map(x => x.address);
      for (const ad of addrs) {
        const c = classify(ad);
        if (c === 'link-local') throw new Error(h + ' resolves to a link-local address (' + ad + '): never scanned');
        if (c === 'private' && process.env.A11Y_ALLOW_PRIVATE !== '1') throw new Error(h + ' resolves to a private address (' + ad + '): blocked. Set A11Y_ALLOW_PRIVATE=1 to scan your own internal hosts.');
        if (c === 'loopback' && !isLocalName(h)) throw new Error(h + ' resolves to a loopback address (' + ad + '): blocked');
      }
      return addrs;
    })());
  }
  return vetted.get(h);
}
// Kept for the crawler: the URL the browser finally landed on must not be link-local. (vetHost does the real work; this is the cheap final check.)
export function landedOnLinkLocal(u) {
  try { const h = new URL(u).hostname.replace(/^\[|\]$/g, '').toLowerCase(); return classify(h) === 'link-local' || h === 'metadata.google.internal'; } catch { return false; }
}
const hostsOf = (d) => (d && d.urls ? [...new Set(Object.values(d.urls).map(u => new URL(u).hostname))] : []);

// ---- Browser launch --------------------------------------------------------------------------------------------------------------------------
// The Chromium sandbox stays ON for remote hosts. It is off only for content you control (fragments, a local folder, localhost), where containers and CI
// often cannot create the sandbox, or when you set A11Y_NO_SANDBOX=1 yourself.
const BASE_ARGS = ['--disable-gpu', '--mute-audio', '--use-gl=swiftshader'];
export async function launchBrowser(puppeteer, d) {
  const hosts = hostsOf(d);
  const trusted = hosts.every(isLocalName);
  const args = [...BASE_ARGS];
  const rules = [];
  for (const h of hosts) {
    const addrs = await vetHost(h);
    const v4 = addrs.find(x => net.isIPv4(x));
    if (!isLocalName(h) && !net.isIP(h) && v4) rules.push('MAP ' + h + ' ' + v4);
  }
  if (rules.length) args.push('--host-resolver-rules=' + rules.join(','));
  const noSandbox = process.env.A11Y_NO_SANDBOX === '1' || trusted;
  if (noSandbox) args.push('--no-sandbox');
  try {
    return await puppeteer.launch({ executablePath: process.env.CHROMIUM || '/usr/bin/chromium', headless: 'new', args });
  } catch (e) {
    throw new Error(String(e.message).slice(0, 300) + (noSandbox ? '' : '\n(Chromium could not start with its sandbox. In a container or CI set A11Y_NO_SANDBOX=1, and only when scanning content you trust.)'));
  }
}

export const readInput = (dir) => JSON.parse(fs.readFileSync(dir + '/html.json', 'utf8'));
export const namesOf = (d) => Object.keys(d.urls || d.html);
export const rootSel = (d) => (d.urls ? 'body' : 'main');
export async function prepare(page, d) {
  await page.setViewport({ width: 900, height: 700 });
  if (d.urls) {
    await page.setRequestInterception(true);
    page.on('request', async (r) => {
      try { const u = new URL(r.url()); if (u.protocol === 'http:' || u.protocol === 'https:') await vetHost(u.hostname); await r.continue(); }
      catch (e) { try { await r.abort('blockedbyclient'); } catch (_) {} }
    });
  } else {
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
