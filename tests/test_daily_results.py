"""Standalone-Tests für puzzle/daily_results.py (Tagespuzzle-Visualisierung).

Ausführen: python tests/test_daily_results.py
Lädt das Modul direkt per Pfad (umgeht puzzle/__init__.py / discord), da die
Formatierungslogik bewusst ohne schwere Importe auskommt.
"""

import importlib.util
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

_spec = importlib.util.spec_from_file_location(
    'daily_results_standalone', os.path.join(_REPO, 'puzzle', 'daily_results.py'))
dr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dr)

_failures = []


def check(name, cond):
    print(('  OK   ' if cond else '  FAIL ') + name)
    if not cond:
        _failures.append(name)


def test_no_solvers():
    line = dr.format_solver_line({'solvedCount': 0, 'attemptCount': 5, 'solvers': []})
    check('0 Solver → "Noch niemand"', 'Noch niemand' in line)
    check('0 Solver → Versuchs-Zahl', '5 dran versucht' in line)


def test_mentions_and_names():
    res = {'solvedCount': 3, 'attemptCount': 8, 'solvers': [
        {'name': 'Anna', 'discordId': '111'},
        {'name': 'Ben', 'discordId': None},
        {'name': 'Carl'},
    ]}
    line = dr.format_solver_line(res)
    check('verknüpft → @mention', '<@111>' in line)
    check('unverknüpft → Name (Ben)', 'Ben' in line and '<@' not in line.split('Ben')[0].split(',')[-1])
    check('unverknüpft → Name (Carl)', 'Carl' in line)
    check('Solved-Count', 'Gelöst (3)' in line)
    check('Versuchs-Zahl', '8 dran versucht' in line)


def test_truncates_long_list():
    solvers = [{'name': f'U{i}', 'discordId': str(i)} for i in range(20)]
    line = dr.format_solver_line({'solvedCount': 20, 'attemptCount': 25, 'solvers': solvers}, max_names=15)
    check('zeigt "+5 weitere"', '+5 weitere' in line)


def test_anonymous_counted():
    # 1 eingeloggt + 2 anonym → Gesamt 3, anonyme als "+2 anonym"
    res = {'solvedCount': 1, 'anonymousSolvedCount': 2, 'attemptCount': 4,
           'solvers': [{'name': 'Anna', 'discordId': '111'}]}
    line = dr.format_solver_line(res)
    check('Gesamt inkl. anonym → (3)', 'Gelöst (3)' in line)
    check('eingeloggter @mention', '<@111>' in line)
    check('anonyme als Anzahl', '2 anonym' in line)


def test_only_anonymous():
    res = {'solvedCount': 0, 'anonymousSolvedCount': 3, 'attemptCount': 3, 'solvers': []}
    line = dr.format_solver_line(res)
    check('nur anonym → Gelöst (3)', 'Gelöst (3)' in line)
    check('nur anonym → "3 anonym"', '3 anonym' in line)
    check('nicht "Noch niemand"', 'Noch niemand' not in line)


def test_remember_current_roundtrip():
    dr.DAILY_FILE = f'/tmp/test_daily_post_{os.getpid()}.json'
    if os.path.exists(dr.DAILY_FILE):
        os.remove(dr.DAILY_FILE)
    dr.remember(123, 456, 789)
    cur = dr.current()
    check('current() liefert heutigen Post',
          cur is not None and cur['channel_id'] == 123 and cur['message_id'] == 456 and cur['puzzle_id'] == 789)

    from core.json_store import atomic_write
    stale = dict(cur); stale['date'] = '2000-01-01'
    atomic_write(dr.DAILY_FILE, stale)
    check('altes Datum → current() = None', dr.current() is None)
    os.remove(dr.DAILY_FILE)


def main():
    for t in (test_no_solvers, test_mentions_and_names, test_truncates_long_list,
              test_anonymous_counted, test_only_anonymous, test_remember_current_roundtrip):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle daily_results-Tests bestanden.')


if __name__ == '__main__':
    main()
