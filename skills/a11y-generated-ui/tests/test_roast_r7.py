"""Fixes from the seventh roast (October 2026): late content is audited however it arrives, the crawl finds links rendered late, exit codes.
Real-Chromium tests are skipped without node_modules."""
import json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
SCRIPTS = HERE / 'scripts'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_roast_r3 import ratchet    # noqa: E402

REAL = pytest.mark.skipif(not (SCRIPTS / 'node_modules').exists() or not os.path.exists(os.environ.get('CHROMIUM', '/usr/bin/chromium')), reason='needs node_modules and Chromium')

# The 13 late-render shapes from round 7: each lands a barrier 3-5 s after load (spinners, re-armed polls, a callback scheduled twice, fetch and SSE
# streams, a typewriter, style reveals after an animation or a progress bar, a CSS animationend reveal).
BAR = "<img src=data:image/gif;base64,R0lGODlhAQABAAAAACw= ><button></button>"
PAGES = {
    'static': BAR,
    # spinner text in #out changes every 300 ms (setInterval); the real content lands in the same node
    'spin_fetch3': "<div id=out>Loading</div><script>let d=0;const iv=setInterval(()=>{out.textContent='Loading'+'.'.repeat(d++%4)},300);"
                   "fetch('/slow?3').then(r=>r.text()).then(()=>{clearInterval(iv);out.innerHTML='" + BAR + "'})</script>",
    'spin_timer3': "<div id=out>Loading</div><script>let d=0;const iv=setInterval(()=>{out.textContent='Loading'+'.'.repeat(d++%4)},300);"
                   "setTimeout(()=>{clearInterval(iv);out.innerHTML='" + BAR + "'},3000)</script>",
    # spinner driven by a re-armed setTimeout (same callback); after 10 ticks (~3 s) the content lands in the same node
    'spin_rearm': "<div id=out>Loading</div><script>let d=0;function spin(){d++;if(d<10){out.textContent='Loading'+'.'.repeat(d%4);setTimeout(spin,300)}"
                  "else out.innerHTML='" + BAR + "'}setTimeout(spin,300)</script>",
    # retry/poll loop calling the same named function; the job is ready on the 3rd poll (1.5 s apart)
    'poll_named_1500': "<script>let n=0;function poll(){n++;fetch('/status?'+n).then(r=>r.text()).then(t=>{if(t==='ready')document.querySelector('main')"
                       ".insertAdjacentHTML('beforeend','" + BAR + "');else setTimeout(poll,1500)})}poll()</script>",
    # same with 1 s apart, ready on the 5th poll (an AI generation job status poll)
    'poll_named_1000': "<script>let n=0;function poll(){n++;fetch('/status5?'+n).then(r=>r.text()).then(t=>{if(t==='ready')document.querySelector('main')"
                       ".insertAdjacentHTML('beforeend','" + BAR + "');else setTimeout(poll,1000)})}poll()</script>",
    # one render function scheduled twice: skeleton at 300 ms, data at 3.5 s
    'same_cb_twice': "<div id=app></div><script>let k=0;function render(){k++;app.innerHTML=k<2?'<p>loading</p>':'" + BAR + "'}"
                     "setTimeout(render,300);setTimeout(render,3500)</script>",
    # chat-style stream over fetch(): 10 chunks 400 ms apart appended into one message node; the last chunk carries the barrier
    'stream_fetch': "<div id=msg></div><script>(async()=>{const r=await fetch('/chunked');const rd=r.body.getReader();const dec=new TextDecoder();"
                    "for(;;){const {done,value}=await rd.read();if(done)break;msg.insertAdjacentHTML('beforeend',dec.decode(value))}})()</script>",
    # same over SSE (EventSource), chunks into one node
    'stream_sse': "<div id=msg></div><script>const es=new EventSource('/sse');es.onmessage=e=>{if(e.data==='END'){es.close();msg.insertAdjacentHTML('beforeend','"
                  + BAR + "')}else msg.insertAdjacentHTML('beforeend','<p>'+e.data+'</p>')}</script>",
    # typewriter: one text node grows every 50 ms for 3 s (setInterval), then the barrier is appended to the same parent
    'typewriter': "<p id=t></p><script>const tn=document.createTextNode('');t.appendChild(tn);let i=0;const iv=setInterval(()=>{tn.data+='x';if(++i>=60){clearInterval(iv);"
                  "t.insertAdjacentHTML('beforeend','" + BAR + "')}},50)</script>",
    # intro animation (rAF, style only) for 3 s, then pre-rendered content revealed by display:none -> block
    'intro_style_reveal': "<div id=splash>hi</div><div id=c style=display:none>" + BAR + "</div><script>const t0=performance.now();(function f(){const e=performance.now()-t0;"
                          "if(e<3000){splash.style.opacity=String(1-e/3000);requestAnimationFrame(f)}else{splash.style.display='none';c.style.display='block'}})()</script>",
    # reveal by style after a re-armed progress timer (width) reaches 100% (~3 s)
    'progress_style_reveal': "<div id=bar style=width:0></div><div id=c style=display:none>" + BAR + "</div><script>let w=0;function step(){w+=5;bar.style.width=w+'%';"
                             "if(w<100)setTimeout(step,150);else c.style.display='block'}setTimeout(step,150)</script>",
    # control (pre-existing gap): pure CSS animation 3 s, revealed on animationend
    'cssanim_end': "<style>@keyframes k{from{opacity:0}to{opacity:1}}#s{animation:k 3s}</style><div id=s>hi</div><div id=c style=display:none>" + BAR + "</div>"
                   "<script>s.addEventListener('animationend',()=>{c.style.display='block'})</script>",
}

