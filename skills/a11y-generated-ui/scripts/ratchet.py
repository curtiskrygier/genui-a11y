#!/usr/bin/env python3
"""Accessibility ratchet for generated UI. Engine-agnostic about WHAT rendered the HTML: you give it named HTML fragments (and, optionally,
the host stylesheet they will really sit in); it runs axe-core in headless Chromium, a few static checks axe cannot make, an optional
keyboard "tab walk", and an optional cross-check with two more engines. The baseline lists exactly which items are not yet clean; anything
NEW fails, anything that got worse fails, anything fixed is reported so you can lock the gain in.

  python3 ratchet.py --items items.json --baseline baseline.json                 # ratchet (exit 1 on anything new)
  python3 ratchet.py --items items.json --baseline baseline.json --update        # rewrite the baseline after a fixing batch
  python3 ratchet.py --items items.json --baseline baseline.json --theme dark    # same on a dark host page (use a separate baseline)
  python3 ratchet.py --items items.json --report                                 # breakdown, no ratchet
  python3 ratchet.py --items items.json --static                                 # static flags only: seconds, no browser
  python3 ratchet.py --items items.json --tabwalk                                # keyboard + accessibility-tree walk
  python3 ratchet.py --items items.json --crosscheck                             # axe vs HTML_CodeSniffer vs IBM Equal Access

items.json is {"name": "<html fragment>", ...}. A directory of .html files works too: --items dir/. --shell host.css gives the real host
stylesheet (theme tokens such as --bg and --text); without it, fragments sit on a plain page. Set A11Y_DARK_CLASS if the host marks its
dark theme with a body class other than "dark". See ../SKILL.md for what a clean result does and does not mean.

Static flags (own markup only):
  loop_no_reduced_motion  an infinite CSS animation and no prefers-reduced-motion rule (WCAG 2.2.2, 2.3.3)
  canvas_no_text_alt      a <canvas> with no aria-label / role=img / aria-hidden (WCAG 1.1.1)
  click_not_keyboard      a non-interactive element with an onclick/onkeydown handler and no role+tabindex (WCAG 2.1.1); axe misses this, IBM finds it
  hidden_input_widget     a radio/checkbox hidden with display:none (the CSS radio trick): cannot take focus (WCAG 2.1.1)
  svg_no_name             an <svg> with no aria-hidden / role=img / label / <title> (WCAG 1.1.1)
"""
import argparse, collections, functools, http.server, json, os, re, subprocess, sys, tempfile, threading, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_items(src):
    p = Path(src)
    if p.is_dir():
        return {f.stem: f.read_text() for f in sorted(p.glob('*.html'))}
    d = json.loads(p.read_text())
    if isinstance(d, dict) and 'html' in d and isinstance(d['html'], dict):
        d = d['html']
    return {str(k): str(v) for k, v in d.items()}


def static_flags(html):
    f = []
    if re.search(r'animation[^;"}]*\binfinite\b|animation-iteration-count:\s*infinite', html) and 'prefers-reduced-motion' not in html:
        f.append('loop_no_reduced_motion')
    for cm in re.finditer(r'<canvas\b([^>]*)>', html):   # each canvas needs its own name, or a named parent directly around it
        own = re.search(r'aria-label=|aria-labelledby=|role="img"|aria-hidden="true"', cm.group(1))
        before = html[max(0, cm.start() - 400):cm.start()]
        parent = re.findall(r'<(?:div|span|figure|section)\b[^>]*>', before)
        near = bool(parent and re.search(r'aria-label=|role="img"|aria-hidden="true"', parent[-1]))
        if not own and not near:
            f.append('canvas_no_text_alt'); break
    for m in re.finditer(r'<(\w+)\b([^>]*)>', re.sub(r'<script\b.*?</script>', '', html, flags=re.S)):
        tag, at = m.group(1).lower(), m.group(2)
        if tag in ('th', 'td', 'tr') and re.search(r'\btabindex\s*=', at) and re.search(r'\bonkeydown\s*=', at):
            continue
        if tag in ('a', 'button', 'input', 'select', 'textarea', 'summary', 'label', 'option', 'details'):
            continue
        if re.search(r'\bon(?:click|keydown|keyup|mousedown)\s*=', at) and not (re.search(r'\btabindex\s*=', at) and re.search(r'\brole\s*=', at)):
            f.append('click_not_keyboard'); break
    for m in re.finditer(r'<input\b([^>]*)>', html):
        at = m.group(1)
        if re.search(r'type=["\']?(radio|checkbox)', at) and re.search(r'display:\s*none|\bhidden\b', at):
            f.append('hidden_input_widget'); break
    if 'hidden_input_widget' not in f and re.search(r'input(?:\[type=(?:radio|checkbox)\])?\s*\{\s*display:\s*none', html) and re.search(r'type=["\']?(radio|checkbox)', html):
        f.append('hidden_input_widget')   # the same trick in a <style> rule
    for m in re.finditer(r'<svg\b([^>]*)>(.{0,200})', html, re.S):
        at, rest = m.group(1), m.group(2)
        if not re.search(r'aria-hidden=|role=["\']img|aria-label=|aria-labelledby=', at) and not rest.lstrip().startswith('<title'):
            f.append('svg_no_name'); break
    return f


