"""Smoke tests: static flags need no browser; the ratchet and the live modes need Chromium and `npm install` in scripts/ (skipped otherwise)."""
import json, subprocess, sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
SCRIPTS = HERE / 'scripts'
ITEMS = HERE / 'examples' / 'items.json'
sys.path.insert(0, str(SCRIPTS))
HAVE_BROWSER = (SCRIPTS / 'node_modules').exists()
browser = pytest.mark.skipif(not HAVE_BROWSER, reason='run npm install in scripts/')


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPTS / 'ratchet.py'), *args], capture_output=True, text=True, timeout=600)


def test_static_flags_find_the_five_known_failures():
    out = run('--items', str(ITEMS), '--static').stdout
    for flag, item in (('click_not_keyboard', 'click_on_span'), ('hidden_input_widget', 'css_radio_tabs'), ('svg_no_name', 'unnamed_svg'),
                       ('canvas_no_text_alt', 'canvas_no_alt'), ('loop_no_reduced_motion', 'endless_spinner')):
        assert flag in out and item in out, out


def test_a_remote_host_is_refused_without_permission():
    r = run('--url', 'https://example.com', '--crawl')
    assert r.returncode != 0 and 'confirm-permission' in (r.stderr + r.stdout)


@browser
def test_ratchet_passes_on_rerun_and_fails_on_a_new_bad_item(tmp_path):
    base = tmp_path / 'b.json'
    assert run('--items', str(ITEMS), '--baseline', str(base)).returncode == 0       # writes it
    assert run('--items', str(ITEMS), '--baseline', str(base)).returncode == 0       # unchanged
    d = json.loads(ITEMS.read_text()); d['new_pale'] = '<p style="color:#bbb;background:#fff">pale</p>'
    items2 = tmp_path / 'i2.json'; items2.write_text(json.dumps(d))
    r = run('--items', str(items2), '--baseline', str(base))
    assert r.returncode == 1 and 'new_pale' in r.stdout


@browser
def test_dir_mode_audits_a_local_page(tmp_path):
    (tmp_path / 'index.html').write_text('<!doctype html><html lang="en"><title>t</title><main><p style="color:#aaa;background:#fff">pale</p></main></html>')
    r = run('--dir', str(tmp_path), '--report')
    assert 'color-contrast' in r.stdout, r.stdout + r.stderr


@browser
def test_score_caps_severe_pages_and_min_score_gates(tmp_path):
    bad = tmp_path / 'bad.html'
    r = run('--items', str(ITEMS), '--score', '--json')
    rep = json.loads(r.stdout[r.stdout.index('{'):])
    assert rep['pages']['click_on_span']['score'] <= 69 and rep['pages']['ok_button']['score'] == 100, rep['pages']
    assert 'not a conformance claim' in rep['note']
    assert run('--items', str(ITEMS), '--score', '--min-score', '99').returncode == 1
