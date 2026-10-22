"""Fixes from the fourth roast (October 2026). Stub-node tests need no browser; the real-Chromium tests are skipped without node_modules."""
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


class Page(BaseHTTPRequestHandler):
    """/ : an SSE stream. /imgs : 6 images that are never answered. /hang : an HTML page that is never answered."""
    def log_message(self, *a): pass
    def do_GET(self):
        p = self.path
        if p.startswith('/events'):
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
            try:
                while True: self.wfile.write(b'data: x\n\n'); self.wfile.flush(); time.sleep(1)
            except OSError: return
        if p.startswith('/never') or p == '/hang':
            time.sleep(120); return
        extra = '<script>new EventSource("/events")</script>' if p == '/' else ''.join(f'<img alt="" src="/never{i}">' for i in range(6)) if p == '/imgs' else ''
        body = f'<!doctype html><html lang="en"><head><title>t</title></head><body><main><h1>t</h1>{extra}</main></body></html>'.encode()
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers()
        try: self.wfile.write(body)
        except OSError: pass


@pytest.fixture
def site():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Page); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()


# ---- 1. one streaming or never-answered request must not hold the whole run ---------------------------------------------------------------------

@REAL
def test_an_sse_page_does_not_hold_the_run(site):
    env = dict(os.environ, A11Y_NAV_TIMEOUT='8000', A11Y_JOB_TIMEOUT='90')
    t0 = time.time()
    r = ratchet(env, '--url', site + '/', '--score', timeout=120)
    took = time.time() - t0
    assert 'STOPPED' not in r.stderr + r.stdout, r.stderr
    assert took < 45, f'the run took {took:.0f} s (job timeout 90)'
    assert r.returncode == 0, r.stderr


@REAL
def test_never_answered_pages_are_named_and_the_run_ends(tmp_path, site):
    urls = tmp_path / 'urls.txt'; urls.write_text(f'{site}/\n{site}/imgs\n{site}/hang\n')
    env = dict(os.environ, A11Y_NAV_TIMEOUT='8000', A11Y_IDLE_TIMEOUT='3000', A11Y_JOB_TIMEOUT='120')
    t0 = time.time()
    r = ratchet(env, '--urls', str(urls), '--score', timeout=150)
    took = time.time() - t0
    out = r.stderr + r.stdout
    assert took < 60, f'the run took {took:.0f} s (job timeout 120)'
    assert 'STOPPED' not in out, out
    assert re.search(r'deadline.*/hang|/hang.*deadline', out, re.S | re.I), out          # the page that hit the deadline is named
    assert re.search(r'/imgs', out) and 'never went idle' in out, out                     # the slow-but-audited page is named too


def test_a_timeout_with_every_page_done_does_not_say_stopped(tmp_path):
    # the engine wrote every page and then did not exit: results are complete, and the message must say what happened instead of "STOPPED"
    env = stub_node(tmp_path, f'echo \'{json.dumps({"/": {"v": [], "p": []}})}\' > "$2/audit.json"\nsleep 30\n')
    env['A11Y_JOB_TIMEOUT'] = '2'
    items = tmp_path / 'items.json'; items.write_text(json.dumps({'/': '<p>x</p>'}))
    r = ratchet(env, '--items', str(items), '--score')
    assert 'STOPPED' not in r.stderr, r.stderr
    assert 'did not exit' in r.stderr and r.returncode == 0, r.stderr


def test_a_timeout_with_pages_missing_names_them_and_has_no_score_wording_in_ratchet_mode(tmp_path):
    env = stub_node(tmp_path, 'sleep 30\n')
    env['A11Y_JOB_TIMEOUT'] = '2'
    items = tmp_path / 'items.json'; items.write_text(json.dumps({'a': '<p>x</p>', 'b': '<p>y</p>'}))
    base = tmp_path / 'b.json'; base.write_text(json.dumps({'axe': {}, 'static': {}}))
    r = ratchet(env, '--items', str(items), '--baseline', str(base))
    assert r.returncode == 3, r.stderr
    assert 'score below' not in r.stderr + r.stdout, r.stderr          # 6. no score is printed in ratchet mode
    assert 'STOPPED' in r.stderr and 'a' in r.stderr and 'b' in r.stderr


