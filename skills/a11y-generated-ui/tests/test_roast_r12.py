"""Fix from the twelfth roast (October 2026): late content in a nested frame, or in the second or later sibling frame, is waited for
(the merged settle state keeps the page's origin, so every frame is compared with it). Real-Chromium tests skip without node_modules."""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
SCRIPTS = HERE / 'scripts'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_roast_r3 import ratchet    # noqa: E402

REAL = pytest.mark.skipif(not (SCRIPTS / 'node_modules').exists() or not os.path.exists(os.environ.get('CHROMIUM', '/usr/bin/chromium')), reason='needs node_modules and Chromium')

BAR = "<img src=data:image/gif;base64,R0lGODlhAQABAAAAACw= ><button></button>"
LATE3 = "<script>setTimeout(()=>{document.querySelector('main').insertAdjacentHTML('beforeend','" + BAR + "')},3000)</script>"
PAGES = {
    'nested_late3': "<iframe title=outer src='/nest'></iframe>",
    'sibling_late3': ("<iframe title=a srcdoc='<main><p>one</p></main>'></iframe><iframe title=b srcdoc='<main><p>two</p></main>'></iframe>"
                      "<iframe title=c srcdoc=\"<main><p>three</p></main>" + LATE3.replace("'", "&#39;") + "\"></iframe>"),
}


def page(title, body):
    return f'<!doctype html><html lang="en"><head><title>{title}</title></head><body><main><h1>{title}</h1>{body}</main></body></html>'.encode()


class P(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        try:
            if self.path == '/nest':
                b = page('nest', "<iframe title=inner src='/late3'></iframe>")
            elif self.path == '/late3':
                b = page('late3', LATE3)
            else:
                name = self.path.strip('/'); b = page(name, PAGES.get(name, ''))
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
        except OSError:
            return


@REAL
def test_late_content_in_nested_and_later_sibling_frames_is_audited(tmp_path):
    srv = ThreadingHTTPServer(('127.0.0.1', 0), P); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f'http://127.0.0.1:{srv.server_address[1]}'
        urls = tmp_path / 'urls.txt'; urls.write_text(''.join(f'{base}/{n}\n' for n in PAGES))
        out = tmp_path / 'audit.json'
        r = ratchet(dict(os.environ, A11Y_JOB_TIMEOUT='120'), '--urls', str(urls), '--score', '--audit-out', str(out), timeout=180)
        audit = json.load(open(out))['audit']
        missed = [k for k, v in audit.items() if not {'image-alt', 'button-name'} <= {x['id'] for x in v.get('v', [])}]
        assert len(audit) == len(PAGES) and not missed, (missed, r.stderr[-400:])
    finally:
        srv.shutdown()
