"""Sammel-Runner fuer ALLE Offline-Tests des Bots — der einzige Testbefehl.

Ausfuehren: python tests/run_all.py          (-v: Ausgabe jeder Datei zeigen)

Fuehrt jede ``tests/test_*.py`` mit eigenem ``if __name__ == '__main__'`` in
einem EIGENEN Prozess aus (die Dateien stubben ``sys.modules`` unterschiedlich:
``test_helpers`` stubbt discord/svglib/reportlab weg, ``test_rendering`` braucht
die echten Libs) und schlaegt fehl, sobald eine davon mit Exit-Code != 0 endet.
Neue Testdateien mit ``__main__`` laufen automatisch mit.

Nicht dabei:
- ``test_cmd_*.py`` / ``test_helpers.py`` haben kein ``__main__``; sie laufen
  ueber ``test_commands.py`` (``test_ci_gate.py`` prueft, dass jedes
  ``test_cmd_*``-Modul dort importiert wird).
- ``NETWORK_TESTS``: sprechen die echte Lichess-API an bzw. legen echte
  Studien an (Token noetig) — nur manuell starten.

Nur lokal:
- ``NEEDS_BOOKS`` (``test_trim.py``): liest die Snapshot-PGNs
  ``books/*_firstkey.pgn``. ``books/*.pgn`` ist gitignored, die Dateien fehlen
  also in jedem sauberen Checkout (auch im CI). Fehlt KEINE davon, laeuft die
  Datei; fehlen ALLE, wird sie sichtbar als ``SKIP`` gemeldet (zaehlt nicht als
  Fehler, steht aber in der Zusammenfassung); fehlen nur EINZELNE, laeuft sie
  trotzdem und wird rot.

Laeuft auch in ``.github/workflows/release.yml`` (Job ``test``), bevor ein
Image gebaut und als ``:dev``/``:latest`` gepusht wird — dort ohne
``test_trim.py`` (Buecher fehlen).
"""

import json
import os
import subprocess
import sys
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)

# Brauchen echtes Lichess-Netz (+ LICHESS_TOKEN) → nicht im Sammellauf.
NETWORK_TESTS = frozenset({'test_puzzle.py', 'test_upload.py', 'test_study_create.py'})

BOOKS_DIR = os.path.join(REPO_ROOT, 'books')
TRIM_SNAPSHOTS = os.path.join(TESTS_DIR, 'trim_snapshots.json')


def _trim_snapshot_books():
    with open(TRIM_SNAPSHOTS, encoding='utf-8') as f:
        return sorted({snap['filename'] for snap in json.load(f)})


# Brauchen die lokalen Buch-PGNs (books/*.pgn gitignored) → {Datei: PGN-Liste}.
_BOOK_LISTS = {'test_trim.py': _trim_snapshot_books}
NEEDS_BOOKS = frozenset(_BOOK_LISTS)

TIMEOUT_S = 600


def _has_main(path):
    with open(path, encoding='utf-8') as f:
        src = f.read()
    return "__name__ == '__main__'" in src or '__name__ == "__main__"' in src


def collect():
    """Alle eigenstaendig lauffaehigen Offline-Testdateien (Dateinamen, sortiert)."""
    return [
        name for name in sorted(os.listdir(TESTS_DIR))
        if name.startswith('test_') and name.endswith('.py')
        and name not in NETWORK_TESTS
        and _has_main(os.path.join(TESTS_DIR, name))
    ]


def required_books(name):
    """PGN-Dateinamen unter books/, die eine NEEDS_BOOKS-Datei liest (sonst [])."""
    lister = _BOOK_LISTS.get(name)
    return lister() if lister else []


def skip_reason(name, books_dir=None):
    """Grund fuers Ueberspringen oder None.

    Nur fuer NEEDS_BOOKS und nur, wenn KEINE der benoetigten PGNs in
    ``books_dir`` liegt (sauberer Checkout/CI). Fehlen nur einzelne, laeuft die
    Datei und wird rot — ein halber Buecher-Ordner soll nicht still gruen sein.
    """
    needed = required_books(name)
    if not needed:
        return None
    books_dir = books_dir or BOOKS_DIR
    if any(os.path.isfile(os.path.join(books_dir, b)) for b in needed):
        return None
    return (f'keine der {len(needed)} Snapshot-PGNs books/*_firstkey.pgn da - '
            'gitignored, fehlen in jedem sauberen Checkout/CI; laeuft nur lokal mit den Buechern')


def plan(books_dir=None):
    """(zu startende Dateien, {uebersprungene Datei: Grund})."""
    run, skipped = [], {}
    for name in collect():
        reason = skip_reason(name, books_dir)
        if reason:
            skipped[name] = reason
        else:
            run.append(name)
    return run, skipped


def main(argv=None):
    verbose = '-v' in (argv if argv is not None else sys.argv[1:])
    files, skipped = plan()
    failed = []
    for name in sorted(set(files) | set(skipped)):
        if name in skipped:
            print(f'SKIP {name} ({skipped[name]})')
            continue
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                [sys.executable, os.path.join('tests', name)], cwd=REPO_ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                timeout=TIMEOUT_S)
            rc, out = proc.returncode, proc.stdout
        except subprocess.TimeoutExpired as e:
            rc = 'timeout'
            out = e.stdout.decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        dt = time.monotonic() - t0
        ok = rc == 0
        if not ok:
            failed.append(name)
        if verbose or not ok:
            print(out.rstrip())
        print(f"{'OK  ' if ok else 'FAIL'} {name} ({dt:.1f}s{'' if ok else f', rc={rc}'})")
    skip_note = f', {len(skipped)} uebersprungen: {", ".join(skipped)}' if skipped else ''
    print(f'---\n{len(files) - len(failed)}/{len(files)} Testdateien gruen{skip_note}.')
    if failed:
        print('FAILED: ' + ', '.join(failed))
        return 1
    print('Alle gestarteten Tests OK.' if skipped else 'Alle Tests OK.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
