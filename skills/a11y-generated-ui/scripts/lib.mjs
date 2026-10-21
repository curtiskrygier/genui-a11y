// Shared by the engine scripts. Two modes: FRAGMENTS (html.json {html:{name:html}}: each fragment is put on a clean page inside the host's
// stylesheet, with the network blocked so results are deterministic) and LIVE (html.json {urls:{name:url}}: each real page is loaded with its
// own CSS and scripts, and the dark theme is requested with prefers-color-scheme).
import fs from 'node:fs';
import dns from 'node:dns/promises';
import net from 'node:net';
import { startVettingProxy } from './proxy.mjs';
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
//   * only http, https, data, blob and about URLs are allowed; file/ftp URLs are blocked, and service workers are bypassed;
//   * ALL browser TCP traffic, including WebSockets (ws/wss, which have no CORS) and SharedWorker / Worker fetches, goes through a local vetting proxy
//     (proxy.mjs) that applies the rules above to every connection and connects to the address it checked. WebRTC (UDP) is disabled with
//     --webrtc-ip-handling-policy=disable_non_proxied_udp and QUIC with --disable-quic. See the README for what is and is not covered.
// Addresses are parsed to bytes, and every form that embeds an IPv4 address (IPv4-mapped, NAT64, 6to4, IPv4-compatible) is classified by the IPv4
// inside it. Anything that cannot be parsed is treated as not public.
// Each host is resolved once (vetHost) and the proxy connects to exactly the addresses that were checked, for the starting page, redirects and
// subresources alike, so the address checked is the address used. Chromium does not resolve names itself when it uses a fixed proxy. For untrusted
// sites still scan from a container with no sensitive network access.
const LOCAL_NAMES = new Set(['localhost', '127.0.0.1', '::1']);
const bare = (h) => String(h).replace(/^\[|\]$/g, '').toLowerCase();
export const isLocalName = (h) => LOCAL_NAMES.has(bare(h));
function classify4(o) {
  const [o1, o2, o3] = o;
  if (o1 === 127 || o1 === 0) return 'loopback';     // 0.0.0.0/8 too: on Linux a connection to 0.0.0.0 (or "0") reaches this machine's own services
  if (o1 === 169 && o2 === 254) return 'link-local';
  if (o1 === 10 || (o1 === 172 && o2 >= 16 && o2 <= 31) || (o1 === 192 && o2 === 168) || (o1 === 100 && o2 >= 64 && o2 <= 127)
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
let LOCAL_ORIGINS = new Set();   // host:port of the scan targets that are on this machine (the port is always spelled out: 80 and 443 are different ports)
const effPort = (u) => u.port || (u.protocol === 'https:' ? '443' : '80');   // URL.host drops a default port, so http://h/ and https://h:443/ would otherwise look the same as, or differ from, the wrong thing
const hostKey = (u) => bare(u.hostname) + ':' + effPort(u);
let activeProxy = null;          // the vetting proxy of the running browser, so a page's sockets can be torn down when the page is done
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
    if (!LOCAL_ORIGINS.has(hostKey(u))) throw new Error('loopback ' + u.host + ' is not one of the origins being scanned');
    return;
  }
  await vetHost(u.hostname);
}
// Kept for the crawler: the URL the browser finally landed on must not be link-local. (vetHost does the real work; this is the cheap final check.)
export function landedOnLinkLocal(u) {
  try { const h = bare(new URL(u).hostname); return classify(h) === 'link-local' || h === 'metadata.google.internal'; } catch { return false; }
}
const hostsOf = (d) => (d && d.urls ? [...new Set(Object.values(d.urls).map(u => new URL(u).hostname))] : []);
const originsOf = (d) => (d && d.urls ? [...new Set(Object.values(d.urls).map(u => new URL(u)))].map(u => ({ name: bare(u.hostname), key: hostKey(u) })) : []);

