"""Fixes from the third roast (October 2026). Ratchet tests stub `node` with a shell script, so they need no browser; the one test that starts a real
Chromium (the orphan check) is skipped without node_modules."""
import json, os, re, stat, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
SCRIPTS = HERE / 'scripts'
sys.path.insert(0, str(SCRIPTS))

OK = {'/': {'v': [], 'p': []}}


def stub_node(tmp_path, body):
    d = tmp_path / 'bin'
    d.mkdir(exist_ok=True)
    f = d / 'node'
    f.write_text('#!/bin/sh\n' + body)
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return dict(os.environ, PATH=str(d) + os.pathsep + os.environ['PATH'], NODE_PATH='/nonexistent')


def audit_node(tmp_path, audit):
    (tmp_path / 'audit.json').write_text(json.dumps(audit))
    return stub_node(tmp_path, f'cp {tmp_path}/audit.json "$2/audit.json"\n')


def ratchet(env, *args, timeout=60):
    return subprocess.run([sys.executable, str(SCRIPTS / 'ratchet.py'), *args], capture_output=True, text=True, timeout=timeout, env=env)


# ---- --json must stay pure JSON, also with --baseline ------------------------------------------------------------------------------------------

def test_json_with_baseline_keeps_stdout_pure_json(tmp_path):
    items = tmp_path / 'items.json'; items.write_text(json.dumps({'a': '<p>x</p>'}))
    base = tmp_path / 'base.json'; base.write_text(json.dumps({'axe': {}, 'static': {}}))
    r = ratchet(audit_node(tmp_path, {'a': {'v': [], 'p': []}}), '--items', str(items), '--score', '--json', '--min-score', '0', '--baseline', str(base))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)['score'] is not None            # raises on 'Extra data' if ratchet text follows the report
    assert 'NEW 0' in r.stderr                                    # the ratchet result is still shown, on stderr


# ---- a timeout must take the browser down with node --------------------------------------------------------------------------------------------

def alive(marker):
    out = subprocess.run(['ps', '-eo', 'args'], capture_output=True, text=True).stdout
    return [ln for ln in out.splitlines() if marker in ln and 'ps -eo' not in ln]


def test_a_timeout_kills_the_detached_browser_too(tmp_path):
    # Puppeteer starts Chromium detached (its own process group), so killing node or node's group is not enough. The stub does the same:
    # a setsid'ed child carrying the run's --user-data-dir, which ratchet.py hands to the engine in A11Y_USER_DATA_DIR.
    env = stub_node(tmp_path, 'setsid sh -c "while :; do sleep 1; done" chromium-stub "--user-data-dir=$A11Y_USER_DATA_DIR" &\nsleep 60\n')
    env['A11Y_JOB_TIMEOUT'] = '2'
    items = tmp_path / 'items.json'; items.write_text(json.dumps({'a': '<p>x</p>'}))
    r = ratchet(env, '--items', str(items), '--score')
    assert r.returncode == 3, r.stdout + r.stderr
    time.sleep(0.5)
    left = alive('chromium-stub')
    for ln in left:
        subprocess.run(['pkill', '-f', 'chromium-stub'])
    assert not left, 'a browser process survived the timeout: ' + str(left)


