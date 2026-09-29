"""Guard: kein Image ohne Testlauf, keine Testdatei ohne Runner.

Ausfuehren: python tests/test_ci_gate.py   (laeuft auch in tests/run_all.py)
Nur stdlib, liest release.yml/CLAUDE.md als Text (kein PyYAML im Image).

Hintergrund (Review W1 S4-011): release.yml baute und pushte bei jedem
main-Push ``:dev`` und bei jedem Tag ``:latest`` ohne einen einzigen Test;
20 Testdateien liefen ueber keinen dokumentierten Runner.
"""

import os
import re
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_TESTS)
sys.path.insert(0, _TESTS)

import run_all  # noqa: E402

_failures = []


def check(name, cond, detail=''):
    print(('  OK   ' if cond else '  FAIL ') + name + (f'  [{detail}]' if detail and not cond else ''))
    if not cond:
        _failures.append(name)


def _read(*parts):
    with open(os.path.join(_REPO, *parts), encoding='utf-8') as f:
        return f.read()


def _jobs(workflow_text):
    """{job_name: block_text} der Jobs unter ``jobs:`` (Einrueckung 2)."""
    jobs, cur, in_jobs = {}, None, False
    for line in workflow_text.splitlines():
        if re.match(r'^jobs:\s*$', line):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line and not line.startswith(' ') and not line.startswith('#'):
            break  # naechster Top-Level-Schluessel
        m = re.match(r'^  ([A-Za-z0-9_-]+):\s*$', line)
        if m:
            cur = m.group(1)
            jobs[cur] = ''
        elif cur:
            jobs[cur] += line + '\n'
    return jobs


def test_release_workflow_gated():
    jobs = _jobs(_read('.github', 'workflows', 'release.yml'))
    check('release.yml hat Job "test"', 'test' in jobs, f'jobs={sorted(jobs)}')
    check('Job "test" startet den Sammel-Runner',
          'python tests/run_all.py' in jobs.get('test', ''))
    build = jobs.get('build-and-push', '')
    check('build-and-push existiert', bool(build))
    check('build-and-push wartet auf "test" (needs)',
          re.search(r'^    needs:\s*(test|\[\s*test\s*\])\s*$', build, re.M) is not None)
    check('nur build-and-push pusht Images', all(
        'push: true' not in body for name, body in jobs.items() if name != 'build-and-push'))


def test_every_test_file_has_runner():
    collected = set(run_all.collect())
    runner_src = _read('tests', 'test_commands.py')
    imported = set(re.findall(r'^from (test_cmd_\w+) import', runner_src, re.M)) \
        | set(re.findall(r'^import (test_cmd_\w+)', runner_src, re.M))
    orphans = []
    for name in sorted(os.listdir(_TESTS)):
        if not (name.startswith('test_') and name.endswith('.py')):
            continue
        mod = name[:-3]
        if name in collected or name in run_all.NETWORK_TESTS or mod == 'test_helpers':
            continue
        if mod.startswith('test_cmd_') and mod in imported:
            continue
        orphans.append(name)
    check('jede tests/test_*.py laeuft ueber run_all oder test_commands', not orphans,
          f'ohne Runner: {orphans}')


def test_collect():
    files = run_all.collect()
    check('Netz-Tests nicht im Sammellauf', not (set(files) & run_all.NETWORK_TESTS))
    must = ('test_commands.py', 'test_trim.py', 'test_rendering.py', 'test_discord_link.py',
            'test_webhook_build_info.py', 'test_json_store.py', 'test_state.py',
            'test_selection.py', 'test_rookhub.py', 'test_ci_gate.py')
    missing = [m for m in must if m not in files]
    check('Kern-Testdateien im Sammellauf', not missing, f'fehlen: {missing}')
    check('keine test_cmd_* (laufen ueber test_commands)',
          not [f for f in files if f.startswith('test_cmd_')])


def test_docs_name_runner():
    check('CLAUDE.md nennt python tests/run_all.py',
          'python tests/run_all.py' in _read('CLAUDE.md'))


def main():
    for t in (test_release_workflow_gated, test_every_test_file_has_runner, test_collect,
              test_docs_name_runner):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle CI-Gate-Tests bestanden.')


if __name__ == '__main__':
    main()
