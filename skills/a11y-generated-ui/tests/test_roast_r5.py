"""Fixes from the fifth roast (October 2026). Real-Chromium tests are skipped without node_modules."""
import json, os, re, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
SCRIPTS = HERE / 'scripts'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_roast_r3 import stub_node, ratchet, alive    # noqa: E402

REAL = pytest.mark.skipif(not (SCRIPTS / 'node_modules').exists() or not os.path.exists(os.environ.get('CHROMIUM', '/usr/bin/chromium')), reason='needs node_modules and Chromium')

BAD = "document.querySelector('main').insertAdjacentHTML('beforeend','<img src=data:image/gif;base64,R0lGODlhAQABAAAAACw= ><button></button>')"
LATE = {
    'fetch3': f"<script>fetch('/slow?3').then(r=>r.text()).then(()=>{{{BAD}}})</script>",
    'chain2x2': f"<script>fetch('/slow?2').then(()=>fetch('/slow?2')).then(()=>{{{BAD}}})</script>",
    'timer2': f"<script>setTimeout(()=>{{{BAD}}},2000)</script>",
    'timer5': f"<script>setTimeout(()=>{{{BAD}}},5000)</script>",
    'sse': '<script>new EventSource("/events")</script>',
    'imgs': ''.join(f'<img alt="" src="/never{i}">' for i in range(6)),
}


class Late(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        p = self.path
        try:
            if p.startswith('/events'):
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                while True: self.wfile.write(b'data: x\n\n'); self.wfile.flush(); time.sleep(1)
            if p.startswith('/never'):
                time.sleep(120); return
            if p.startswith('/slow'):
                time.sleep(float(p.split('?')[1])); b = b'ok'
                self.send_response(200); self.send_header('Content-Type', 'text/plain'); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b); return
            name = p.strip('/')
            body = f'<!doctype html><html lang="en"><head><title>{name}</title></head><body><main><h1>{name}</h1>{LATE.get(name, "")}</main></body></html>'.encode()
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        except OSError:
            return


@pytest.fixture
def late_site():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Late); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()


# ---- 1. content that renders late is audited; streams and hanging images still end the wait --------------------------------------------------

@REAL
def test_late_rendered_content_is_audited_and_streams_still_finish(tmp_path, late_site):
    urls = tmp_path / 'urls.txt'; urls.write_text(''.join(f'{late_site}/{n}\n' for n in LATE))
    out = tmp_path / 'audit.json'
    env = dict(os.environ, A11Y_JOB_TIMEOUT='200')
    t0 = time.time()
    r = ratchet(env, '--urls', str(urls), '--score', '--audit-out', str(out), timeout=240)
    took = time.time() - t0
    assert 'STOPPED' not in r.stderr + r.stdout, r.stderr
    audit = json.load(open(out))['audit']
    seen = {k.rsplit('/', 1)[-1]: {x['id'] for x in v.get('v', [])} for k, v in audit.items()}
    for n in ('fetch3', 'chain2x2', 'timer2', 'timer5'):
        assert {'image-alt', 'button-name'} <= seen[n], f'{n}: the late barrier was not audited ({seen[n]})'
    assert took < 90, f'the run took {took:.0f} s (job timeout 200)'
    assert 'imgs' in r.stderr and 'never went idle' in r.stderr, r.stderr            # the never-quiet page is still named


@REAL
def test_settle_ms_is_settable(tmp_path, late_site):
    # a quiet window of 0 and a page with nothing pending: the run must not wait the default window (a timer 2 s out is still pending, so use /sse)
    urls = tmp_path / 'urls.txt'; urls.write_text(f'{late_site}/sse\n')
    t0 = time.time()
    r = ratchet(dict(os.environ, A11Y_SETTLE_MS='0', A11Y_JOB_TIMEOUT='60'), '--urls', str(urls), '--score', timeout=90)
    assert r.returncode == 0, r.stderr
    assert time.time() - t0 < 20


def test_idle_and_settle_variables_are_documented():
    for f in (REPO / 'README.md', HERE / 'SKILL.md'):
        t = f.read_text()
        assert 'A11Y_IDLE_TIMEOUT' in t and 'A11Y_SETTLE_MS' in t, f


# ---- 2. the R4 minors --------------------------------------------------------------------------------------------------------------------------