@pytest.mark.skipif(not (SCRIPTS / 'node_modules').exists() or not os.path.exists(os.environ.get('CHROMIUM', '/usr/bin/chromium')), reason='needs node_modules and Chromium')
def test_a_timeout_leaves_no_real_chromium_of_the_run(tmp_path):
    class Slow(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if self.path == '/slow':
                time.sleep(25)
            body = b'<!doctype html><html lang="en"><title>t</title><main><p>x</p><script>fetch("/slow")</script></main>'
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers()
            try: self.wfile.write(body)
            except OSError: pass
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    before = set(alive('puppeteer_dev_chrome_profile'))
    try:
        env = dict(os.environ, A11Y_JOB_TIMEOUT='8', A11Y_NO_SANDBOX=os.environ.get('A11Y_NO_SANDBOX', ''))
        ratchet(env, '--url', f'http://127.0.0.1:{srv.server_address[1]}/', '--report', timeout=120)
        time.sleep(1)
    finally:
        srv.shutdown()
    new = set(alive('puppeteer_dev_chrome_profile')) - before
    assert not new, 'Chromium of this run survived the timeout: ' + str(list(new)[:2])


# ---- --crosscheck sets the exit code ---------------------------------------------------------------------------------------------------------

def crosscheck_env(tmp_path, htmlcs, ibm, axe):
    fx = tmp_path / 'fx'; fx.mkdir()
    (fx / 'audit.json').write_text(json.dumps(axe)); (fx / 'htmlcs-light.json').write_text(json.dumps(htmlcs)); (fx / 'ibm-light.json').write_text(json.dumps(ibm))
    return stub_node(tmp_path, f'cp {fx}/*.json "$2/"\n')


def test_crosscheck_exits_1_when_engines_agree_on_a_finding(tmp_path):
    items = tmp_path / 'items.json'; items.write_text(json.dumps({'a': '<input placeholder="x">'}))
    env = crosscheck_env(tmp_path, {'a': {'v': [{'rule': 'WCAG2AA.Principle1.Guideline1_3.1_3_1.F68', 'msg': 'm'}]}}, {'a': {'v': [{'rule': 'input_label_exists', 'msg': 'm'}]}}, {'a': {'v': []}})
    r = ratchet(env, '--items', str(items), '--crosscheck')
    assert r.returncode == 1, r.stdout + r.stderr


def test_crosscheck_exits_0_when_the_engines_find_nothing_in_common(tmp_path):
    items = tmp_path / 'items.json'; items.write_text(json.dumps({'a': '<p>x</p>'}))
    env = crosscheck_env(tmp_path, {'a': {'v': []}}, {'a': {'v': []}}, {'a': {'v': []}})
    assert ratchet(env, '--items', str(items), '--crosscheck').returncode == 0


# ---- [::1] is local; a sitemap cannot widen the scan to other hosts --------------------------------------------------------------------------

def test_ipv6_loopback_is_local_and_needs_no_permission(tmp_path):
    r = ratchet(audit_node(tmp_path, OK), '--url', 'http://[::1]:9/', '--score')
    assert 'refusing' not in r.stderr, r.stderr


def test_a_sitemap_lists_only_its_own_host(tmp_path):
    class Sm(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            port = self.server.server_address[1]
            body = f'<urlset><url><loc>http://127.0.0.1:{port}/a</loc></url><url><loc>http://elsewhere.example/b</loc></url></urlset>'.encode()
            self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Sm)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = ratchet(audit_node(tmp_path, {'/a': {'v': [], 'p': []}}), '--sitemap', f'http://127.0.0.1:{srv.server_address[1]}/sitemap.xml', '--score')
    finally:
        srv.shutdown()
    assert 'refusing' not in r.stderr and 'elsewhere.example' in r.stderr and 'skipped' in r.stderr, r.stdout + r.stderr


# ---- plugin text, stray file, CI template, release steps -------------------------------------------------------------------------------------

def test_plugin_descriptions_do_not_claim_three_engines_score():
    for f in (REPO / 'plugin.json', REPO / '.claude-plugin' / 'plugin.json'):
        text = json.loads(f.read_text())['description']
        assert 'two more engines' not in text and 'axe-core' in text and 'cross-check' in text, f


def test_the_debug_script_is_gone():
    assert not (SCRIPTS / 't.mjs').exists()


def test_the_ci_template_parses_and_pins_the_tag_the_changelog_names():
    import yaml
    wf = yaml.safe_load((HERE / 'examples' / 'ci' / 'a11y-scan.yml').read_text())
    steps = wf['jobs']['scan']['steps']
    install = next(s for s in steps if s.get('name') == 'Install the scanner')
    ref = install['env']['A11Y_REF']
    assert re.fullmatch(r'v\d+\.\d+\.\d+', ref), f'a runnable template pins a release tag, not a placeholder: {ref}'
    assert ref != 'v0.1.0', 'v0.1.0 is the withdrawn pre-hardening tag'
    changelog = (REPO / 'CHANGELOG.md').read_text()
    assert 'Release steps' in changelog and ref in changelog.split('Release steps', 1)[1], 'CHANGELOG must say the maintainer cuts ' + ref


def test_mcp_scan_status_reports_progress():
    import mcp_server
    assert mcp_server.progress_of('[12/70] /a/b') == '12/70'
    assert mcp_server.progress_of('nothing here') is None