def static_applicable(html):
    """Which static checks could apply to this page at all (the element type is present). A check that cannot apply adds nothing to the
    denominator, so a page with no canvas is not credited for 'having no bad canvas'."""
    a = set()
    if re.search(r'animation|@keyframes', html): a.add('loop_no_reduced_motion')
    if '<canvas' in html: a.add('canvas_no_text_alt')
    if re.search(r'\bon(?:click|keydown|keyup|mousedown)\s*=', re.sub(r'<script\b.*?</script>', '', html, flags=re.S)): a.add('click_not_keyboard')
    if re.search(r'type=["\']?(radio|checkbox)', html): a.add('hidden_input_widget')
    if '<svg' in html: a.add('svg_no_name')
    return a


class JobTimeout(Exception):
    """The engine script ran past A11Y_JOB_TIMEOUT. Whatever it had already written to audit.json is kept."""


def node(script, td, *extra):
    """Run an engine script. Its progress lines (stderr) are shown as they happen. A script that runs past A11Y_JOB_TIMEOUT seconds
    (default 7200) is stopped and JobTimeout is raised; audit.mjs writes audit.json as it goes, so the pages done so far are not lost."""
    env = dict(os.environ)
    if not (HERE / 'node_modules').exists() and 'NODE_PATH' not in env:
        sys.exit(f'no node_modules next to {HERE}: run `npm install` there once')
    p = subprocess.Popen(['node', str(HERE / script), str(td), *extra], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=HERE, env=env)
    tail, chunks = collections.deque(maxlen=12), []

    def pump_err():
        for line in p.stderr:
            tail.append(line.rstrip())
            sys.stderr.write(line)
            sys.stderr.flush()

    def pump_out():
        chunks.append(p.stdout.read())
    threads = [threading.Thread(target=pump_err, daemon=True), threading.Thread(target=pump_out, daemon=True)]
    for th in threads:
        th.start()
    try:
        p.wait(timeout=int(os.environ.get('A11Y_JOB_TIMEOUT', 7200)))
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        for th in threads:
            th.join(2)
        raise JobTimeout(script)
    for th in threads:
        th.join(5)
    out = ''.join(chunks)
    if p.returncode:
        msg = next((ln for ln in reversed(tail) if re.search(r'\bError: ', ln)), None)   # the one-line reason, not the stack trace
        sys.exit(f'{script} failed: ' + (msg or '\n'.join(tail) or out)[-800:])
    return out.strip()


LAYERS = {'perceivable': 35, 'operable': 35, 'understandable': 15, 'robust': 15}
LAYER_OF = {'color': 'perceivable', 'text-alternatives': 'perceivable', 'sensory-and-visual-cues': 'perceivable', 'time-and-media': 'perceivable',
            'keyboard': 'operable', 'forms': 'understandable', 'language': 'understandable'}   # anything else (aria, name-role-value, structure, semantics, tables, parsing) is robust