// ---- Browser launch --------------------------------------------------------------------------------------------------------------------------
// The Chromium sandbox is ON unless you set A11Y_NO_SANDBOX=1. Containers and some CI images cannot create it, and then the launch fails with a message
// that says so; turn it off only for content you trust, because a page that escapes an unsandboxed Chromium runs as you.
// The second line switches off Chromium's own background traffic (component and safe-browsing updates, pings, domain reliability, sync), which the proxy
// would otherwise refuse and log as "blocked google.com" on every start. None of it is part of the page being scanned.
const BASE_ARGS = ['--disable-gpu', '--mute-audio', '--use-gl=swiftshader',
  '--disable-background-networking', '--disable-component-update', '--no-pings', '--disable-domain-reliability', '--disable-sync', '--disable-client-side-phishing-detection', '--no-default-browser-check', '--no-first-run',
  '--disable-features=NetworkTimeServiceQuerying,OptimizationHints,Translate,MediaRouter,AutofillServerCommunication'];
// Say which pages are being scanned, so loopback is allowed at exactly their origins and nowhere else. launchBrowser does this too; the crawler calls it first
// because it checks the start URL before it launches anything.
export function declareTargets(d) {
  LOCAL_ORIGINS = new Set(originsOf(d).filter(o => isLocalName(o.name)).map(o => o.key));
}
export async function launchBrowser(puppeteer, d) {
  const hosts = hostsOf(d);
  declareTargets(d);
  const args = [...BASE_ARGS];
  for (const h of hosts) await vetHost(h);           // refuse a bad target before anything starts (the proxy resolves again from this cache, so the address checked is the address used)
  // ALL browser egress goes through a local vetting proxy (proxy.mjs). <-loopback> removes the browser's built-in exemption for localhost, so even
  // 127.0.0.1 traffic is checked. This is what covers WebSockets, SharedWorkers and ServiceWorkers, which the in-page interception cannot see.
  // Fragment mode has no live pages, so the proxy there refuses everything.
  const proxy = await startVettingProxy({ vetUrl, vetHost, blockAll: !d.urls, log: (m) => console.error('scan proxy: ' + m) });
  activeProxy = proxy;
  args.push('--proxy-server=http://127.0.0.1:' + proxy.port, '--proxy-bypass-list=<-loopback>');
  // UDP does not go through an HTTP proxy. WebRTC (STUN/ICE) is told to use no UDP that is not proxied (measured: a STUN probe to a local UDP port sent 5
  // datagrams without this flag and 0 with it; --force-webrtc-ip-handling-policy did NOT stop it). WebTransport (QUIC) is removed in prepare().
  args.push('--webrtc-ip-handling-policy=disable_non_proxied_udp', '--disable-quic');
  const profile = process.env.A11Y_USER_DATA_DIR;      // set by ratchet.py: a directory unique to the run, so a timeout can find and stop this Chromium
  if (profile) args.push('--user-data-dir=' + profile);
  const noSandbox = process.env.A11Y_NO_SANDBOX === '1';
  if (noSandbox) args.push('--no-sandbox');
  try {
    const browser = await puppeteer.launch({ executablePath: process.env.CHROMIUM || '/usr/bin/chromium', headless: 'new', args });
    const close = browser.close.bind(browser);
    browser.close = async () => { try { await Promise.race([close(), new Promise(r => setTimeout(r, 10000))]); } finally { proxy.close(); } };   // proxy.close() also destroys sockets a page left open
    for (const sig of ['SIGTERM', 'SIGINT']) process.once(sig, () => { browser.close().catch(() => {}).finally(() => process.exit(130)); });   // stopped from outside: take the browser down with us
    try { console.error('browser: ' + await browser.version()); } catch (_) {}   // the Chromium version the results came from (tested on 153)
    return browser;
  } catch (e) {
    proxy.close();
    throw new Error(String(e.message).slice(0, 300) + (noSandbox ? '' : '\n(Chromium could not start with its sandbox. In a container or CI set A11Y_NO_SANDBOX=1, and only when scanning content you trust.)'));
  }
}

