#!/usr/bin/env python3
"""Local MCP server (stdio) around ratchet.py: lets an agent scan a site or a built folder, read the score and the failing checks, and ask what a
check means. No dependencies beyond the standard library; it speaks MCP's newline-delimited JSON-RPC itself.

Scans take minutes, so the scan is a job: scan_start returns an id at once, scan_status shows progress, scan_result returns the report.

Safety: localhost and local folders are scanned freely. Any other host needs BOTH confirm_permission=true in the call AND the environment variable
A11Y_ALLOW_REMOTE=1 set by whoever starts the server: an agent can set the first itself, so the second is the human's switch. Link-local and cloud-metadata
addresses (169.254.0.0/16, fe80::/10) are never scanned, and private ranges are blocked unless the human sets A11Y_ALLOW_PRIVATE=1. A target that is not a folder under the
current directory (or A11Y_SCAN_ROOT) is refused. The server runs on your machine with your network access.
"""
import ipaddress, json, os, re, signal, socket, subprocess, sys, tempfile, threading, time, urllib.parse, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS = {}
MAX_RUNNING_JOBS = int(os.environ.get('A11Y_MAX_JOBS', 2))      # concurrent scans; a third scan_start is refused until one finishes
SUPPORTED_VERSIONS = ('2025-06-18', '2025-03-26', '2024-11-05')   # MCP protocol versions this server implements, newest first


def bounded(a, key, default, lo, hi):
    """An integer argument inside [lo, hi]; the declared JSON-schema bounds are enforced here, not just advertised."""
    v = a.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
        raise ValueError(f'{key} must be a whole number')
    if not lo <= int(v) <= hi:
        raise ValueError(f'{key} must be between {lo} and {hi}')
    return int(v)

VERSION = '0.1.1'

STATIC_HELP = {
    'click_not_keyboard': 'A non-interactive element (span, div) has a click handler but no role and tabindex, so a keyboard user cannot operate it (WCAG 2.1.1). Use a real <button> or <a>, or add role, tabindex="0" and Enter/Space handling.',
    'hidden_input_widget': 'A radio or checkbox is hidden with display:none (the CSS radio trick), so it cannot take focus (WCAG 2.1.1). Hide it visually (clip, opacity:0, position:absolute) and keep it focusable, with a visible focus style on its label.',
    'svg_no_name': 'An <svg> has no accessible name or aria-hidden (WCAG 1.1.1). Give it an accessible name (role="img" plus aria-label, or a non-empty <title>), or aria-hidden="true" if decorative. role="img" alone is not a name.',
    'canvas_no_text_alt': 'A <canvas> has no text alternative (WCAG 1.1.1). Add aria-label (role="img" alone is not a name), or fallback text inside the <canvas>, or a text equivalent next to it; aria-hidden if purely decorative.',
    'loop_no_reduced_motion': 'An endless CSS animation has no prefers-reduced-motion rule (WCAG 2.2.2 for anything that moves for more than 5 seconds; 2.3.3 is a AAA criterion about interaction-triggered motion). Add @media (prefers-reduced-motion: reduce) { animation: none } and offer a pause control for motion over five seconds.',
}
TOOLS = [
    {'name': 'scan_start', 'description': 'Start an accessibility scan of a site (http/https URL) or a built folder (local path). Returns a job id at once; poll scan_status, then read scan_result. Automated checks only: axe-core plus static checks. Hosts other than localhost need confirm_permission.',
     'inputSchema': {'type': 'object', 'properties': {
         'target': {'type': 'string', 'description': 'A URL (http://localhost:3000, https://example.com) or a local folder of built .html files'},
         'crawl': {'type': 'boolean', 'description': 'Follow same-origin links from a URL (default false: scan only that page)'},
         'max_pages': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'description': 'Page cap (default 15)'},
         'depth': {'type': 'integer', 'minimum': 0, 'maximum': 4, 'description': 'Link depth when crawling (default 2)'},
         'theme': {'type': 'string', 'enum': ['light', 'dark'], 'description': 'Colour scheme to request (default light)'},
         'confirm_permission': {'type': 'boolean', 'description': 'Required for any host other than localhost: true only if you own the site or have permission to test it'}},
         'required': ['target']}},
    {'name': 'scan_status', 'description': 'Status of a scan job: running, done or failed, with progress (pages done / pages) while it runs.', 'inputSchema': {'type': 'object', 'properties': {'job_id': {'type': 'string'}}, 'required': ['job_id']}},
    {'name': 'scan_result', 'description': 'The finished report: score 0-100, grade (always "automated findings", never "accessible"), four layer scores, worst pages, failing checks with the points each cost and the score gain if fixed alone, a greedy fix_order (which fixes raise the score most), and the coverage note. Say that note to the user.',
     'inputSchema': {'type': 'object', 'properties': {'job_id': {'type': 'string'}, 'max_checks': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'description': 'How many failing checks to include (default 15)'}}, 'required': ['job_id']}},
    {'name': 'explain_check', 'description': 'Plain-language meaning and fix for one failing check id from a scan (an axe rule such as color-contrast, or one of the static checks).',
     'inputSchema': {'type': 'object', 'properties': {'check_id': {'type': 'string'}, 'job_id': {'type': 'string', 'description': 'Optional: the scan the id came from, for its help text and link'}}, 'required': ['check_id']}},
]