STATIC_LAYER = {'click_not_keyboard': 'operable', 'hidden_input_widget': 'operable', 'loop_no_reduced_motion': 'operable', 'svg_no_name': 'perceivable', 'canvas_no_text_alt': 'perceivable'}
IMPACT_W = {'critical': 4, 'serious': 3, 'moderate': 2, 'minor': 1}
BANDS = [(90, 'A'), (75, 'B'), (55, 'C'), (35, 'D'), (0, 'F')]   # our own cut-offs; there is deliberately no A+, because no automated score means 'done'
STATIC_HELP = {
    'click_not_keyboard': 'A clickable non-control (span, div) has no role and tabindex, so a keyboard user cannot operate it (WCAG 2.1.1): use a real button or link.',
    'hidden_input_widget': 'A radio or checkbox is hidden with display:none, so it cannot take focus (WCAG 2.1.1): hide it visually and keep it focusable.',
    'svg_no_name': 'An svg has no accessible name or aria-hidden (WCAG 1.1.1): add role=img and a label, or aria-hidden if decorative.',
    'canvas_no_text_alt': 'A canvas has no text alternative (WCAG 1.1.1): add aria-label or a text equivalent.',
    'loop_no_reduced_motion': 'Endless CSS animation with no prefers-reduced-motion rule (WCAG 2.2.2, 2.3.3).',
}
BANNER = ('Automated checks only (axe-core plus a few static checks): they find roughly a third to a half of real issues. Keyboard order, screen-reader '
          'output, content quality and anything behind a login are not scored. A high score is not a conformance claim.')


import math


def jr(x):
    """JavaScript Math.round (half up), so the Python and the Worker scores agree."""
    return math.floor(x + 0.5)


def jr1(x):
    return math.floor(x * 10 + 0.5) / 10


def grade(score):
    return next(g for cut, g in BANDS if score >= cut)


def grade_word(g):
    return {'A': 'few automated findings', 'B': 'some automated findings', 'C': 'many automated findings', 'D': 'serious automated findings', 'F': 'severe automated findings'}[g]


def score_page(res, flags, drop=frozenset(), applicable=None):
    """One page. Per layer: the weight of the rules that passed over the weight of those that applied; failures weigh by axe impact.
    drop: check ids to treat as fixed (the what-if). Returns (score, layer scores, points lost per check, cap penalty)."""
    tot_w, lost = collections.Counter(), collections.Counter()
    fail = []                                   # (check id, layer, weight)
    for p in res.get('p', []):
        tot_w[LAYER_OF.get(p.get('cat'), 'robust')] += 2
    for v in res.get('v', []):
        L, w = LAYER_OF.get(v.get('cat'), 'robust'), IMPACT_W.get(v.get('impact'), 2)
        tot_w[L] += w
        if v['id'] not in drop:
            lost[L] += w; fail.append((v['id'], L, w, v.get('impact')))
    live_flags = [f for f in flags if f not in drop]
    for fl, L in STATIC_LAYER.items():
        if applicable is not None and fl not in applicable and fl not in flags:
            continue                            # no such element on the page: nothing to pass or fail
        tot_w[L] += 3
        if fl in live_flags:
            lost[L] += 3; fail.append((fl, L, 3, 'critical' if fl in ('click_not_keyboard', 'hidden_input_widget') else 'static'))
    used = {L: w for L, w in LAYERS.items() if tot_w[L]}
    if not used:
        return 100, {}, {}, 0
    layer = {L: 1 - lost[L] / tot_w[L] for L in used}
    base = 100 * sum(LAYERS[L] * layer[L] for L in used) / sum(used.values())
    pts = collections.Counter()                 # points this page lost to each check, before any cap
    for cid, L, w, _imp in fail:
        pts[cid] += 100 * (LAYERS[L] / sum(used.values())) * (w / tot_w[L])
    # Severity caps, so many passing checks cannot hide a barrier. A critical failure or a keyboard barrier (it stops a person using the page at all)
    # caps the page at 69; a serious failure at 84; three or more of either at 59.
    crit = sum(1 for f in fail if f[3] == 'critical')
    ser = sum(1 for f in fail if f[3] == 'serious')
    cap = 59 if crit + ser >= 3 else 69 if crit >= 1 else 84 if ser >= 1 else 100
    score = jr(min(base, cap))
    cap_loss = max(0.0, base - cap)
    severe = [f[0] for f in fail if f[3] in ('critical', 'serious')]
    for cid in set(severe):                     # the cap penalty is shared among the checks that set it
        pts[cid] += cap_loss / len(set(severe))
    return score, {L: jr(100 * v) for L, v in layer.items()}, dict(pts), jr1(cap_loss)


