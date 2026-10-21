"""Fixes from the second roast (October 2026): the ratchet must not fail open, --baseline must not be ignored, a site score must not dilute away a barrier.
The ratchet tests stub the engine with a fake `node` on PATH, so they need neither Chromium nor npm packages and run in seconds."""
import json, os, stat, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SCRIPTS = HERE / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import ratchet  # noqa: E402

CONTRAST = {'id': 'color-contrast', 'impact': 'serious', 'nodes': 1, 'cat': 'color', 'sc': ['wcag143'], 'help': 'h', 'url': 'u'}


def fake_node(tmp_path, audit, sleep=0):
    """A `node` that ignores the engine script and writes `audit` as audit.json into the work dir (argv[2]), then optionally hangs."""
    d = tmp_path / 'bin'
    d.mkdir(exist_ok=True)
    (tmp_path / 'audit.json').write_text(json.dumps(audit))
    f = d / 'node'
    f.write_text(f'#!/bin/sh\ncp {tmp_path}/audit.json "$2/audit.json"\n' + (f'sleep {sleep}\n' if sleep else ''))
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return d


def run(tmp_path, audit, *args, sleep=0, timeout='2'):
    env = dict(os.environ, PATH=str(fake_node(tmp_path, audit, sleep)) + os.pathsep + os.environ['PATH'], NODE_PATH='/nonexistent', A11Y_JOB_TIMEOUT=timeout)
    return subprocess.run([sys.executable, str(SCRIPTS / 'ratchet.py'), *args], capture_output=True, text=True, timeout=60, env=env)


def setup(tmp_path, base_axe=None):
    items = tmp_path / 'items.json'
    items.write_text(json.dumps({'a': '<p>x</p>', 'b': '<p>y</p>'}))
    base = tmp_path / 'base.json'
    base.write_text(json.dumps({'axe': base_axe or {}, 'static': {}}))
    return items, base


# ---- 1. the ratchet must not fail open when the audit is cut short ---------------------------------------------------------------------------------

def test_ratchet_exits_3_when_items_were_never_audited(tmp_path):
    items, base = setup(tmp_path)
    r = run(tmp_path, {'a': {'v': [], 'p': []}}, '--items', str(items), '--baseline', str(base), sleep=30)      # 'b' (which has a NEW defect) never finishes
    assert r.returncode == 3, r.stdout + r.stderr
    assert 'never audited' in r.stderr and 'b' in r.stderr and 'NEW 0' not in r.stdout


def test_update_is_refused_from_a_partial_run(tmp_path):
    items, base = setup(tmp_path, {'b': {'color-contrast': 1}})
    before = base.read_text()
    r = run(tmp_path, {'a': {'v': [], 'p': []}}, '--items', str(items), '--baseline', str(base), '--update', sleep=30)
    assert r.returncode == 3, r.stdout + r.stderr
    assert base.read_text() == before, 'a partial run rewrote the baseline'


def test_a_complete_run_still_passes_and_updates(tmp_path):
    items, base = setup(tmp_path)
    full = {'a': {'v': [], 'p': []}, 'b': {'v': [], 'p': []}}
    assert run(tmp_path, full, '--items', str(items), '--baseline', str(base)).returncode == 0
    assert run(tmp_path, full, '--items', str(items), '--baseline', str(base), '--update').returncode == 0


# ---- 3. --score / --min-score must not silently ignore --baseline ----------------------------------------------------------------------------------

def test_score_and_baseline_run_both_and_the_worst_exit_code_wins(tmp_path):
    items, base = setup(tmp_path)
    audit = {'a': {'v': [], 'p': []}, 'b': {'v': [CONTRAST], 'p': []}}       # b has a defect that is not in the baseline
    r = run(tmp_path, audit, '--items', str(items), '--baseline', str(base), '--score', '--min-score', '0')
    assert r.returncode == 1, r.stdout + r.stderr          # the score gate passes (min 0); the ratchet must still fail
    assert 'score ' in r.stdout and 'NEW 1' in r.stdout
    clean = {'a': {'v': [], 'p': []}, 'b': {'v': [], 'p': []}}
    assert run(tmp_path, clean, '--items', str(items), '--baseline', str(base), '--score', '--min-score', '0').returncode == 0
    assert run(tmp_path, clean, '--items', str(items), '--baseline', str(base), '--score', '--min-score', '101').returncode == 1


# ---- 4. a site score must not dilute a barrier away --------------------------------------------------------------------------------------------

def page(impact=None, sc='wcag211'):
    res = {'v': [{'id': 'x-' + (impact or ''), 'impact': impact, 'nodes': 1, 'sc': [sc]}] if impact else [], 'p': [{'id': 'p%d' % i, 'impact': 'moderate', 'sc': ['wcag131']} for i in range(20)]}
    return (res, [], set())


def test_clean_pages_cannot_lift_a_site_with_barriers_to_an_A():
    barriers = {'bar1': page('critical'), 'bar2': page('critical')}
    small = ratchet.site_score(barriers)[0]
    big = ratchet.site_score({**barriers, **{f'clean{i}': page() for i in range(60)}})[0]
    assert ratchet.grade(big) != 'A', big
    assert big <= 84, big                                  # a blocking page means no A; the site is at best a B
    assert ratchet.site_score({f'clean{i}': page() for i in range(60)})[0] >= 90      # but a clean site is still an A


def test_three_blocking_pages_hold_a_large_site_at_C():
    inputs = {f'bar{i}': page('critical') for i in range(3)}
    inputs.update({f'clean{i}': page() for i in range(200)})
    assert ratchet.site_score(inputs)[0] <= 69



# ---- minor items: clean errors instead of tracebacks, and the exit code for "could not audit" ---------------------------------------------------------

def plain(*args):
    return subprocess.run([sys.executable, str(SCRIPTS / 'ratchet.py'), *args], capture_output=True, text=True, timeout=60)


def test_wrong_items_and_shell_paths_give_one_line_errors():
    for args in (('--items', '/nope/items.json', '--score'), ('--items', str(HERE / 'examples' / 'items.json'), '--shell', '/nope.css', '--score')):
        r = plain(*args)
        assert r.returncode == 1 and 'Traceback' not in r.stderr and ('no such file' in r.stderr), r.stderr


def test_missing_node_modules_exits_3_and_says_npm_ci(tmp_path):
    env = dict(os.environ, PATH=str(fake_node(tmp_path, {})) + os.pathsep + os.environ['PATH'])
    env.pop('NODE_PATH', None)
    code = "import sys; sys.path.insert(0, %r); import ratchet; ratchet.HERE = __import__('pathlib').Path(%r); ratchet.node('audit.mjs', '.')" % (str(SCRIPTS), str(tmp_path))
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 3 and 'npm ci' in r.stderr, r.stderr


# ---- the README demo must match what the quick start prints -----------------------------------------------------------------------------------------

def test_readme_demo_matches_the_quick_start():
    if not (SCRIPTS / 'node_modules').exists():
        import pytest
        pytest.skip('run npm ci in scripts/')
    readme = (HERE.parent.parent / 'README.md').read_text()
    demo = readme.split('```text\n', 1)[1].split('```', 1)[0].splitlines()
    out = subprocess.run([sys.executable, str(SCRIPTS / 'ratchet.py'), '--items', str(HERE / 'examples' / 'items.json'), '--score'], capture_output=True, text=True, timeout=300).stdout.splitlines()
    for ln in demo:
        if '...' in ln:
            continue                                   # the trimmed fix-order heading
        assert ln in out, f'README demo line not in the real output: {ln!r}'
