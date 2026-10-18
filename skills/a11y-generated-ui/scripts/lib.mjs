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
//   * private and special-use ranges (10/8, 172.16/12, 192.168/16, 100.64/10, 198.18/15, multicast, fc00::/7, fec0::/10, Teredo ...) are blocked
//     unless A11Y_ALLOW_PRIVATE=1;
//   * loopback is reachable only at the exact origin(s) being scanned (a local build on 127.0.0.1:8777 may load its own files, but a page on a remote
//     host cannot probe your localhost, and a scan of one local port cannot reach another);
//   * a public hostname that resolves to loopback is blocked (a rebinding trick);
//   * only http, https, data, blob and about URLs are allowed; WebSockets and file/ftp URLs are blocked, and service workers are bypassed.
// Addresses are parsed to bytes, and every form that embeds an IPv4 address (IPv4-mapped, NAT64, 6to4, IPv4-compatible) is classified by the IPv4
// inside it. Anything that cannot be parsed is treated as not public.
// Each target host is resolved once here and pinned for the browser (--host-resolver-rules), so the address checked is the address used.
// Residual risk: redirect and subresource hosts are checked per request but not pinned (a hostile DNS server could answer differently to Chromium than
// to Node); for untrusted sites scan from a container with no sensitive network access.
const LOCAL_NAMES = new Set(['localhost', '127.0.0.1', '::1']);
const bare = (h) => String(h).replace(/^\[|\]$/g, '').toLowerCase();
export const isLocalName = (h) => LOCAL_NAMES.has(bare(h));
function classify4(o) {
  const [o1, o2, o3] = o;
  if (o1 === 127) return 'loopback';
  if (o1 === 169 && o2 === 254) return 'link-local';
  if (o1 === 0 || o1 === 10 || (o1 === 172 && o2 >= 16 && o2 <= 31) || (o1 === 192 && o2 === 168) || (o1 === 100 && o2 >= 64 && o2 <= 127)
      || (o1 === 192 && o2 === 0 && o3 === 0) || (o1 === 198 && (o2 === 18 || o2 === 19)) || o1 >= 224) return 'private';
  return 'public';
}
function ipv6Bytes(a) {   // 16 bytes, or null if a is not a valid IPv6 address
  let s = a;
  const dotted = s.match(/(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (dotted) {
    const p = dotted.slice(1).map(Number);
    if (p.some(x => x > 255)) return null;
    s = s.slice(0, s.length - dotted[0].length) + ((p[0] << 8) | p[1]).toString(16) + ':' + ((p[2] << 8) | p[3]).toString(16);
  }
  const halves = s.split('::');
  if (halves.length > 2) return null;
  const head = halves[0] ? halves[0].split(':') : [];
  const tail = halves.length === 2 && halves[1] ? halves[1].split(':') : [];
  const fill = 8 - head.length - tail.length;
  if (halves.length === 1 ? head.length !== 8 : fill < 1) return null;
  const groups = [...head, ...Array(halves.length === 2 ? fill : 0).fill('0'), ...tail];
  if (groups.length !== 8) return null;
  const out = [];
  for (const g of groups) { if (!/^[0-9a-f]{1,4}$/.test(g)) return null; const v = parseInt(g, 16); out.push(v >> 8, v & 255); }
  return out;
}
export function classify(ip) {
  const a = String(ip).split('%')[0].toLowerCase();
  if (net.isIPv4(a)) return classify4(a.split('.').map(Number));
  const b = net.isIPv6(a) ? ipv6Bytes(a) : null;
  if (!b) return 'private';                                                    // unparseable: never treated as public
  const zero = (from, to) => b.slice(from, to).every(x => x === 0);
  if (zero(0, 16)) return 'loopback';                                          // :: (the unspecified address connects to localhost on Linux)
  if (zero(0, 15) && b[15] === 1) return 'loopback';                           // ::1
  if (zero(0, 10) && b[10] === 255 && b[11] === 255) return classify4(b.slice(12));   // ::ffff:a.b.c.d (IPv4-mapped)
  if (zero(0, 12)) { const c = classify4(b.slice(12)); return c === 'public' ? 'private' : c; }   // ::a.b.c.d (IPv4-compatible, deprecated)
  if (b[0] === 0x00 && b[1] === 0x64 && b[2] === 0xff && b[3] === 0x9b && zero(4, 12)) return classify4(b.slice(12));   // 64:ff9b::/96 (NAT64)
  if (b[0] === 0x20 && b[1] === 0x02) return classify4(b.slice(2, 6));         // 2002::/16 (6to4)
  if (b[0] === 0x20 && b[1] === 0x01 && b[2] === 0 && b[3] === 0) return 'private';   // 2001::/32 (Teredo: the IPv4 inside is obfuscated)
  if (b[0] === 0xfe && (b[1] & 0xc0) === 0x80) return 'link-local';           // fe80::/10
  if (b[0] === 0xfe && (b[1] & 0xc0) === 0xc0) return 'private';              // fec0::/10 (site-local, deprecated)
  if ((b[0] & 0xfe) === 0xfc) return 'private';                               // fc00::/7
  if (b[0] === 0xff) return 'private';                                        // ff00::/8 multicast
  if (b[0] === 0x01 && zero(1, 8)) return 'private';                          // 100::/64 (discard)
  return 'public';
}
let LOCAL_ORIGINS = new Set();   // host:port of the scan targets that are on this machine
const vetted = new Map();        // hostname -> Promise<string[]> of addresses, or a rejection
export function vetHost(hostname) {
  const h = bare(hostname);
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
// One request's verdict: scheme allowlist, then (for loopback) the exact-origin rule, then the address checks.
export async function vetUrl(raw) {
  const u = new URL(raw);
  if (u.protocol === 'data:' || u.protocol === 'blob:' || u.protocol === 'about:') return;
  if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new Error('scheme ' + u.protocol + ' is not allowed');
  if (isLocalName(u.hostname)) {
    if (!LOCAL_ORIGINS.has(u.host)) throw new Error('loopback ' + u.host + ' is not one of the origins being scanned');
    return;
  }
  await vetHost(u.hostname);
}
// Kept for the crawler: the URL the browser finally landed on must not be link-local. (vetHost does the real work; this is the cheap final check.)
export function landedOnLinkLocal(u) {
  try { const h = bare(new URL(u).hostname); return classify(h) === 'link-local' || h === 'metadata.google.internal'; } catch { return false; }
}
const hostsOf = (d) => (d && d.urls ? [...new Set(Object.values(d.urls).map(u => new URL(u).hostname))] : []);
const originsOf = (d) => (d && d.urls ? [...new Set(Object.values(d.urls).map(u => new URL(u).host))] : []);

// ---- Browser launch --------------------------------------------------------------------------------------------------------------------------
// The Chromium sandbox is ON unless you set A11Y_NO_SANDBOX=1. Containers and some CI images cannot create it, and then the launch fails with a message
// that says so; turn it off only for content you trust, because a page that escapes an unsandboxed Chromium runs as you.
const BASE_ARGS = ['--disable-gpu', '--mute-audio', '--use-gl=swiftshader'];
// Say which pages are being scanned, so loopback is allowed at exactly their origins and nowhere else. launchBrowser does this too; the crawler calls it first
// because it checks the start URL before it launches anything.
export function declareTargets(d) {
  LOCAL_ORIGINS = new Set(originsOf(d).filter(o => isLocalName(o.replace(/:\d+$/, '').replace(/^\[|\]$/g, ''))));
}
export async function launchBrowser(puppeteer, d) {
  const hosts = hostsOf(d);
  declareTargets(d);
  const args = [...BASE_ARGS];
  const rules = [];
  for (const h of hosts) {
    const addrs = await vetHost(h);
    const v4 = addrs.find(x => net.isIPv4(x));
    if (!isLocalName(h) && !net.isIP(h) && v4) rules.push('MAP ' + h + ' ' + v4);
  }
  if (rules.length) args.push('--host-resolver-rules=' + rules.join(','));
  const noSandbox = process.env.A11Y_NO_SANDBOX === '1';
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
      try { await vetUrl(r.url()); await r.continue(); }
      catch (e) { try { await r.abort('blockedbyclient'); } catch (_) {} }
    });
    try {   // the interception above cannot see WebSockets or service-worker traffic: block both at the protocol level
      const c = await page.createCDPSession();
      await c.send('Network.enable');
      await c.send('Network.setBypassServiceWorker', { bypass: true });
      await c.send('Network.setBlockedURLs', { urls: ['ws://*', 'wss://*', 'ftp://*', 'file://*'] });
    } catch (e) { console.error('warning: could not apply the WebSocket and service-worker block: ' + String(e.message).slice(0, 120)); }
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