def site_score(inputs, drop=frozenset()):
    pages = {k: score_page(res, flags, drop, app) for k, (res, flags, app) in inputs.items()}
    if not pages:
        return 0, pages
    site = jr(sum(p[0] for p in pages.values()) / len(pages))
    capped = sum(1 for p in pages.values() if p[0] <= 84)
    blocked = sum(1 for p in pages.values() if p[0] <= 69)
    if blocked / len(pages) > 0.10:             # more than a tenth of pages with a barrier: not better than a C
        site = min(site, 69)
    elif capped / len(pages) > 0.25:            # more than a quarter with any serious problem: not better than a B
        site = min(site, 84)
    return site, pages


def build_report(audit, items, label, requested=None):
    inputs, errored, info = {}, {}, {}
    for k, v in sorted(audit.items()):
        if 'err' in v:
            errored[k] = v['err']
            continue
        flags = static_flags(items[k] if k in items else v.get('src', ''))
        src = items[k] if k in items else v.get('src', '')
        inputs[k] = (v, flags, static_applicable(src))
        for x in v.get('v', []):
            e = info.setdefault(x['id'], {'id': x['id'], 'impact': x.get('impact'), 'help': x.get('help'), 'url': x.get('url'), 'pages': 0, 'nodes': 0})
            e['pages'] += 1; e['nodes'] += x['nodes']
        for fl in flags:
            e = info.setdefault(fl, {'id': fl, 'impact': 'static', 'help': STATIC_HELP.get(fl, 'static check'), 'url': None, 'pages': 0, 'nodes': 0})
            e['pages'] += 1
    site, pages = site_score(inputs)
    n = max(len(pages), 1)
    pts_total, cap_total = collections.Counter(), 0.0
    for k, (sc, layers, pts, cap_loss) in pages.items():
        for cid, p in pts.items():
            pts_total[cid] += p
        cap_total += cap_loss
    for cid, e in info.items():
        e['points_lost'] = jr1(pts_total[cid] / n)                      # average points this check cost per page
        e['gain_if_fixed_alone'] = site_score(inputs, frozenset([cid]))[0] - site
    # fix order: greedy; at each step fix the check whose removal raises the site score most (ties: most points lost)
    order, dropped, cur = [], set(), site
    left = set(info)
    while left and len(order) < 12:
        best = max(sorted(left), key=lambda c: (site_score(inputs, frozenset(dropped | {c}))[0], info[c]['points_lost']))   # sorted: ties break the same way everywhere
        new = site_score(inputs, frozenset(dropped | {best}))[0]
        order.append({'fix': best, 'score_before': cur, 'score_after': new, 'grade_after': grade(new), 'pages': info[best]['pages']})
        dropped.add(best); left.discard(best); cur = new
    capped = sum(1 for p in pages.values() if p[0] <= 84)
    rep = {'target': label, 'pages_scanned': len(pages), 'score': site, 'grade': grade(site), 'grade_word': grade_word(grade(site)),
            'points_lost_to_severity_caps': jr1(cap_total / n), 'fix_order': order,
            'pages_with_severe_barriers': capped, 'pages_not_audited': errored,
            'worst_pages': sorted(({'page': k, 'score': p[0]} for k, p in pages.items()), key=lambda x: x['score'])[:5],
            'failing_checks': sorted(info.values(), key=lambda e: (-e['points_lost'], -e['pages'])),
            'pages': {k: {'score': p[0], 'grade': grade(p[0]), 'layers': p[1], 'static_flags': inputs[k][1]} for k, p in pages.items()}, 'note': BANNER}
    if requested is not None:
        missing = [k for k in requested if k not in audit]
        rep['pages_requested'] = len(requested)
        rep['pages_missing'] = missing           # asked for, but never audited (the run was stopped); pages_not_audited has those that errored
        rep['coverage'] = jr1(100 * len(pages) / max(len(requested), 1))
    return rep