def test_the_proxy_destroys_upstream_sockets_when_closed():
    code = """
import { startVettingProxy } from %r; import http from 'node:http'; import net from 'node:net';
const srv = http.createServer(() => {}).listen(0, '127.0.0.1'); await new Promise(r => srv.on('listening', r));
const port = srv.address().port; const origin = '127.0.0.1:' + port;
const p = await startVettingProxy({ vetUrl: async () => {}, vetHost: async (h) => [h] });
const req = http.request({ host: '127.0.0.1', port: p.port, path: 'http://' + origin + '/', headers: { host: origin } }); req.on('error', () => {}); req.end();
await new Promise(r => setTimeout(r, 500));
p.close(); srv.close();
await new Promise(r => setTimeout(r, 300));
// anything left holding the loop (an upstream socket) keeps node alive: the unref'd proxy server alone does not
process.exit(process._getActiveHandles().filter(h => h instanceof net.Socket && !h.destroyed && h.remotePort === port).length);
""" % ((SCRIPTS / 'proxy.mjs').as_uri(),)
    r = subprocess.run(['node', '--input-type=module', '-e', code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


# ---- 2. a crawl that times out is exit 3 with the documented message, not a traceback -------------------------------------------------------

def test_a_crawl_timeout_exits_3_with_a_message(tmp_path):
    env = stub_node(tmp_path, 'sleep 30\n')
    env['A11Y_JOB_TIMEOUT'] = '2'
    r = ratchet(env, '--url', 'http://127.0.0.1:9/', '--crawl', '--score')
    assert r.returncode == 3, r.stdout + r.stderr
    assert 'Traceback' not in r.stderr, r.stderr
    assert 'A11Y_JOB_TIMEOUT' in r.stderr and 'crawl' in r.stderr, r.stderr


# ---- 3. an MCP timeout leaves no node or Chromium of the job -----------------------------------------------------------------------------------

def test_an_mcp_timeout_leaves_no_node_or_chromium(tmp_path, monkeypatch):
    import mcp_server
    env = stub_node(tmp_path, 'setsid sh -c "while :; do sleep 1; done" chromium-stub "--user-data-dir=$A11Y_USER_DATA_DIR" &\nsleep 60\n')
    for k in ('PATH', 'NODE_PATH'):
        monkeypatch.setenv(k, env[k])
    monkeypatch.setenv('A11Y_SCAN_ROOT', str(tmp_path))
    site = tmp_path / 'site'; site.mkdir(); (site / 'index.html').write_text('<!doctype html><html lang="en"><title>t</title><main><p>x</p></main>')
    orig = subprocess.Popen.communicate
    monkeypatch.setattr(subprocess.Popen, 'communicate', lambda self, input=None, timeout=None: orig(self, input, 4 if timeout and timeout > 100 else timeout))
    monkeypatch.chdir(tmp_path)
    job = {'status': 'running', 'started': time.time()}
    mcp_server.run_job(job, {'target': str(site)})
    time.sleep(1)
    left = alive('chromium-stub') + alive(str(tmp_path / 'bin' / 'node'))
    subprocess.run(['pkill', '-f', 'chromium-stub'])
    assert job['status'] == 'failed', job
    assert not left, 'survived the MCP timeout: ' + str(left)


# ---- 4. one version everywhere -----------------------------------------------------------------------------------------------------------------

def test_every_version_string_matches_the_changelog():
    top = re.search(r'^## (\d+\.\d+\.\d+)', (REPO / 'CHANGELOG.md').read_text(), re.M).group(1)
    import mcp_server
    found = {
        'plugin.json': json.loads((REPO / 'plugin.json').read_text())['version'],
        '.claude-plugin/plugin.json': json.loads((REPO / '.claude-plugin' / 'plugin.json').read_text())['version'],
        'mcp_server.VERSION': mcp_server.VERSION,
        'README status': re.search(r'\*\*Status:\*\* early \((\d+\.\d+\.\d+)\)', (REPO / 'README.md').read_text()).group(1),
    }
    assert all(v == top for v in found.values()), (top, found)


# ---- 5. the quick start prints no proxy-block lines for the browser's own background requests ---------------------------------------------------

@REAL
def test_quick_start_has_no_blocked_background_requests():
    r = subprocess.run([sys.executable, str(SCRIPTS / 'ratchet.py'), '--items', str(HERE / 'examples' / 'items.json'), '--score'], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert 'scan proxy: blocked' not in r.stderr, [l for l in r.stderr.splitlines() if 'blocked' in l][:3]


# ---- 7. a scan on :80 does not also open :443, and the reverse ----------------------------------------------------------------------------------

def test_default_ports_are_not_interchangeable():
    code = """
import { declareTargets, vetUrl } from %r;
const t = async (u) => { try { await vetUrl(u); return 'ALLOW'; } catch (e) { return 'block'; } };
const out = {};
for (const scan of ['http://127.0.0.1/', 'https://127.0.0.1/']) {
  declareTargets({ urls: { a: scan } });
  out[scan] = [await t('http://127.0.0.1:80/'), await t('http://127.0.0.1/'), await t('https://127.0.0.1:443/'), await t('https://127.0.0.1/'), await t('http://127.0.0.1:443/')];
}
console.log(JSON.stringify(out));
""" % ((SCRIPTS / 'lib.mjs').as_uri(),)
    r = subprocess.run(['node', '--input-type=module', '-e', code], capture_output=True, text=True, timeout=30, cwd=SCRIPTS)
    out = json.loads(r.stdout)
    assert out['http://127.0.0.1/'] == ['ALLOW', 'ALLOW', 'block', 'block', 'block'], out
    assert out['https://127.0.0.1/'] == ['block', 'block', 'ALLOW', 'ALLOW', 'ALLOW'], out
