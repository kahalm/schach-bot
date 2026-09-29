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

Laeuft auch in ``.github/workflows/release.yml`` (Job ``test``), bevor ein
Image gebaut und als ``:dev``/``:latest`` gepusht wird.
"""

import os
import subprocess
import sys
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)

# Brauchen echtes Lichess-Netz (+ LICHESS_TOKEN) → nicht im Sammellauf.
NETWORK_TESTS = frozenset({'test_puzzle.py', 'test_upload.py', 'test_study_create.py'})

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


def main(argv=None):
    verbose = '-v' in (argv if argv is not None else sys.argv[1:])
    files = collect()
    failed = []
    for name in files:
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
    print(f'---\n{len(files) - len(failed)}/{len(files)} Testdateien gruen.')
    if failed:
        print('FAILED: ' + ', '.join(failed))
        return 1
    print('Alle Tests OK.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
