"""Pure checks (no browser): the address classifier behind the network guard, and the coverage fields of the report."""
import json, subprocess, sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / 'scripts'))
import ratchet  # noqa: E402


def classify(*ips):
    code = "import {classify} from './lib.mjs'; console.log(JSON.stringify(process.argv.slice(1).map(classify)));"
    r = subprocess.run(['node', '--input-type=module', '-e', code, *ips], capture_output=True, text=True, cwd=HERE / 'scripts', timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_address_classes():
    assert classify('169.254.169.254', 'fe80::1', '10.1.2.3', '172.16.0.1', '172.32.0.1', '192.168.0.9', '100.64.0.1', '127.0.0.1', '::1', '8.8.8.8',
                    '::ffff:10.0.0.1', 'fd00::1', '2606:4700::1111') == [
        'link-local', 'link-local', 'private', 'private', 'public', 'private', 'private', 'loopback', 'loopback', 'public', 'private', 'private', 'public']


def test_report_says_how_much_was_covered():
    audit = {'a': {'v': [], 'p': []}, 'b': {'err': 'Navigation timeout of 40000 ms exceeded'}}
    rep = ratchet.build_report(audit, {'a': '<p>x</p>'}, 'x', requested=['a', 'b', 'c'])
    assert rep['pages_scanned'] == 1 and rep['pages_requested'] == 3 and rep['pages_missing'] == ['c'] and rep['coverage'] == 33.3
    assert 'b' in rep['pages_not_audited']
    assert 'coverage' not in ratchet.build_report(audit, {'a': '<p>x</p>'}, 'x')      # the old call shape is unchanged


def test_experimental_wcag_rules_are_switched_on_by_audit():
    src = (HERE / 'scripts' / 'audit.mjs').read_text()
    assert "r.tags.includes('experimental')" in src and "axe.getRules()" in src      # derived from the installed axe, not a hand list


# ---- fixes from the independent reviews (October 2026) ------------------------------------------------------------------------------------------

def test_address_classifier_handles_hex_mapped_and_special_forms():
    got = classify('::ffff:a9fe:a9fe', '::ffff:a00:1', '::ffff:7f00:1', '::', 'fec0::1', '64:ff9b::a9fe:a9fe', '2002:a9fe:a9fe::', '2001:0:4136:e378:8000:63bf:3fff:fdd2',
                   'ff02::1', '198.19.0.1', '224.0.0.1', 'nonsense', '::ffff:808:808', '2606:4700::1111')
    assert got == ['link-local', 'private', 'loopback', 'loopback', 'private', 'link-local', 'link-local', 'private',
                   'private', 'private', 'private', 'private', 'public', 'public']


def test_urls_are_vetted_by_scheme_and_by_loopback_origin():
    code = """import {vetUrl, declareTargets} from './lib.mjs';
declareTargets({urls: {a: 'http://127.0.0.1:8777/'}});
const out = [];
for (const u of process.argv.slice(1)) { try { await vetUrl(u); out.push('ok'); } catch (e) { out.push('blocked'); } }
console.log(JSON.stringify(out));"""
    urls = ['http://127.0.0.1:8777/a', 'http://127.0.0.1:9999/', 'http://localhost:8777/', 'ws://127.0.0.1:8777/', 'file:///etc/passwd', 'http://2852039166/', 'data:text/plain,x', 'http://[::ffff:a9fe:a9fe]/']
    r = subprocess.run(['node', '--input-type=module', '-e', code, *urls], capture_output=True, text=True, cwd=HERE / 'scripts', timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ['ok', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked', 'ok', 'blocked']


STATIC_CASES = [
    ('<svg role="img"><path d="M0 0h10v10z"/></svg>', ['svg_no_name']),
    ('<svg aria-hidden="false"><path/></svg>', ['svg_no_name']),
    ('<svg role="img" aria-label="Chart"><path/></svg>', []),
    ('<svg><title>Chart</title><path/></svg>', []),
    ('<svg aria-hidden="true"><path/></svg>', []),
    ('<canvas role="img"></canvas>', ['canvas_no_text_alt']),
    ('<canvas>Sales: 12 units</canvas>', []),
    ('<canvas aria-label="Sales"></canvas>', []),
    ('<input type="checkbox" aria-hidden="false">', []),
    ('<input type="checkbox" hidden>', ['hidden_input_widget']),
    ('<input type="radio" style="display:none">', ['hidden_input_widget']),
    ('<div role="button" tabindex="-1" onclick="save()">Save</div>', ['click_not_keyboard']),
    ('<div role="button" tabindex="0" onclick="save()">Save</div>', []),
    ('<button onclick="x()">Save</button>', []),
    ('<span onclick="x()">go</span>', ['click_not_keyboard']),
    ('<style>/*prefers-reduced-motion*/.x{animation:spin 1s infinite}</style>', ['loop_no_reduced_motion']),
    ('<style>.x{animation:spin 1s infinite}@media (prefers-reduced-motion: reduce){.x{animation:none}}</style>', []),
]


def test_static_checks_on_the_cases_the_reviews_found():
    wrong = [(h, ratchet.static_flags(h), want) for h, want in STATIC_CASES if ratchet.static_flags(h) != want]
    assert not wrong, wrong


def test_adding_a_defect_never_raises_the_score():
    base = {'v': [{'id': 'svg-img-alt', 'impact': 'serious', 'nodes': 1, 'cat': 'text-alternatives'}], 'p': []}
    plain, svg = '<p>x</p>', '<svg role="img"></svg>'
    alone = ratchet.score_page(base, ratchet.static_flags(plain), frozenset(), ratchet.static_applicable(plain))[0]
    worse = ratchet.score_page(base, ratchet.static_flags(svg), frozenset(), ratchet.static_applicable(svg))[0]
    assert worse <= alone


def test_a_page_with_nothing_assessable_is_not_assessed_not_perfect():
    assert ratchet.score_page({'v': [], 'p': []}, [], frozenset(), set())[0] is None
    site, _ = ratchet.site_score({'a': ({'v': [], 'p': []}, [], set())})
    assert site == 0


def test_site_rules_follow_the_real_cap_not_the_score():
    # a page with many moderate failures can score below 69 with no serious or critical failure: it must not count as a barrier
    moderate = {'v': [{'id': f'm{i}', 'impact': 'moderate', 'nodes': 1, 'cat': 'forms'} for i in range(8)], 'p': []}
    s = ratchet.score_page(moderate, [], frozenset(), set())
    assert s[4] is None
    serious = {'v': [{'id': 'color-contrast', 'impact': 'serious', 'nodes': 1, 'cat': 'color'}], 'p': [{'id': 'x', 'impact': 'minor', 'cat': 'color'}] * 20}
    assert ratchet.score_page(serious, [], frozenset(), set())[4] == 'serious'


def test_a_capped_scan_cannot_report_full_coverage():
    rep = ratchet.build_report({'a': {'v': [], 'p': [{'id': 'x', 'impact': 'minor', 'cat': 'color'}]}}, {'a': '<p>x</p>'}, 'x', requested=['a', 'b', 'c'])
    assert rep['coverage'] < 100 and rep['pages_missing'] == ['b', 'c']


def test_a_symlink_that_leaves_the_scanned_folder_is_not_served(tmp_path):
    import threading, urllib.error, urllib.request, http.server, functools
    root = tmp_path / 'site'; root.mkdir()
    (root / 'index.html').write_text('<p>ok</p>')
    secret = tmp_path / 'secret.txt'; secret.write_text('TOP SECRET')
    (root / 'leak.txt').symlink_to(secret)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(ratchet.confined_handler(root.resolve()), directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        assert urllib.request.urlopen(base + '/index.html').read() == b'<p>ok</p>'
        try:
            urllib.request.urlopen(base + '/leak.txt')
            raise AssertionError('the symlinked file was served')
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()


def test_mcp_arguments_are_bounded_and_versions_negotiated():
    sys.path.insert(0, str(HERE / 'scripts'))
    import mcp_server
    for bad in ({'max_pages': 0}, {'max_pages': 1000}, {'max_pages': 'x'}, {'depth': 9}, {'max_pages': True}):
        try:
            mcp_server.bounded(bad, next(iter(bad)), 15, 1, 100 if 'max_pages' in bad else 4)
            raise AssertionError(f'{bad} was accepted')
        except ValueError:
            pass
    assert mcp_server.bounded({}, 'max_pages', 15, 1, 100) == 15
    assert '2099-01-01' not in mcp_server.SUPPORTED_VERSIONS


def test_svg_title_may_follow_other_children_and_an_empty_title_is_not_a_name():
    assert ratchet.static_flags('<svg width="10"><desc>d</desc><title>Chart</title><path/></svg>') == []
    assert ratchet.static_flags('<svg><title></title><path/></svg>') == ['svg_no_name']


def test_the_ci_example_turns_the_sandbox_off_with_a_warning():
    y = (HERE / 'examples' / 'ci' / 'a11y-scan.yml').read_text()
    assert "A11Y_NO_SANDBOX: '1'" in y and 'never copy this line' in y


def test_layers_follow_the_wcag_principle_of_the_success_criterion():
    L = ratchet.layer_of
    assert L({'id': 'td-has-header', 'sc': ['wcag131'], 'cat': 'tables'}) == 'perceivable'      # 1.3.1: was 'robust' under the axe-category grouping
    assert L({'id': 'label', 'sc': ['wcag412'], 'cat': 'forms'}) == 'robust'                      # 4.1.2: was 'understandable'
    assert L({'id': 'document-title', 'sc': ['wcag242'], 'cat': 'text-alternatives'}) == 'operable'
    assert L({'id': 'html-has-lang', 'sc': ['wcag311'], 'cat': 'language'}) == 'understandable'


def test_a_rule_under_two_principles_takes_the_lowest_regardless_of_tag_order():
    assert ratchet.layer_of({'id': 'link-name', 'sc': ['wcag244', 'wcag412']}) == 'operable'
    assert ratchet.layer_of({'id': 'link-name', 'sc': ['wcag412', 'wcag244']}) == 'operable'


def test_a_rule_without_a_criterion_tag_falls_back_and_is_reported():
    ratchet.FALLBACKS.clear()
    assert ratchet.layer_of({'id': 'made-up-rule', 'sc': [], 'cat': 'keyboard'}) == 'operable'
    assert 'made-up-rule' in ratchet.FALLBACKS
    rep = ratchet.build_report({'a': {'v': [{'id': 'made-up-rule', 'impact': 'minor', 'nodes': 1, 'cat': 'keyboard'}], 'p': []}}, {'a': '<p>x</p>'}, 'x')
    assert 'made-up-rule' in rep['layer_fallback_rules']


# ---- round 3: everything the kernel routes to this host is loopback, never "private" ------------------------------------------------------------

def test_the_unspecified_address_is_loopback_in_every_form():
    assert classify('0.0.0.0', '0.1.2.3', '0.255.255.255', '::', '::0.0.0.0', '::ffff:0.0.0.0', '::ffff:0:0', '64:ff9b::0.0.0.0', '2002:0:1::') == ['loopback'] * 9


def test_loopback_lookalikes_are_not_reachable_even_with_allow_private():
    code = """import {vetUrl, declareTargets} from './lib.mjs';
declareTargets({urls: {a: 'http://127.0.0.1:8777/'}});
const out = [];
for (const u of process.argv.slice(1)) { try { await vetUrl(u); out.push('ok'); } catch (e) { out.push('blocked'); } }
console.log(JSON.stringify(out));"""
    urls = ['http://127.0.0.1:8777/', 'http://0.0.0.0:8777/', 'http://0:8777/', 'http://[::]:8777/', 'http://[::1]:8777/', 'http://[::ffff:127.0.0.1]:8777/',
            'http://127.0.0.2:8777/', 'ws://0.0.0.0:8777/', 'http://10.1.2.3/']
    import os
    r = subprocess.run(['node', '--input-type=module', '-e', code, *urls], capture_output=True, text=True, cwd=HERE / 'scripts', timeout=30, env=dict(os.environ, A11Y_ALLOW_PRIVATE='1'))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ['ok'] + ['blocked'] * 7 + ['ok']      # a private LAN address is what A11Y_ALLOW_PRIVATE=1 is for; the rest is this machine


def test_python_guards_agree_that_0_0_0_0_is_this_machine(monkeypatch):
    import mcp_server
    monkeypatch.setenv('A11Y_ALLOW_PRIVATE', '1')
    for host in ('0.0.0.0', '0', '[::]', '127.0.0.2'):
        with pytest.raises(SystemExit):
            ratchet.check_public_host(host.strip('[]'))
        with pytest.raises(ValueError):
            mcp_server.check_target('http://' + host + ':8777/', False)
    ratchet.check_public_host('127.0.0.1')
