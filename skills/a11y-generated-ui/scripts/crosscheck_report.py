#!/usr/bin/env python3
"""Compare axe-core, HTML_CodeSniffer and IBM Equal Access over the same rendered items. ratchet.py --crosscheck runs the engines and calls this.

  python3 crosscheck_report.py <dir with audit.json, htmlcs-<theme>.json, ibm-<theme>.json> [--theme light|dark] [--list contrast|name|other]

Three engines are three opinions, not a verdict. Where two or more agree an item is very likely a real finding; where only one flags it,
look by hand (axe cannot evaluate text over gradients; HTMLCS contrast needs a computable background; IBM is stricter on form patterns)."""
import collections, json, re, sys
from pathlib import Path
d = Path(sys.argv[1])
theme = 'dark' if '--theme' in sys.argv and sys.argv[sys.argv.index('--theme') + 1] == 'dark' else 'light'
show = sys.argv[sys.argv.index('--list') + 1] if '--list' in sys.argv else None
audit = json.loads((d / 'audit.json').read_text())
axe = {k: {x['id']: x['nodes'] for x in v.get('v', [])} for k, v in audit.items()}
hc = json.loads((d / f'htmlcs-{theme}.json').read_text())
ib = json.loads((d / f'ibm-{theme}.json').read_text())

def cat_axe(r): return 'contrast' if r == 'color-contrast' else 'name' if r in ('label', 'select-name', 'button-name', 'link-name', 'image-alt', 'svg-img-alt', 'frame-title', 'input-image-alt', 'aria-input-field-name') else 'other'
def cat_hc(r): return 'contrast' if re.search(r'1_4_3\.(G18|G145)', r) else 'name' if re.search(r'4_1_2\.H91\.\w+\.Name|1_3_1\.F68|1_1_1\.H37|2_4_4\.H77|1_1_1\.H30', r) else 'other'
def cat_ib(r): return 'contrast' if 'contrast' in r else 'name' if re.search(r'input_label|img_alt|a_text_purpose|frame_title|svg_graphics_labelled|aria_.*(name|label)|label_', r) else 'other'

items = sorted(set(hc) | set(ib) | set(axe))
flag = {'axe': collections.defaultdict(set), 'htmlcs': collections.defaultdict(set), 'ibm': collections.defaultdict(set)}
for a in items:
    for r in axe.get(a, {}): flag['axe'][cat_axe(r)].add(a)
    for x in (hc.get(a, {}).get('v') or []): flag['htmlcs'][cat_hc(x['rule'])].add(a)
    for x in (ib.get(a, {}).get('v') or []): flag['ibm'][cat_ib(x['rule'])].add(a)
errs = {n: sum(1 for v in e.values() if 'err' in v) for n, e in (('htmlcs', hc), ('ibm', ib))}
print(f'{theme} host page, {len(items)} items. engine errors: {errs}')
print(f'{"category":10s} {"axe":>5s} {"htmlcs":>7s} {"ibm":>5s} | {">=2 agree":>10s} {"all 3":>6s} {"only 1":>7s}')
for cat in ('contrast', 'name', 'other'):
    s = {e: flag[e][cat] for e in flag}
    union = set().union(*s.values()); cnt = {a: sum(a in s[e] for e in s) for a in union}
    print(f'{cat:10s} {len(s["axe"]):5d} {len(s["htmlcs"]):7d} {len(s["ibm"]):5d} | {sum(c >= 2 for c in cnt.values()):10d} {sum(c == 3 for c in cnt.values()):6d} {sum(c == 1 for c in cnt.values()):7d}')
anyflag = {e: set().union(*flag[e].values()) for e in flag}
print(f'items with ANY finding: axe {len(anyflag["axe"])}, htmlcs {len(anyflag["htmlcs"])}, ibm {len(anyflag["ibm"])}; flagged by all three {len(anyflag["axe"] & anyflag["htmlcs"] & anyflag["ibm"])}')
if show:
    s = {e: flag[e][show] for e in flag}
    print(f'\n{show}: item -> engines that flag it')
    for a in sorted(set().union(*s.values())): print('  ', f'{a:30s}', ','.join(e for e in s if a in s[e]))

# Exit code: 1 when two or more engines flag the same item in the same category (very likely a real finding); 0 otherwise. ratchet.py --crosscheck passes it on.
agreed = sum(1 for cat in ('contrast', 'name', 'other') for a in set().union(*(flag[e][cat] for e in flag)) if sum(a in flag[e][cat] for e in flag) >= 2)
print(f'findings that >= 2 engines agree on: {agreed}')
sys.exit(1 if agreed else 0)
