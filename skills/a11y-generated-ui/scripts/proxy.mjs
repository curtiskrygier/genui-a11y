// A small local vetting proxy. The browser is started with --proxy-server pointing here and --proxy-bypass-list=<-loopback> (so loopback is NOT exempt),
// which sends every connection Chromium makes over TCP through this one place: page loads, subresources, WebSockets, SharedWorker and ServiceWorker
// fetches, and the browser's own background requests. Each request is checked with the same rules as the in-page guard (vetUrl), and the connection
// is made to the address that vetHost checked and cached, so the address checked is the address used (that closes the DNS-rebinding gap for every host).
// It does not cover UDP (WebRTC / STUN and QUIC); lib.mjs switches those off with browser flags.
import http from 'node:http';
import net from 'node:net';

const hostPort = (s) => {                         // 'host:443' or '[::1]:80' -> { host, port }
  const m = String(s).match(/^\[([^\]]+)\]:(\d+)$/) || String(s).match(/^([^:]+):(\d+)$/);
  return m ? { host: m[1], port: +m[2] } : null;
};

export async function startVettingProxy({ vetUrl, vetHost, blockAll = false, log = () => {} }) {
  const blocked = [];
  // Resolve and vet one destination; returns the addresses to connect to, or throws.
  async function allow(scheme, host, port) {
    if (blockAll) throw new Error('no network is allowed in this mode');
    const shown = host.includes(':') ? '[' + host + ']' : host;
    await vetUrl(scheme + '://' + shown + ':' + port + '/');
    return vetHost(host);
  }
  function connectAny(addrs, port) {              // try each vetted address in order
    return new Promise((resolve, reject) => {
      const tryNext = (i) => {
        if (i >= addrs.length) return reject(new Error('could not connect'));
        const s = net.connect({ host: addrs[i], port });
        s.once('connect', () => { s.removeAllListeners('error'); resolve(s); });
        s.once('error', () => { s.destroy(); tryNext(i + 1); });
      };
      tryNext(0);
    });
  }
  const refuse = (what, e) => { blocked.push(what); log('blocked ' + what + ': ' + String(e.message).slice(0, 120)); };

  const server = http.createServer(async (req, res) => {       // plain http:// through the proxy: the request line carries an absolute URL
    let u;
    try { u = new URL(req.url); } catch (e) { res.writeHead(400).end(); return; }
    try {
      const addrs = await allow(u.protocol === 'https:' ? 'https' : 'http', u.hostname.replace(/^\[|\]$/g, ''), +u.port || 80);
      const sock = await connectAny(addrs, +u.port || 80);
      const headers = { ...req.headers }; delete headers['proxy-connection']; delete headers['proxy-authorization'];
      const up = http.request({ createConnection: () => sock, method: req.method, path: u.pathname + u.search, headers });
      up.on('response', (r) => { res.writeHead(r.statusCode, r.headers); r.pipe(res); });
      up.on('error', () => { try { res.writeHead(502).end(); } catch (_) {} });
      req.pipe(up);
    } catch (e) { refuse(req.url, e); try { res.writeHead(403).end('blocked by the scan proxy'); } catch (_) {} }
  });
  server.on('connect', async (req, client, head) => {            // CONNECT host:port: https:// and wss:// and (in Chromium) ws:// too
    const hp = hostPort(req.url);
    client.on('error', () => {});
    try {
      if (!hp) throw new Error('bad CONNECT target');
      const addrs = await allow(hp.port === 443 ? 'https' : 'http', hp.host, hp.port);
      const sock = await connectAny(addrs, hp.port);
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head && head.length) sock.write(head);
      sock.pipe(client); client.pipe(sock);
      sock.on('error', () => client.destroy()); client.on('close', () => sock.destroy()); sock.on('close', () => client.destroy());
    } catch (e) { refuse(req.url, e); try { client.end('HTTP/1.1 403 Forbidden\r\n\r\n'); } catch (_) {} }
  });
  server.on('upgrade', async (req, client, head) => {            // a WebSocket upgrade sent as a plain proxied request, if a browser ever does that
    client.on('error', () => {});
    try {
      const u = new URL(req.url);
      const port = +u.port || 80;
      const addrs = await allow('http', u.hostname.replace(/^\[|\]$/g, ''), port);
      const sock = await connectAny(addrs, port);
      const hdr = Object.entries(req.headers).map(([k, v]) => k + ': ' + v).join('\r\n');
      sock.write(req.method + ' ' + u.pathname + u.search + ' HTTP/1.1\r\n' + hdr + '\r\n\r\n');
      if (head && head.length) sock.write(head);
      sock.pipe(client); client.pipe(sock);
      sock.on('error', () => client.destroy()); client.on('close', () => sock.destroy());
    } catch (e) { refuse(req.url, e); try { client.end('HTTP/1.1 403 Forbidden\r\n\r\n'); } catch (_) {} }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  server.unref();
  return { port: server.address().port, blocked, close: () => { try { server.closeAllConnections(); server.close(); } catch (_) {} } };
}