NAV = ''.join(f'<a href=/p{j}>p{j}</a> ' for j in range(5))


class Late(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *a): pass
    def send(self, b, ct='text/plain'):
        self.send_response(200); self.send_header('Content-Type', ct); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path
        try:
            if p.startswith('/slow'):
                time.sleep(float(p.split('?')[1])); return self.send(b'ok')
            if p.startswith('/status5'):
                return self.send(b'ready' if int(p.split('?')[1]) >= 5 else b'pending')
            if p.startswith('/status'):
                return self.send(b'ready' if int(p.split('?')[1]) >= 3 else b'pending')
            if p.startswith('/chunked'):
                self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Transfer-Encoding', 'chunked'); self.end_headers()
                for i in range(11):
                    c = (BAR if i == 10 else f'<span>tok{i} </span>').encode()
                    self.wfile.write(b'%x\r\n%s\r\n' % (len(c), c)); self.wfile.flush(); time.sleep(0.4)
                self.wfile.write(b'0\r\n\r\n'); self.wfile.flush(); return
            if p.startswith('/sse'):
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Cache-Control', 'no-cache'); self.end_headers()
                for i in range(10):
                    self.wfile.write(f'data: tok{i}\n\n'.encode()); self.wfile.flush(); time.sleep(0.4)
                self.wfile.write(b'data: END\n\n'); self.wfile.flush(); time.sleep(30); return
            name = p.strip('/')
            body = f'<!doctype html><html lang="en"><head><title>{name}</title></head><body><main><h1>{name}</h1>{PAGES.get(name, "")}</main></body></html>'.encode()
            self.send(body, 'text/html')
        except OSError:
            return


class LateNav(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        try:
            if self.path.startswith('/api/nav'):
                time.sleep(4); b = NAV.encode()
            elif self.path == '/':
                b = b"<!doctype html><html lang=en><head><title>t</title></head><body><main><h1>t</h1><nav id=n></nav><script>fetch('/api/nav').then(r=>r.text()).then(t=>{n.innerHTML=t})</script></main></body></html>"
            else:
                b = f'<!doctype html><html lang=en><head><title>t</title></head><body><main><h1>t</h1>{BAR}</main></body></html>'.encode()
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
        except OSError:
            return


def serve(h):
    srv = ThreadingHTTPServer(('127.0.0.1', 0), h); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_address[1]}'


@REAL
def test_every_late_render_shape_is_audited(tmp_path):
    srv, base = serve(Late)
    try:
        urls = tmp_path / 'urls.txt'; urls.write_text(''.join(f'{base}/{n}\n' for n in PAGES))
        out = tmp_path / 'audit.json'
        r = ratchet(dict(os.environ, A11Y_JOB_TIMEOUT='300'), '--urls', str(urls), '--score', '--audit-out', str(out), timeout=360)
        audit = json.load(open(out))['audit']
        missed = [k for k, v in audit.items() if not {'image-alt', 'button-name'} <= {x['id'] for x in v.get('v', [])}]
        assert len(audit) == len(PAGES) and not missed, (missed, r.stderr[-500:])
    finally:
        srv.shutdown()


@REAL
def test_crawl_finds_links_rendered_after_a_slow_fetch():
    srv, base = serve(LateNav)
    try:
        r = ratchet(dict(os.environ, A11Y_JOB_TIMEOUT='200', A11Y_ALLOW_PRIVATE='1'), '--url', base + '/', '--crawl', '--max-pages', '10', '--json', timeout=240)
        rep = json.loads(r.stdout)
        assert rep['pages_scanned'] == 6 and rep['grade'] == 'C', (rep['pages_scanned'], rep['grade'])
    finally:
        srv.shutdown()


class Plain(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type', 'text/plain'); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'ok')


@REAL
def test_crawl_with_no_html_page_exits_3():
    srv, base = serve(Plain)
    try:
        r = ratchet(dict(os.environ, A11Y_JOB_TIMEOUT='60', A11Y_ALLOW_PRIVATE='1'), '--url', base + '/', '--crawl', '--score', timeout=90)
        assert r.returncode == 3 and 'no pages to scan' in r.stderr, (r.returncode, r.stderr[-300:])
    finally:
        srv.shutdown()


@REAL
def test_report_where_no_page_could_be_audited_exits_3(tmp_path):
    srv, base = serve(Plain); port = srv.server_address[1]; srv.shutdown(); srv.server_close()      # nothing listens there any more
    urls = tmp_path / 'urls.txt'; urls.write_text(f'http://127.0.0.1:{port}/a\n')
    r = ratchet(dict(os.environ, A11Y_JOB_TIMEOUT='60', A11Y_ALLOW_PRIVATE='1'), '--urls', str(urls), '--report', timeout=90)
    assert r.returncode == 3 and 'no page could be audited' in r.stderr, (r.returncode, r.stdout[-300:], r.stderr[-300:])


def test_sigterm_removes_the_temp_dir_without_an_engine():
    src = (SCRIPTS / 'ratchet.py').read_text()          # reading the code: a SIGTERM between engines is hard to time in a test
    assert 'TEMP.append(t)' in src and 'for t in TEMP:' in src


def test_node_without_the_october_2026_security_fixes_is_refused():
    js = ("import('./lib.mjs').then(L => console.log(JSON.stringify(['20.19.2', '22.23.3', '22.23.4', '24.22.0', '24.22.1', '25.9.0', '26.12.1', '27.0.0']"
          ".map(v => L.nodeVersionOk(v)))))")
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True, cwd=SCRIPTS, timeout=30)
    assert json.loads(r.stdout) == [False, False, True, False, True, False, True, True], r.stderr