def tot(d, rule):
    return sum(r.get(rule, 0) for r in d.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--items', default='', help='fragments: items.json or a folder of .html files')
    ap.add_argument('--url', default='', help='scan a live site: this page, plus same-origin links with --crawl')
    ap.add_argument('--urls', default='', help='scan the pages listed (one URL per line) in this file')
    ap.add_argument('--sitemap', default='', help='scan the pages listed in this sitemap.xml URL')
    ap.add_argument('--dir', default='', help='scan a built site: serve this folder locally and audit every .html page in it')
    ap.add_argument('--audit-out', default='', help='also write the raw audit data (for comparing scoring versions offline)')
    ap.add_argument('--score', action='store_true', help='score 0-100 with a grade, layer breakdown and the failing checks (scan, score, fix, rescan; see the README for where the idea comes from)')
    ap.add_argument('--json', action='store_true', help='with --score: the full report as JSON')
    ap.add_argument('--min-score', type=int, default=None, help='with --score: exit 1 when the site score is below this')
    ap.add_argument('--min-coverage', type=float, default=90.0, help='with --min-score: exit 3 when fewer than this percent of the requested pages could be audited (default 90)')
    ap.add_argument('--allow-partial', action='store_true', help='with --min-score: do not fail the gate on low coverage')
    ap.add_argument('--crawl', action='store_true', help='with --url: follow same-origin links')
    ap.add_argument('--path-scope', action='store_true', help='with --crawl: stay under the start URL\'s folder, not just its origin')
    ap.add_argument('--max-pages', type=int, default=30)
    ap.add_argument('--depth', type=int, default=2)
    ap.add_argument('--delay', type=int, default=500, help='ms between page loads when crawling')
    ap.add_argument('--confirm-permission', action='store_true', help='required for any host other than localhost: you own the site or have permission to test it')
    ap.add_argument('--shell', default='')
    ap.add_argument('--baseline', default='')
    ap.add_argument('--theme', choices=['light', 'dark'], default='light')
    ap.add_argument('--update', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--static', action='store_true')
    ap.add_argument('--tabwalk', action='store_true')
    ap.add_argument('--crosscheck', action='store_true')
    ap.add_argument('--only', default='', help='comma list of item names (tabwalk / crosscheck)')
    a = ap.parse_args()
    live = bool(a.url or a.urls or a.sitemap or a.dir)
    items = {} if live else load_items(a.items) if a.items else {}
    if not live and not items:
        sys.exit('give --items, or one of --url / --urls / --sitemap / --dir')
    server = None
    urls = {}
    if a.dir:
        root = Path(a.dir).resolve()
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
        handler.log_message = lambda *x, **k: None
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_address[1]}'
        for f in sorted(root.rglob('*.html')):
            rel = f.relative_to(root).as_posix()
            urls['/' + rel] = base + '/' + urllib.parse.quote(rel)
    elif a.urls:
        for ln in Path(a.urls).read_text().splitlines():
            ln = ln.split('#')[0].strip()
            if ln:
                urls[urllib.parse.urlparse(ln).path or '/'] = ln
    elif a.sitemap:
        with urllib.request.urlopen(a.sitemap, timeout=30) as resp:
            xml = resp.read().decode('utf8', 'replace')
        for loc in re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', xml)[:a.max_pages]:
            urls[urllib.parse.urlparse(loc).path or '/'] = loc
    if live:
        hosts = {urllib.parse.urlparse(u).hostname for u in ([a.url] if a.url else []) + list(urls.values())}
        if hosts - {'localhost', '127.0.0.1'} and not a.confirm_permission:
            sys.exit('refusing to scan ' + ', '.join(sorted(h for h in hosts - {'localhost', '127.0.0.1'} if h)) + ': scan only sites you own or have permission to test, and say so with --confirm-permission')
    if a.static:
        c = collections.defaultdict(list)
        for k, h in sorted(items.items()):
            for fl in static_flags(h):
                c[fl].append(k)
        for fl, ks in sorted(c.items()):
            print(f'{fl}: {len(ks)}\n   ' + ' '.join(ks))
        print(f'{len(items)} items, {sum(len(v) for v in c.values())} static flags')
        return 1 if c and not a.update and a.baseline and not Path(a.baseline).exists() else 0
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        if live:
            if a.url and not a.crawl:
                urls = {urllib.parse.urlparse(a.url).path or '/': a.url}
            if a.url and a.crawl:
                print(node('crawl.mjs', td, a.url, '--max', str(a.max_pages), '--depth', str(a.depth), '--delay', str(a.delay), *(['--path-scope'] if a.path_scope else [])), file=sys.stderr)
                urls = json.loads((td / 'html.json').read_text())['urls']
            if not urls:
                sys.exit('no pages to scan')
            urls = dict(list(urls.items())[:a.max_pages])
            (td / 'html.json').write_text(json.dumps({'urls': urls}))
        else:
            (td / 'html.json').write_text(json.dumps({'html': items, 'stage': {}}))
        (td / 'shell.css').write_text(Path(a.shell).read_text() if a.shell else '')
        if a.tabwalk:
            node('tabwalk.mjs', td, a.theme, a.only)
            tw = json.loads((td / 'tabwalk.json').read_text())
            cur = {k: v['findings'] for k, v in tw.items() if v.get('findings')}
            tot_ = collections.Counter(rr for v in cur.values() for rr in v)
            print(f'{len(tw)} items walked ({a.theme} page); items with a finding: {len(cur)}; by rule: {dict(tot_)}')
            for k, v in sorted(tw.items()):
                for d in v.get('detail', [])[:3]:
                    print('  ', k, d[:140])
            return 1 if cur else 0
        if a.crosscheck:
            print(node('audit.mjs', td, a.theme))
            for eng in ('htmlcs', 'ibm'):
                print(node('crosscheck.mjs', td, a.theme, eng, a.only))
            r = subprocess.run([sys.executable, str(HERE / 'crosscheck_report.py'), str(td), '--theme', a.theme], capture_output=True, text=True)
            print(r.stdout or r.stderr)
            return 0
        timed_out = False
        try:
            print(node('audit.mjs', td, a.theme), file=sys.stderr)    # progress goes to stderr so that --json output stays pure JSON
        except JobTimeout:
            timed_out = True
            print('STOPPED: the audit ran past A11Y_JOB_TIMEOUT; the score below covers only the pages finished so far.', file=sys.stderr)
        audit = json.loads((td / 'audit.json').read_text()) if (td / 'audit.json').exists() else {}
        requested = list(json.loads((td / 'html.json').read_text()).get('urls', json.loads((td / 'html.json').read_text()).get('html', {})))
    cur = {'axe': {}, 'static': {}}
    pairs = collections.defaultdict(list)
    errors = [k for k, v in audit.items() if 'err' in v]
    for k, v in sorted(audit.items()):
        rules = {x['id']: x['nodes'] for x in v.get('v', [])}
        for x in v.get('v', []):
            for fg, bg, ratio in (x.get('pairs') or []):
                pairs[(fg, bg)].append((k, ratio))
        if rules:
            cur['axe'][k] = rules
        fl = static_flags(items[k] if k in items else v.get('src', ''))
        if fl:
            cur['static'][k] = fl
    if server:
        server.shutdown()
    if a.audit_out:
        Path(a.audit_out).write_text(json.dumps({'audit': audit, 'items': items}))
    if a.score or a.json or a.min_score is not None:
        rep = build_report(audit, items, a.url or a.sitemap or a.dir or a.urls or a.items, requested)
        if rep['pages_scanned'] == 0:
            print('no pages could be audited' + (f" ({len(rep['pages_not_audited'])} errored, {len(rep.get('pages_missing', []))} never finished)" if requested else ''), file=sys.stderr)
            return 3
        if a.json:
            print(json.dumps(rep, indent=1))
        else:
            print(f"score {rep['score']}/100  grade {rep['grade']} ({rep['grade_word']})  {rep['pages_scanned']} of {rep.get('pages_requested', rep['pages_scanned'])} page(s)/item(s) scored" + ('' if rep.get('coverage', 100) >= 100 else f"  *** PARTIAL: {rep['coverage']}% covered ***"))
            for k, p in sorted(rep['pages'].items(), key=lambda kv: kv[1]['score'])[:12]:
                print(f"  {p['score']:3d} {p['grade']:2s}  {k}  " + ' '.join(f'{L[:4]}={v}' for L, v in p['layers'].items()))
            if rep['pages_not_audited']:
                print(f"NOT AUDITED ({len(rep['pages_not_audited'])}): " + '; '.join(f'{k} [{e}]' for k, e in list(rep['pages_not_audited'].items())[:5]) + '  (the score covers only the pages that were audited)')
            print(f"points lost to severity caps (average per page): {rep['points_lost_to_severity_caps']}")
            print('where the points went (average points lost per page; score gain if that check alone were fixed; pages hit):')
            for e in rep['failing_checks'][:12]:
                print(f"  {e['id']:30s} -{e['points_lost']:5.1f}  +{e['gain_if_fixed_alone']:<3d} {e['pages']:3d} page(s)  {e['impact'] or '':9s} {e['help'] or ''}" + (f"  {e['url']}" if e['url'] else ''))
            print('fix order (assumes EVERY instance of a check is fixed; each step re-scores the whole site; fixing the top check alone can show +0 when another check still holds the same pages down):')
            for i, s in enumerate(rep['fix_order'][:8], 1):
                print(f"  {i}. fix {s['fix']:28s} {s['score_before']} -> {s['score_after']} ({s['grade_after']})")
            print('NOTE: ' + BANNER)
        if a.min_score is not None and rep['score'] < a.min_score:
            print(f"score {rep['score']} is below --min-score {a.min_score}", file=sys.stderr)
            return 1
        if a.min_score is not None and rep.get('coverage', 100) < a.min_coverage and not a.allow_partial:
            print(f"only {rep['coverage']}% of the requested pages were audited (--min-coverage {a.min_coverage}): the score is not trustworthy as a gate. "
                  "Raise A11Y_NAV_TIMEOUT / A11Y_JOB_TIMEOUT, scan in smaller batches, or pass --allow-partial.", file=sys.stderr)
            return 3
        return 0
    print(f"{len(audit)} items audited ({a.theme} page), {len(errors)} errors; axe violations in {len(cur['axe'])} items, static flags in {len(cur['static'])}")
    if a.report or not a.baseline:
        c = collections.Counter(r for rules in cur['axe'].values() for r in rules)
        for r_, k in c.most_common():
            print(f'  {r_:32s} {k:4d} items')
        for (fg, bg), lst in sorted(pairs.items(), key=lambda kv: -len(kv[1]))[:12]:
            print(f'    {fg} on {bg}  nodes={len(lst):3d} items={len({x for x, _ in lst}):3d} ratio={lst[0][1]}')
        for f_, k in collections.Counter(f for fl in cur['static'].values() for f in fl).most_common():
            print(f'  {f_:32s} {k:4d} items')
        return 0
    base_path = Path(a.baseline)
    if a.update or not base_path.exists():
        base_path.write_text(json.dumps(cur, indent=1, sort_keys=True) + '\n')
        print('baseline written ->', base_path)
        return 0
    base = json.loads(base_path.read_text())
    new, fixed = [], []
    for k, rules in cur['axe'].items():
        for r_, nodes in rules.items():
            was = base['axe'].get(k, {}).get(r_)
            if was is None:
                new.append(f'{k}: {r_} ({nodes} nodes)' + ('  [not in the baseline: a new item must start clean]' if k not in base['axe'] else ''))
            elif nodes > was:
                new.append(f'{k}: {r_} got worse ({was} -> {nodes} nodes)')
    for k, rules in base['axe'].items():
        for r_, was in rules.items():
            now = cur['axe'].get(k, {}).get(r_, 0)
            if now < was:
                fixed.append(f'{k}: {r_} {was} -> {now}')
    for k, fl in cur['static'].items():
        for f_ in fl:
            if f_ not in base['static'].get(k, []):
                new.append(f'{k}: {f_}')
    for k, fl in base['static'].items():
        for f_ in fl:
            if f_ not in cur['static'].get(k, []):
                fixed.append(f'{k}: {f_} fixed')
    print(f"color-contrast failing nodes: baseline {tot(base['axe'], 'color-contrast')} -> now {tot(cur['axe'], 'color-contrast')}")
    print(f'NEW {len(new)}   fixed since baseline {len(fixed)}')
    for x in new[:40]:
        print('  NEW  ', x)
    if fixed:
        print(f'  ({len(fixed)} fixed; run with --update to lock the gain in)')
    return 1 if new else 0


if __name__ == '__main__':
    sys.exit(main())
