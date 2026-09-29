"""Guard: kein Image ohne Testlauf, keine Testdatei ohne Runner.

Ausfuehren: python tests/test_ci_gate.py   (laeuft auch in tests/run_all.py)
Nur stdlib, liest release.yml/CLAUDE.md als Text (kein PyYAML im Image).

Hintergrund (Review W1 S4-011): release.yml baute und pushte bei jedem
main-Push ``:dev`` und bei jedem Tag ``:latest`` ohne einen einzigen Test;
20 Testdateien liefen ueber keinen dokumentierten Runner. Nacharbeit: der
Sammellauf muss auch in einem sauberen Checkout (CI) gruen sein —
``test_trim.py`` braucht die gitignorten ``books/*_firstkey.pgn`` und wird dort
sichtbar uebersprungen (``run_all.NEEDS_BOOKS``), nie still.
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile

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


def _touch(path):
    with open(path, 'w', encoding='utf-8'):
        pass


def test_books_exception():
    """test_trim braucht die gitignorten Buch-PGNs: im sauberen Checkout SKIP statt rot."""
    collected = run_all.collect()
    check('nur test_trim.py ist Buecher-Ausnahme (NEEDS_BOOKS)',
          run_all.NEEDS_BOOKS == frozenset({'test_trim.py'}),
          f'NEEDS_BOOKS={sorted(run_all.NEEDS_BOOKS)}')
    check('Buecher-Ausnahme wird gesammelt und ist kein Netz-Test',
          run_all.NEEDS_BOOKS <= set(collected)
          and not (run_all.NEEDS_BOOKS & run_all.NETWORK_TESTS))
    with open(os.path.join(_TESTS, 'trim_snapshots.json'), encoding='utf-8') as f:
        snap_books = sorted({snap['filename'] for snap in json.load(f)})
    needed = run_all.required_books('test_trim.py')
    check('Skip haengt an genau den Snapshot-PGNs aus trim_snapshots.json',
          len(needed) > 1 and needed == snap_books, f'needed={needed}')
    check('books/*.pgn ist gitignored (Grund der Ausnahme)',
          re.search(r'^books/\*\.pgn\s*$', _read('.gitignore'), re.M) is not None)

    with tempfile.TemporaryDirectory() as empty:
        run, skipped = run_all.plan(books_dir=empty)
        check('sauberer Checkout (keine PGN): nur test_trim uebersprungen, Rest laeuft',
              set(skipped) == {'test_trim.py'}
              and run == [f for f in collected if f != 'test_trim.py'],
              f'skipped={sorted(skipped)}')
        check('Skip-Grund nennt gitignored', 'gitignored' in skipped.get('test_trim.py', ''))
    with tempfile.TemporaryDirectory() as full:
        for b in needed:
            _touch(os.path.join(full, b))
        run, skipped = run_all.plan(books_dir=full)
        check('alle PGNs da: test_trim laeuft', 'test_trim.py' in run and not skipped)
    with tempfile.TemporaryDirectory() as partial:
        _touch(os.path.join(partial, needed[0]))
        run, skipped = run_all.plan(books_dir=partial)
        check('nur einzelne PGNs da: test_trim laeuft (wird rot), kein Skip',
              'test_trim.py' in run and not skipped)
    check('Dateien ohne Buecher-Bedarf werden nie uebersprungen',
          all(run_all.skip_reason(f, os.devnull) is None
              for f in collected if f not in run_all.NEEDS_BOOKS))

    # Ende-zu-Ende ohne Unterprozess: Skip ist sichtbar und macht den Lauf nicht rot.
    orig_collect, orig_books = run_all.collect, run_all.BOOKS_DIR
    buf = io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as empty:
            run_all.collect = lambda: ['test_trim.py']
            run_all.BOOKS_DIR = empty
            with contextlib.redirect_stdout(buf):
                rc = run_all.main([])
    finally:
        run_all.collect, run_all.BOOKS_DIR = orig_collect, orig_books
    out = buf.getvalue()
    check('run_all ohne Buecher: rc 0, SKIP-Zeile und Zusammenfassung zeigen test_trim',
          rc == 0 and 'SKIP test_trim.py (' in out and '1 uebersprungen: test_trim.py' in out,
          f'rc={rc} out={out!r}')


def test_docs_name_runner():
    check('CLAUDE.md nennt python tests/run_all.py',
          'python tests/run_all.py' in _read('CLAUDE.md'))
    for doc in ('CLAUDE.md', 'README.md'):
        text = _read(doc)
        check(f'{doc} sagt, dass test_trim nur lokal laeuft (NEEDS_BOOKS)',
              'NEEDS_BOOKS' in text and 'test_trim.py' in text)


def main():
    for t in (test_release_workflow_gated, test_every_test_file_has_runner, test_collect,
              test_books_exception, test_docs_name_runner):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle CI-Gate-Tests bestanden.')


if __name__ == '__main__':
    main()