def test_sigterm_removes_the_run_directory(tmp_path):
    # the MCP server's timeout sends SIGTERM and ratchet leaves through os._exit: the run's temp dir (scanned URLs, audit.json) must not stay behind
    import signal
    tmp = tmp_path / 'tmp'; tmp.mkdir()
    env = stub_node(tmp_path, 'sleep 60\n'); env['TMPDIR'] = str(tmp)
    items = tmp_path / 'items.json'; items.write_text(json.dumps({'a': '<p>x</p>'}))
    p = subprocess.Popen([sys.executable, str(SCRIPTS / 'ratchet.py'), '--items', str(items), '--score'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if list(tmp.glob('*/html.json')): break
            time.sleep(0.1)
        assert list(tmp.glob('*/html.json')), 'the run never started'
        time.sleep(0.5)
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=20)
    finally:
        if p.poll() is None: p.kill()
    assert not list(tmp.iterdir()), list(tmp.iterdir())


def test_a_sitemap_does_not_widen_the_scan_to_another_port_on_the_same_host(tmp_path):
    class Sm(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            port = self.server.server_address[1]
            body = f'<urlset><url><loc>http://127.0.0.1:{port}/a</loc></url><url><loc>http://127.0.0.1:{port + 1}/other</loc></url></urlset>'.encode()
            self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Sm)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    env = stub_node(tmp_path, f'cp "$2/html.json" {tmp_path}/html.copy\necho \'{json.dumps({"/a": {"v": [], "p": []}})}\' > "$2/audit.json"\n')
    try:
        r = ratchet(env, '--sitemap', f'http://127.0.0.1:{port}/sitemap.xml', '--score')
    finally:
        srv.shutdown()
    urls = json.loads((tmp_path / 'html.copy').read_text())['urls']
    assert list(urls.values()) == [f'http://127.0.0.1:{port}/a'], (urls, r.stderr)
    assert 'skipped 1' in r.stderr and str(port + 1) in r.stderr, r.stderr


def test_a_crashing_crosscheck_report_has_its_own_exit_code(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPTS / 'crosscheck_report.py'), str(tmp_path)], capture_output=True, text=True)   # no audit.json: it crashes
    assert r.returncode == 2, (r.returncode, r.stderr[-300:])          # 0 = no agreement, 1 = engines agree on a finding, 2 = the comparison itself failed
    assert 'Traceback' in r.stderr or 'Error' in r.stderr


def test_json_with_baseline_includes_the_ratchet_result(tmp_path):
    items = tmp_path / 'items.json'; items.write_text(json.dumps({'a': '<p>x</p>'}))
    base = tmp_path / 'base.json'; base.write_text(json.dumps({'axe': {}, 'static': {}}))
    audit = {'a': {'v': [{'id': 'image-alt', 'nodes': 1, 'impact': 'critical', 'help': 'h', 'url': 'u', 'pairs': []}], 'p': []}}
    from test_roast_r3 import audit_node
    r = ratchet(audit_node(tmp_path, audit), '--items', str(items), '--score', '--json', '--min-score', '0', '--baseline', str(base))
    rep = json.loads(r.stdout)
    assert rep['ratchet']['new'] and 'image-alt' in rep['ratchet']['new'][0], rep.get('ratchet')
    assert rep['ratchet']['fixed'] == [] and rep['ratchet']['exit'] == 1 and r.returncode == 1, (rep.get('ratchet'), r.returncode)


def test_tabwalk_count_wording_says_what_it_counts(tmp_path):
    tw = {'a': {'stops': [], 'findings': {}, 'composite_unreached': 0, 'detail': []}}
    env = stub_node(tmp_path, f'echo \'{json.dumps(tw)}\' > "$2/tabwalk.json"\n')
    items = tmp_path / 'items.json'; items.write_text(json.dumps({'a': '<span onclick="go()">x</span>'}))
    r = ratchet(env, '--items', str(items), '--tabwalk')
    assert 'never reached' in r.stdout and 'ARIA' in r.stdout and 'static' in r.stdout, r.stdout     # a role-less clickable span is not counted; the static check covers it


def test_proc_reaping_is_documented_as_linux_only():
    assert re.search(r'/proc', (REPO / 'README.md').read_text()) and re.search(r'Linux', (REPO / 'README.md').read_text())
    assert 'crosscheck_report' in (REPO / 'README.md').read_text() or 'exit 2' in (REPO / 'README.md').read_text()