export const readInput = (dir) => JSON.parse(fs.readFileSync(dir + '/html.json', 'utf8'));
export const namesOf = (d) => Object.keys(d.urls || d.html);
export const rootSel = (d) => (d.urls ? 'body' : 'main');
export async function prepare(page, d) {
  await page.setViewport({ width: 900, height: 700 });
  // WebTransport speaks QUIC over UDP, straight from the browser, so the proxy never sees it and no Chromium flag turns it off (measured). Remove it from
  // every page and iframe. Not covered: a WebTransport opened from inside a Worker (see the README).
  await page.evaluateOnNewDocument(() => { try { Object.defineProperty(window, 'WebTransport', { value: undefined, configurable: false, writable: false }); } catch (e) {} });
  if (d.urls) {
    await page.setRequestInterception(true);
    page.on('request', async (r) => {
      try { await vetUrl(r.url()); await r.continue(); }
      catch (e) { try { await r.abort('blockedbyclient'); } catch (_) {} }
    });
    try {   // service workers would answer from their own cache and fetch through their own path: bypass them (WebSockets and workers are covered by the proxy, not here)
      const c = await page.createCDPSession();
      await c.send('Network.enable');
      await c.send('Network.setBypassServiceWorker', { bypass: true });
    } catch (e) { console.error('warning: could not bypass service workers: ' + String(e.message).slice(0, 120)); }
  } else {
    await page.setRequestInterception(true);
    page.on('request', r => (r.url().startsWith('data:') || r.url().startsWith('about:')) ? r.continue() : r.abort());   // offline, deterministic
  }
}
// One page load with two bounds. The navigation itself (until the DOM is parsed) must finish within A11Y_NAV_TIMEOUT, else the page is NOT AUDITED with
// "Navigation timeout" (it hit the deadline). After that the page gets A11Y_IDLE_TIMEOUT (default 15 s) to settle (at most 2 requests in flight, like
// networkidle2); a page that never settles because of an SSE stream, long poll or never-answered image is audited as it stands and marked slow, not failed.
// Before every page the previous one is cancelled and the proxy drops its sockets, so a hanging request of page N cannot hold page N+1 or the exit.
export async function go(page, url) {
  const nav = +(process.env.A11Y_NAV_TIMEOUT || 40000), idle = +(process.env.A11Y_IDLE_TIMEOUT || 15000);
  page._a11ySlow = 0;
  if (activeProxy) { try { await page.goto('about:blank', { timeout: 5000 }); } catch (_) {} activeProxy.dropAll(); }
  const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: nav });
  const t0 = Date.now();
  try { await page.waitForNetworkIdle({ idleTime: 500, concurrency: 2, timeout: Math.min(nav, idle) }); }
  catch (e) { page._a11ySlow = Math.round((Date.now() - t0) / 1000); }
  return resp;
}
// kind: 'audit' | 'cross' | 'tab' (the small differences between the three scripts' wrapper pages)
export async function open(page, d, t, { shell, dark, kind }) {
  if (d.urls) {
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: dark ? 'dark' : 'light' }]);
    if (dark && (DARK_ATTR || DARK_STORE)) {
      const [ak, av] = DARK_ATTR.split('='), [sk, sv] = DARK_STORE.split('=');
      await page.evaluateOnNewDocument((ak, av, sk, sv) => { try { if (sk) localStorage.setItem(sk, sv || 'dark'); } catch (e) {} if (ak) document.documentElement.setAttribute(ak, av || 'dark'); }, ak, av, sk, sv);
    }
    await go(page, d.urls[t]);
    if (landedOnLinkLocal(page.url())) throw new Error('redirected to a link-local or metadata address: not audited');
    if (dark && DARK_ATTR) { const [k, v] = DARK_ATTR.split('='); await page.evaluate((k, v) => document.documentElement.setAttribute(k, v), k, v || 'dark'); }
    return;
  }
  const body = kind === 'tab' ? 'margin:0;background:var(--bg,#fff)' : 'margin:0;background:var(--bg,#fff);color:var(--text,#111)';
  const wrap = kind === 'tab' ? '<main style="padding:16px">' : '<main>';
  await page.setContent('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title><style>' + shell + '</style></head><body class="' + (dark ? DARK : '') + '" style="' + body + '">' + wrap + d.html[t] + '</main></body></html>',
    kind === 'tab' ? { waitUntil: 'load' } : { waitUntil: 'domcontentloaded', timeout: 20000 });
}