def check_target(target, confirm):
    """Returns (mode, argument) or raises ValueError with a reason."""
    if target.startswith(('http://', 'https://')):
        host = urllib.parse.urlparse(target).hostname or ''
        try:
            addrs = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
        except OSError:
            raise ValueError(f'cannot resolve {host}')
        for a in addrs:
            ip = ipaddress.ip_address(a.split('%')[0])
            if ip.is_link_local or host == 'metadata.google.internal':
                raise ValueError(f'{host} resolves to a link-local address ({a}); never scanned')
            if ip.is_unspecified or ip in ipaddress.ip_network('0.0.0.0/8'):
                raise ValueError(f'{host} resolves to {a}, which the kernel routes to this machine: blocked')
            if (ip.is_private and not ip.is_loopback) and os.environ.get('A11Y_ALLOW_PRIVATE') != '1':
                raise ValueError(f'{host} resolves to a private address ({a}); blocked. Whoever starts this server can allow internal hosts with A11Y_ALLOW_PRIVATE=1')
            if ip.is_loopback and host not in ('localhost', '127.0.0.1', '::1'):     # 127.0.0.2 and friends
                raise ValueError(f'{host} resolves to a loopback address; blocked')
        if not all(ipaddress.ip_address(a.split('%')[0]).is_loopback for a in addrs):
            if os.environ.get('A11Y_ALLOW_REMOTE') != '1':
                raise ValueError(f'{host} is not localhost: remote scanning is off. Whoever runs this server must start it with A11Y_ALLOW_REMOTE=1 (a human decision: scan only sites you own or have permission to test)')
            if not confirm:
                raise ValueError(f'{host} is not localhost: scan only sites you own or have permission to test, and pass confirm_permission=true')
        return 'url', target
    p = Path(target).expanduser()
    if p.is_dir():
        root = Path(os.environ.get('A11Y_SCAN_ROOT') or os.getcwd()).resolve()
        rp = p.resolve()
        if root != rp and root not in rp.parents:
            raise ValueError(f'{rp} is outside {root}: set A11Y_SCAN_ROOT to the folder scans may read')
        return 'dir', str(rp)
    raise ValueError('target must be an http(s) URL or an existing folder')


def progress_of(line):
    """'12/70' from an engine progress line like '[12/70] /page', else None."""
    m = re.match(r'\s*\[(\d+)/(\d+)\]', line)
    return f'{m.group(1)}/{m.group(2)}' if m else None


def run_job(job, args):
    proc = None
    try:
        mode, arg = check_target(args['target'], bool(args.get('confirm_permission')))
        theme = args.get('theme', 'light')
        if theme not in ('light', 'dark'):
            raise ValueError('theme must be light or dark')
        cmd = [sys.executable, str(HERE / 'ratchet.py'), '--score', '--json', '--theme', theme, '--max-pages', str(bounded(args, 'max_pages', 15, 1, 100)),
               '--depth', str(bounded(args, 'depth', 2, 0, 4))]
        if mode == 'url':
            cmd += ['--url', arg] + (['--crawl'] if args.get('crawl') else []) + (['--confirm-permission'] if args.get('confirm_permission') else [])
        else:
            cmd += ['--dir', arg]
        job['phase'] = 'scanning'
        limit = int(os.environ.get('A11Y_JOB_TIMEOUT', 1800)) + 120
        # ratchet.py runs in its own process group, but node and Chromium run in sessions of their own (ratchet starts them that way), so killing the group
        # does not reach them. On a timeout ratchet gets SIGTERM first: it stops its node and the Chromium found by the run's own --user-data-dir, then exits.
        # The group kill afterwards is only the backstop for ratchet itself.
        env = {**os.environ, 'A11Y_JOB_TIMEOUT': os.environ.get('A11Y_JOB_TIMEOUT', '1800')}      # an agent-started scan stops after 30 minutes unless the human who runs the server allows more
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL, start_new_session=True)   # never let the scan read the MCP stream
        job['pgid'] = proc.pid
        err_lines = []

        def pump_err():      # scan_status shows progress: the engine prints [n/N] per page on stderr
            for line in proc.stderr:
                err_lines.append(line)
                p_ = progress_of(line)
                if p_:
                    job['progress'] = p_
        t_err = threading.Thread(target=pump_err, daemon=True)
        t_err.start()
        try:
            out = proc.communicate(timeout=limit)[0]
        except subprocess.TimeoutExpired:
            proc.terminate()                          # ratchet's handler stops node and Chromium before it exits
            try:
                proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(proc.pid, signal.SIGKILL)   # backstop for ratchet and any helper left in its group
            except OSError:
                pass
            proc.communicate()
            raise RuntimeError(f'scan stopped after {limit} s')
        t_err.join(5)
        err = ''.join(err_lines)
        if '{' not in out:
            raise RuntimeError((err or out)[-400:] or 'scan produced no report')
        job['report'] = json.loads(out[out.index('{'):])
        job['status'] = 'done'
    except Exception as e:   # noqa: BLE001 - reported to the caller
        job['status'] = 'failed'
        job['error'] = str(e)[:400]


