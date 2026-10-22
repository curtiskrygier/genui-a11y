"""Fixes from the sixth roast (October 2026). Real-Chromium tests are skipped without node_modules."""
import json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
SCRIPTS = HERE / 'scripts'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_roast_r3 import ratchet    # noqa: E402

REAL = pytest.mark.skipif(not (SCRIPTS / 'node_modules').exists() or not os.path.exists(os.environ.get('CHROMIUM', '/usr/bin/chromium')), reason='needs node_modules and Chromium')

BAR = "<img src=data:image/gif;base64,R0lGODlhAQABAAAAACw= ><button></button>"
LATE = "document.querySelector('main').insertAdjacentHTML('beforeend','" + BAR + "')"
MOVING = {
    'interval50': BAR + "<div id=b>x</div><script>let i=0;setInterval(()=>{document.getElementById('b').style.transform='translateX('+(i++%100)+'px)'},50)</script>",
    'clock1s': BAR + "<p id=c></p><script>setInterval(()=>{document.getElementById('c').textContent=new Date().toISOString()},1000)</script>",
    'carousel_to5': BAR + "<div id=s class=a>slide</div><script>(function n(){document.getElementById('s').classList.toggle('a');setTimeout(n,5000)})()</script>",
    'clock_late3': "<p id=c></p><script>setInterval(()=>{document.getElementById('c').textContent=new Date().toISOString()},1000);fetch('/slow?3').then(()=>{" + LATE + "})</script>",
    'hang': BAR + '<img alt="" src="/never">',
}


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        p = self.path
        try:
            if p.startswith('/never'):
                time.sleep(60); return
            if p.startswith('/slow'):
                time.sleep(float(p.split('?')[1]))
                self.send_response(200); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'ok'); return
            name = p.strip('/') or 'index'
            links = ''.join(f'<a href="/{n}">{n}</a>' for n in MOVING) if name == 'index' else ''
            body = f'<!doctype html><html lang="en"><head><title>{name}</title></head><body><main><h1>{name}</h1>{links}{MOVING.get(name, "")}</main></body></html>'.encode()
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        except OSError:
            return


@pytest.fixture
def site():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Site); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()


@REAL
def test_motion_does_not_hold_the_wait_and_pages_slow_is_in_json(tmp_path, site):
    urls = tmp_path / 'urls.txt'; urls.write_text(''.join(f'{site}/{n}\n' for n in MOVING))
    out = tmp_path / 'audit.json'
    r = ratchet(dict(os.environ, A11Y_JOB_TIMEOUT='200'), '--urls', str(urls), '--json', '--audit-out', str(out), timeout=240)
    rep = json.loads(r.stdout)
    audit = json.load(open(out))['audit']
    for k, v in audit.items():
        assert {'image-alt', 'button-name'} <= {x['id'] for x in v.get('v', [])}, f'{k}: barrier not audited'
    assert list(rep['pages_slow']) == ['/hang'], rep['pages_slow']        # only the never-answered request waits the full bound
    assert rep['pages_deadline'] == []
    assert 'A11Y_IDLE_TIMEOUT' in r.stderr and '/hang (' in r.stderr, r.stderr


@REAL
def test_crawl_waits_less_than_the_audit(tmp_path, site):
    env = dict(os.environ, A11Y_JOB_TIMEOUT='200', A11Y_ALLOW_PRIVATE='1')
    t0 = time.time()
    r = ratchet(env, '--url', site + '/', '--crawl', '--max-pages', '6', '--json', timeout=240)
    took = time.time() - t0
    rep = json.loads(r.stdout)
    assert rep['pages_scanned'] == 6, r.stderr
    assert list(rep['pages_slow']) == ['/hang']
    assert took < 60, f'{took:.0f} s'        # crawl pays at most 3 s on /hang, the audit 10 s


def test_crawl_timeout_message_does_not_claim_no_pages(tmp_path):
    src = (SCRIPTS / 'ratchet.py').read_text()
    assert 'no pages were found' not in src
    assert 'stopped before it finished' in src


def test_nav_timeout_is_not_described_as_the_whole_page_load():
    for f in (REPO / 'README.md', HERE / 'SKILL.md'):
        t = f.read_text()
        row = next(l for l in t.splitlines() if '`A11Y_NAV_TIMEOUT`, `A11Y_AXE_TIMEOUT`' in l)
        assert 'per page load' not in row and 'DOM is parsed' in row, f
        assert 'A11Y_CRAWL_IDLE_TIMEOUT' in t and 'pages_slow' in t, f
