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
import shutil
import subprocess
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
          re.search(r'^    needs:\s*(test|\[[^\]]*\btest\b[^\]]*\])\s*$', build, re.M) is not None)
    check('nur build-and-push pusht Images', all(
        'push: true' not in body for name, body in jobs.items() if name != 'build-and-push'))


def _push_tag_patterns(workflow_text):
    """Eintraege unter ``on: push: tags:`` (Liste mit ``- 'muster'``)."""
    m = re.search(r'^on:\s*\n(.*?)^\S', workflow_text, re.M | re.S)
    block = m.group(1) if m else ''
    t = re.search(r'^    tags:\s*\n((?:\s*(?:#.*|- .*)\n)+)', block, re.M)
    return re.findall(r"^\s*- '?([^'\n]+?)'?\s*$", t.group(1), re.M) if t else []


def _step_run_script(job_text, step_id):
    """``run: |``-Block des Schritts mit ``id: <step_id>`` (ausgerueckt) oder ''."""
    lines = job_text.splitlines()
    for i, line in enumerate(lines):
        if re.match(rf'^\s+id:\s*{re.escape(step_id)}\s*$', line):
            for j in range(i + 1, len(lines)):
                m = re.match(r'^(\s+)run:\s*\|\s*$', lines[j])
                if not m:
                    continue
                indent, body = len(m.group(1)), []
                for k in range(j + 1, len(lines)):
                    if lines[k].strip() and len(lines[k]) - len(lines[k].lstrip()) <= indent:
                        break
                    body.append(lines[k])
                pad = min(len(b) - len(b.lstrip()) for b in body if b.strip())
                return '\n'.join(b[pad:] for b in body) + '\n'
    return ''


_GIT_ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
                GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid')


def _git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, env=_GIT_ENV, capture_output=True,
                          text=True, check=True).stdout.strip()


def test_release_tags_guarded():
    """Review W2 I1-004: nur vX.Y.Z-Tags auf main werden :latest (Watchtower rollt es nachts aus)."""
    text = _read('.github', 'workflows', 'release.yml')
    jobs = _jobs(text)
    check('Tag-Trigger nur vX.Y.Z (kein v*)', _push_tag_patterns(text) == ['v[0-9]+.[0-9]+.[0-9]+'],
          f'{_push_tag_patterns(text)}')
    build = jobs.get('build-and-push', '')
    check('build-and-push wartet auf release-guard',
          re.search(r'^    needs:\s*\[[^\]]*\brelease-guard\b[^\]]*\]\s*$', build, re.M) is not None)
    latest = [l for l in build.splitlines() if 'value=latest' in l]
    check(':latest nur mit Freigabe von release-guard',
          len(latest) == 1 and "needs.release-guard.outputs.latest == 'true'" in latest[0]
          and 'startsWith' not in latest[0], f'{latest}')
    guard = jobs.get('release-guard', '')
    check('release-guard holt die volle Historie (fetch-depth: 0)', 'fetch-depth: 0' in guard)
    script = _step_run_script(guard, 'tag-check')
    check('release-guard hat den Schritt tag-check', bool(script))
    if not script:
        return
    if not (shutil.which('git') and shutil.which('bash')):
        check('git und bash fuer den Verhaltenstest vorhanden', False)
        return

    # Verhalten: Skript echt ausfuehren gegen ein Wegwerf-Repo mit origin/main und Feature-Branch.
    with tempfile.TemporaryDirectory() as tmp:
        origin, work = os.path.join(tmp, 'origin.git'), os.path.join(tmp, 'work')
        _git(tmp, 'init', '-q', '--bare', '-b', 'main', origin)
        _git(tmp, 'init', '-q', '-b', 'main', work)
        _git(work, 'remote', 'add', 'origin', origin)
        _git(work, 'commit', '-q', '--allow-empty', '-m', 'A')
        old_main = _git(work, 'rev-parse', 'HEAD')
        _git(work, 'commit', '-q', '--allow-empty', '-m', 'C')
        _git(work, 'push', '-q', 'origin', 'main')
        _git(work, 'checkout', '-q', '-b', 'feature')
        _git(work, 'commit', '-q', '--allow-empty', '-m', 'B (nicht gemergt)')
        feature = _git(work, 'rev-parse', 'HEAD')
        _git(work, 'update-ref', '-d', 'refs/remotes/origin/main')  # das Skript muss selbst holen
        script_path = os.path.join(tmp, 'tag-check.sh')
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script)

        def run(ref, sha):
            out = os.path.join(tmp, 'github_output')
            open(out, 'w').close()
            env = dict(_GIT_ENV, GITHUB_REF=ref, GITHUB_REF_NAME=ref.rsplit('/', 1)[-1],
                       GITHUB_SHA=sha, GITHUB_OUTPUT=out)
            rc = subprocess.run(['bash', '--noprofile', '--norc', '-eo', 'pipefail', script_path],
                                cwd=work, env=env, capture_output=True, text=True).returncode
            with open(out, encoding='utf-8') as f:
                return rc, f.read()

        rc, out = run('refs/heads/main', old_main)
        check('main-Push: laeuft, kein :latest', rc == 0 and 'latest=false' in out, f'rc={rc} {out!r}')
        rc, out = run('refs/tags/v2.99.0', old_main)
        check('vX.Y.Z auf (aelterem) main-Commit: :latest frei', rc == 0 and 'latest=true' in out,
              f'rc={rc} {out!r}')
        for ref, sha, why in (('refs/tags/v2.99.0', feature, 'vX.Y.Z auf ungemergtem Branch'),
                              ('refs/tags/vorher-umbau', old_main, 'Sicherungs-Tag vorher-umbau'),
                              ('refs/tags/v-test', old_main, 'Tag v-test'),
                              ('refs/tags/v2.99.0-rc1', old_main, 'Tag mit Suffix'),
                              ('refs/tags/v2.99', old_main, 'Tag ohne Patch-Stelle')):
            rc, out = run(ref, sha)
            check(f'{why}: abgebrochen, kein :latest', rc != 0 and 'latest=true' not in out,
                  f'rc={rc} {out!r}')


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
    for t in (test_release_workflow_gated, test_release_tags_guarded, test_every_test_file_has_runner,
              test_collect, test_books_exception, test_docs_name_runner):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle CI-Gate-Tests bestanden.')


if __name__ == '__main__':
    main()
