"""Browser-level egress test. A page served from a NON-loopback address of this machine (a scanned remote page, as far as the guard can tell) tries every
way it knows to reach a "localhost service" on another port: image, fetch, beacon, iframe, WebSocket, EventSource, a dedicated worker, a SharedWorker,
WebRTC (STUN over UDP) and WebTransport (QUIC over UDP). The test asserts that the listeners saw NOTHING. It first proves the probe page really ran
(it must reach its own origin), because a probe that never ran also sees nothing. Skipped when there is no browser or no non-loopback IPv4 address."""
import json, os, re, socket, socketserver, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
SCRIPTS = HERE / 'scripts'
browser = pytest.mark.skipif(not (SCRIPTS / 'node_modules').exists(), reason='run npm ci in scripts/')


def non_loopback_ipv4():
    out = subprocess.run(['ip', '-4', '-o', 'addr', 'show'], capture_output=True, text=True).stdout if os.path.exists('/usr/bin/ip') or os.path.exists('/sbin/ip') else ''
    for m in re.finditer(r'inet (\d+\.\d+\.\d+\.\d+)', out):
        if not m.group(1).startswith('127.'):
            return m.group(1)
    return None


class Tcp(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def tcp_listener(seen):
    class H(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(1)
            try:
                seen.append(self.request.recv(200).split(b'\r\n')[0].decode('latin1') or '(connection)')
            except Exception:
                seen.append('(connection)')
    s = Tcp(('0.0.0.0', 0), H)      # all IPv4 addresses, so that 127.0.0.2 and 0.0.0.0 (which the kernel routes here) reach it too
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


HOSTS = ['127.0.0.1', '0.0.0.0', '0', '[::]', '[::1]', '[::ffff:127.0.0.1]', '127.0.0.2', '127.1', '0x7f.1', '2130706433']

PROBE = """<!doctype html><html lang="en"><head><title>probe</title></head><body><main><p>probe</p></main><script>
const go = (f) => { try { const r = f(); if (r && r.catch) r.catch(() => {}); } catch (e) {} };
go(() => fetch('/alive'));                                    // control: the page reached its own origin
go(() => fetch('/slow'));                                     // keeps the page "busy" so the scan waits while the probes run
// every spelling of "this machine" that the kernel routes to localhost, with A11Y_ALLOW_PRIVATE=1 set (the R3 roast found 0.0.0.0 and 0 got through)
for (const H of %(hosts)s) {
const T = 'http://' + H + ':%(tcp)d', W = 'ws://' + H + ':%(tcp)d';
go(() => { new Image().src = T + '/img'; });
go(() => fetch(T + '/fetch', { mode: 'no-cors' }));
go(() => navigator.sendBeacon(T + '/beacon', 'x'));
go(() => { const f = document.createElement('iframe'); f.src = T + '/iframe'; document.body.appendChild(f); });
go(() => new WebSocket(W + '/ws'));
go(() => new EventSource(T + '/sse'));
go(() => new Worker(URL.createObjectURL(new Blob(["fetch('" + T + "/worker', {mode:'no-cors'}).catch(()=>{});"]))));
go(() => new SharedWorker(URL.createObjectURL(new Blob(["fetch('" + T + "/sharedworker', {mode:'no-cors'}).catch(()=>{}); new WebSocket('" + W + "/sharedworker-ws')"]))));
}
go(() => new Worker(URL.createObjectURL(new Blob(["try { new WebTransport('https://127.0.0.1:%(udp)d/wtw').ready.catch(()=>{}) } catch (e) {}"]))));
go(() => { const p = new RTCPeerConnection({ iceServers: [{ urls: 'stun:127.0.0.1:%(udp)d' }] }); p.createDataChannel('x'); return p.createOffer().then(o => p.setLocalDescription(o)); });
go(() => new WebTransport('https://127.0.0.1:%(udp)d/wt').ready);
</script></body></html>"""


@browser
@pytest.mark.parametrize('where', ['lan', 'loopback'])
def test_a_scanned_page_cannot_reach_a_local_service(where):
    ip = non_loopback_ipv4() if where == 'lan' else '127.0.0.1'      # a scanned remote page, and a scan of one local port that must not reach another
    if not ip:
        pytest.skip('no non-loopback IPv4 address on this machine')
    tcp_seen, udp_seen, own = [], [], []
    tcp = tcp_listener(tcp_seen)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); udp.bind(('127.0.0.1', 0)); udp.settimeout(0.2)
    stop = threading.Event()

    def udp_loop():
        while not stop.is_set():
            try:
                udp_seen.append(udp.recvfrom(2000)[1])
            except socket.timeout:
                pass
            except OSError:
                return
    threading.Thread(target=udp_loop, daemon=True).start()
    for h in ('0.0.0.0', '127.0.0.2'):      # control: on this kernel these names really do reach the listener, so a clean result below means the guard held
        c = socket.create_connection((h, tcp.server_address[1]), timeout=2); c.sendall(b'GET /control HTTP/1.0\r\n\r\n'); c.close()
    deadline = time.time() + 3
    while len(tcp_seen) < 2 and time.time() < deadline:
        time.sleep(0.05)
    assert len(tcp_seen) == 2, 'the listener is not reachable through 0.0.0.0 / 127.0.0.2 here, so the probe would prove nothing'
    tcp_seen.clear()
    page = (PROBE % {'tcp': tcp.server_address[1], 'udp': udp.getsockname()[1], 'hosts': json.dumps(HOSTS)}).encode()

    class Page(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            own.append(self.path)
            if self.path == '/slow':
                time.sleep(3)
            body = page if self.path in ('/', '/index.html') else b'ok'
            self.send_response(200); self.send_header('Content-Type', 'text/html' if body is page else 'text/plain'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    srv = ThreadingHTTPServer((ip, 0), Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        env = dict(os.environ, A11Y_ALLOW_PRIVATE='1', A11Y_NAV_TIMEOUT='20000', A11Y_JOB_TIMEOUT='120')
        r = subprocess.run([sys.executable, str(SCRIPTS / 'ratchet.py'), '--url', f'http://{ip}:{srv.server_address[1]}/', *(['--confirm-permission'] if where == 'lan' else []), '--report'],
                           capture_output=True, text=True, timeout=180, env=env)
        time.sleep(1)
    finally:
        stop.set(); srv.shutdown(); tcp.shutdown(); udp.close()
    assert '/alive' in own, 'the probe page never ran, so the test proves nothing:\n' + r.stdout + r.stderr
    assert (tcp_seen, udp_seen) == ([], []), f'a scanned page reached a local service. TCP (WebSocket, SharedWorker, fetch ...): {tcp_seen}; UDP datagrams (WebRTC, WebTransport): {len(udp_seen)}'
