#!/usr/bin/env python3
"""Local MCP server (stdio) around ratchet.py: lets an agent scan a site or a built folder, read the score and the failing checks, and ask what a
check means. No dependencies beyond the standard library; it speaks MCP's newline-delimited JSON-RPC itself.

Scans take minutes, so the scan is a job: scan_start returns an id at once, scan_status shows progress, scan_result returns the report.

Safety: localhost and local folders are scanned freely. Any other host needs BOTH confirm_permission=true in the call AND the environment variable
A11Y_ALLOW_REMOTE=1 set by whoever starts the server: an agent can set the first itself, so the second is the human's switch. Link-local and cloud-metadata
addresses (169.254.0.0/16, fe80::/10) are never scanned. The server runs on your machine with your network access.
"""
import ipaddress, json, os, socket, subprocess, sys, tempfile, threading, time, urllib.parse, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS = {}
VERSION = '0.1.0'

STATIC_HELP = {
    'click_not_keyboard': 'A non-interactive element (span, div) has a click handler but no role and tabindex, so a keyboard user cannot operate it (WCAG 2.1.1). Use a real <button> or <a>, or add role, tabindex="0" and Enter/Space handling.',
    'hidden_input_widget': 'A radio or checkbox is hidden with display:none (the CSS radio trick), so it cannot take focus (WCAG 2.1.1). Hide it visually (clip, opacity:0, position:absolute) and keep it focusable, with a visible focus style on its label.',
    'svg_no_name': 'An <svg> has no accessible name or aria-hidden (WCAG 1.1.1). Add role="img" with aria-label or a <title>, or aria-hidden="true" if decorative.',
    'canvas_no_text_alt': 'A <canvas> has no text alternative (WCAG 1.1.1). Add aria-label or role="img", or a text equivalent next to it; aria-hidden if purely decorative.',
    'loop_no_reduced_motion': 'An endless CSS animation has no prefers-reduced-motion rule (WCAG 2.2.2, 2.3.3). Add @media (prefers-reduced-motion: reduce) { animation: none } and offer a pause control for motion over five seconds.',
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
    {'name': 'scan_status', 'description': 'Status of a scan job: running, done or failed.', 'inputSchema': {'type': 'object', 'properties': {'job_id': {'type': 'string'}}, 'required': ['job_id']}},
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
            if ip.is_link_local:
                raise ValueError(f'{host} resolves to a link-local address ({a}); never scanned')
        if not all(ipaddress.ip_address(a.split('%')[0]).is_loopback for a in addrs):
            if os.environ.get('A11Y_ALLOW_REMOTE') != '1':
                raise ValueError(f'{host} is not localhost: remote scanning is off. Whoever runs this server must start it with A11Y_ALLOW_REMOTE=1 (a human decision: scan only sites you own or have permission to test)')
            if not confirm:
                raise ValueError(f'{host} is not localhost: scan only sites you own or have permission to test, and pass confirm_permission=true')
        return 'url', target
    p = Path(target).expanduser()
    if p.is_dir():
        return 'dir', str(p.resolve())
    raise ValueError('target must be an http(s) URL or an existing folder')


def run_job(job, args):
    try:
        mode, arg = check_target(args['target'], bool(args.get('confirm_permission')))
        cmd = [sys.executable, str(HERE / 'ratchet.py'), '--score', '--json', '--theme', args.get('theme', 'light'), '--max-pages', str(int(args.get('max_pages', 15))),
               '--depth', str(int(args.get('depth', 2)))]
        if mode == 'url':
            cmd += ['--url', arg] + (['--crawl'] if args.get('crawl') else []) + (['--confirm-permission'] if args.get('confirm_permission') else [])
        else:
            cmd += ['--dir', arg]
        job['phase'] = 'scanning'
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, stdin=subprocess.DEVNULL)   # never let the scan read the MCP stream
        out = r.stdout
        if '{' not in out:
            raise RuntimeError((r.stderr or out)[-400:] or 'scan produced no report')
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
        jid = uuid.uuid4().hex[:10]
        JOBS[jid] = {'status': 'running', 'phase': 'starting', 'started': time.time(), 'target': a['target'], 'mode': mode}
        threading.Thread(target=run_job, args=(JOBS[jid], a), daemon=True).start()
        return {'job_id': jid, 'status': 'running', 'note': 'Poll scan_status; a crawl can take a few minutes.'}
    if name == 'scan_status':
        j = JOBS.get(a.get('job_id'))
        if not j:
            raise ValueError('unknown job_id')
        return {'job_id': a['job_id'], 'status': j['status'], 'phase': j.get('phase'), 'seconds': round(time.time() - j['started']), 'error': j.get('error')}
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
            reply(i, {'protocolVersion': p.get('protocolVersion') or '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'a11y-scan', 'version': VERSION}})
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