def call_tool(name, a):
    if name == 'scan_start':
        if not a.get('target'):
            raise ValueError('target is required')
        mode, _ = check_target(a['target'], bool(a.get('confirm_permission')))   # refuse early, before a job exists
        bounded(a, 'max_pages', 15, 1, 100); bounded(a, 'depth', 2, 0, 4)
        if sum(1 for v in JOBS.values() if v.get('status') == 'running') >= MAX_RUNNING_JOBS:
            raise ValueError(f'{MAX_RUNNING_JOBS} scans are already running; wait for one to finish (A11Y_MAX_JOBS raises the limit)')
        jid = uuid.uuid4().hex[:10]
        for old in [k for k, v in JOBS.items() if v.get('status') != 'running' and time.time() - v['started'] > 3600]:
            del JOBS[old]   # finished jobs are kept for an hour, then dropped
        JOBS[jid] = {'status': 'running', 'phase': 'starting', 'started': time.time(), 'target': str(a['target'])[:300], 'mode': mode}
        threading.Thread(target=run_job, args=(JOBS[jid], a), daemon=True).start()
        return {'job_id': jid, 'status': 'running', 'note': 'Poll scan_status; a crawl can take a few minutes.'}
    if name == 'scan_status':
        j = JOBS.get(a.get('job_id'))
        if not j:
            raise ValueError('unknown job_id')
        return {'job_id': a['job_id'], 'status': j['status'], 'phase': j.get('phase'), 'progress': j.get('progress'), 'seconds': round(time.time() - j['started']), 'error': j.get('error')}
    if name == 'scan_result':
        j = JOBS.get(a.get('job_id'))
        if not j:
            raise ValueError('unknown job_id')
        if j['status'] == 'failed':
            raise ValueError('scan failed: ' + j.get('error', ''))
        if j['status'] != 'done':
            return {'status': j['status'], 'note': 'not finished yet'}
        rep = dict(j['report']); n = int(a.get('max_checks', 15))
        rep['failing_checks'] = rep.get('failing_checks', [])[:n]
        rep['fix_order'] = rep.get('fix_order', [])[:10]
        rep['pages'] = {k: {'score': v['score'], 'grade': v['grade']} for k, v in list(rep.get('pages', {}).items())[:40]}
        return rep
    if name == 'explain_check':
        cid = a.get('check_id', '')
        if cid in STATIC_HELP:
            return {'check_id': cid, 'explanation': STATIC_HELP[cid]}
        j = JOBS.get(a.get('job_id') or '')
        for e in ((j or {}).get('report') or {}).get('failing_checks', []):
            if e['id'] == cid:
                return {'check_id': cid, 'explanation': e.get('help'), 'impact': e.get('impact'), 'learn_more': e.get('url')}
        return {'check_id': cid, 'explanation': 'Not a static check and not in the given scan. For an axe rule, see https://dequeuniversity.com/rules/axe/ and the rule id.', 'learn_more': f'https://dequeuniversity.com/rules/axe/4.14/{cid}'}
    raise ValueError('unknown tool ' + name)


def reply(i, result=None, error=None):
    m = {'jsonrpc': '2.0', 'id': i}
    m.update({'error': error} if error else {'result': result})
    sys.stdout.write(json.dumps(m) + '\n'); sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except ValueError:
            continue
        i, method, p = m.get('id'), m.get('method'), m.get('params') or {}
        if method == 'initialize':
            reply(i, {'protocolVersion': (p.get('protocolVersion') if p.get('protocolVersion') in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]), 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'a11y-scan', 'version': VERSION}})
        elif method == 'tools/list':
            reply(i, {'tools': TOOLS})
        elif method == 'tools/call':
            try:
                out = call_tool(p.get('name'), p.get('arguments') or {})
                reply(i, {'content': [{'type': 'text', 'text': json.dumps(out, indent=1)}]})
            except Exception as e:   # noqa: BLE001
                reply(i, {'content': [{'type': 'text', 'text': str(e)}], 'isError': True})
        elif method == 'ping':
            reply(i, {})
        elif i is not None:
            reply(i, error={'code': -32601, 'message': 'method not found: ' + str(method)})


if __name__ == '__main__':
    main()
