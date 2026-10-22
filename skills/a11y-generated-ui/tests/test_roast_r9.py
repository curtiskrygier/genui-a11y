"""Fixes from the ninth roast (October 2026): loops re-armed with a new arrow or .bind are activity, iframes' late content is waited for,
WebSocket subclasses work under the scan. Real-Chromium tests are skipped without node_modules."""
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
SCRIPTS = HERE / 'scripts'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_roast_r3 import ratchet    # noqa: E402

REAL = pytest.mark.skipif(not (SCRIPTS / 'node_modules').exists() or not os.path.exists(os.environ.get('CHROMIUM', '/usr/bin/chromium')), reason='needs node_modules and Chromium')

BAR = "<img src=data:image/gif;base64,R0lGODlhAQABAAAAACw= ><button></button>"
INS = "document.querySelector('main').insertAdjacentHTML('beforeend','" + BAR + "')"
# Round 10: one-shot renders 7-8 s after load whose timers share one line of code (a helper, a zone.js-style patch, await sleep()):
# they keep their own delays, so they are not a loop and must still be waited for.
HELPER = "<script>function later(f,ms){return setTimeout(f,ms)}</script>"
ZONE = "<script>(function(){const n=window.setTimeout;window.setTimeout=function(f,ms,...a){return n.call(window,function(){return f.apply(this,arguments)},ms,...a)}})()</script>"
SLEEP = "<script>const sleep=ms=>new Promise(r=>setTimeout(r,ms))</script>"
TOAST = "document.querySelector('main').insertAdjacentHTML('beforeend','<p>saved</p>')"
PAGES = {
    # React/class-style carousels: each re-arm passes a new arrow or a fresh .bind (R9: 21.7 s per page, all slow)
    'carousel_arrow': BAR + "<div id=s class=a>slide</div><script>function next(){s.classList.toggle('a');setTimeout(()=>next(),2000)}setTimeout(()=>next(),2000)</script>",
    'carousel_bind': BAR + "<div id=s class=a>slide</div><script>const o={go(){s.classList.toggle('a');setTimeout(this.go.bind(this),2000)}};setTimeout(o.go.bind(o),2000)</script>",
    # late content inside a same-origin iframe, 3 s after load
    'iframe_late': "<iframe title=f srcdoc=\"<main></main><script>setTimeout(()=>{document.querySelector('main').insertAdjacentHTML('beforeend','<img src=data:image/gif;base64,R0lGODlhAQABAAAAACw= ><button></button>')},3000)</script>\"></iframe>",
    # a chat client that subclasses WebSocket; the answer lands 2 s later
    'helper_toast_render8': HELPER + "<script>later(()=>{" + TOAST + "},300);later(()=>{" + INS + "},8000)</script>",
    'zone_toast_render7': ZONE + "<script>setTimeout(()=>{" + TOAST + "},300);setTimeout(()=>{" + INS + "},7000)</script>",
    'sleep_chain7_5': SLEEP + "<script>(async()=>{await sleep(1000);" + TOAST + ";await sleep(6500);" + INS + "})()</script>",
    'ws_subclass': "<script>class Chat extends WebSocket{constructor(u){super(u);this.addEventListener('message',()=>{" + INS + "})}}new Chat('ws://'+location.host+'/ws')</script>",
}


class P(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        import base64, hashlib, struct
        try:
            if self.path == '/ws':
                key = self.headers.get('Sec-WebSocket-Key', '')
                acc = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                self.send_response(101); self.send_header('Upgrade', 'websocket'); self.send_header('Connection', 'Upgrade'); self.send_header('Sec-WebSocket-Accept', acc); self.end_headers()
                self.wfile.flush(); time.sleep(2); self.wfile.write(b'\x81\x02hi'); self.wfile.flush(); time.sleep(20); return
            name = self.path.strip('/')
            b = f'<!doctype html><html lang="en"><head><title>{name}</title></head><body><main><h1>{name}</h1>{PAGES.get(name, "")}</main></body></html>'.encode()
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
        except OSError:
            return


@pytest.fixture
def site():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), P); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()


@REAL
def test_rearmed_carousels_iframe_late_content_and_websocket_subclass(tmp_path, site):
    urls = tmp_path / 'urls.txt'; urls.write_text(''.join(f'{site}/{n}\n' for n in PAGES))
    out = tmp_path / 'audit.json'
    t0 = time.time()
    r = ratchet(dict(os.environ, A11Y_JOB_TIMEOUT='200'), '--urls', str(urls), '--json', '--audit-out', str(out), timeout=240)
    took = time.time() - t0
    rep = json.loads(r.stdout)
    audit = json.load(open(out))['audit']
    missed = [k for k, v in audit.items() if not {'image-alt', 'button-name'} <= {x['id'] for x in v.get('v', [])}]
    assert not missed, (missed, r.stderr[-400:])
    assert not rep['pages_slow'], rep['pages_slow']            # the carousels are loops (activity), not pending one-shot timers
    assert took < 110, f'{took:.0f} s'
