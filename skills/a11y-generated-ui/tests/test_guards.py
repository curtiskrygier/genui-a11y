"""Pure checks (no browser): the address classifier behind the network guard, and the coverage fields of the report."""
import json, subprocess, sys
from pathlib import Path

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
