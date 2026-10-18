"""The stdio MCP server: protocol shape, safety refusals and (with a browser) a real scan of a local folder."""
import json, subprocess, sys, time
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
SERVER = HERE / 'scripts' / 'mcp_server.py'
HAVE_BROWSER = (HERE / 'scripts' / 'node_modules').exists()


class Client:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.n = 0
        self.call('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '0'}})

    def call(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.n, 'method': method, 'params': params or {}}) + '\n'); self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def tool(self, name, **args):
        r = self.call('tools/call', {'name': name, 'arguments': args})['result']
        return r.get('isError', False), json.loads(r['content'][0]['text']) if not r.get('isError') else r['content'][0]['text']

    def close(self):
        self.p.stdin.close(); self.p.wait(timeout=10)


@pytest.fixture
def client():
    c = Client(); yield c; c.close()


def test_lists_the_four_tools(client):
    names = {t['name'] for t in client.call('tools/list')['result']['tools']}
    assert names == {'scan_start', 'scan_status', 'scan_result', 'explain_check'}


def test_refuses_other_hosts_without_permission_and_metadata_addresses_always(client):
    err, msg = client.tool('scan_start', target='https://example.com')
    assert err and 'permission' in msg or 'remote scanning is off' in msg
    err, msg = client.tool('scan_start', target='https://example.com', confirm_permission=True)
    assert err and 'A11Y_ALLOW_REMOTE' in msg      # an agent cannot grant itself remote scanning
    err, msg = client.tool('scan_start', target='http://169.254.169.254/latest/meta-data', confirm_permission=True)
    assert err and 'link-local' in msg


def test_explains_a_static_check(client):
    err, out = client.tool('explain_check', check_id='click_not_keyboard')
    assert not err and 'button' in out['explanation']


@pytest.mark.skipif(not HAVE_BROWSER, reason='run npm install in scripts/')
def test_scans_a_local_folder_end_to_end(client, tmp_path):
    (tmp_path / 'index.html').write_text('<!doctype html><html lang="en"><title>t</title><main><span onclick="x()">go</span><p style="color:#aaa;background:#fff">pale</p></main></html>')
    err, out = client.tool('scan_start', target=str(tmp_path))
    assert not err and out['status'] == 'running'
    for _ in range(120):
        _, st = client.tool('scan_status', job_id=out['job_id'])
        if st['status'] != 'running':
            break
        time.sleep(2)
    assert st['status'] == 'done', st
    _, rep = client.tool('scan_result', job_id=out['job_id'])
    ids = {c['id'] for c in rep['failing_checks']}
    assert {'color-contrast', 'click_not_keyboard'} <= ids and rep['score'] <= 69 and 'not a conformance claim' in rep['note'], rep
