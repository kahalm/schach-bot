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


def test_all_solved_hides_try_count():
    # Bug: wenn attempts == total, sah "Gelöst (1): @X · 🧩 1 dran versucht" aus als
    # wäre eine zweite Person gescheitert. Fix: "dran versucht" nur bei attempts > total.
    res = {'solvedCount': 1, 'attemptCount': 1, 'solvers': [{'name': 'Patrik', 'discordId': '42'}]}
    line = dr.format_solver_line(res)
    check('alle gelöst → kein "dran versucht"', 'dran versucht' not in line)
    check('alle gelöst → Gelöst (1) steht drin', 'Gelöst (1)' in line)

    # Wenn mehr versucht als gelöst → Zahl soll weiter erscheinen
    res2 = {'solvedCount': 1, 'attemptCount': 3, 'solvers': [{'name': 'Patrik', 'discordId': '42'}]}
    line2 = dr.format_solver_line(res2)
    check('nicht alle gelöst → "dran versucht" zeigen', 'dran versucht' in line2)


def test_fmt_time():
    check('0 s → leer', dr._fmt_time(0) == '')
    check('45 s → "45s"', dr._fmt_time(45) == '45s')
    check('60 s → "1:00"', dr._fmt_time(60) == '1:00')
    check('83 s → "1:23"', dr._fmt_time(83) == '1:23')
    check('3661 s → "61:01"', dr._fmt_time(3661) == '61:01')


def test_time_display():
    res = {'solvedCount': 2, 'attemptCount': 2, 'solvers': [
        {'name': 'Anna', 'discordId': '111', 'timeSeconds': 45},
        {'name': 'Ben', 'discordId': None, 'timeSeconds': 83},
    ]}
    line = dr.format_solver_line(res)
    check('Zeit in Sekunden → "45s"', '(45s)' in line)
    check('Zeit in Minuten → "1:23"', '(1:23)' in line)
    check('@mention mit Zeit', '<@111> (45s)' in line)


def test_time_zero_hidden():
    res = {'solvedCount': 1, 'attemptCount': 1, 'solvers': [
        {'name': 'Anna', 'discordId': '111', 'timeSeconds': 0},
    ]}
    line = dr.format_solver_line(res)
    check('timeSeconds=0 → keine Klammern', '()' not in line)
    check('name/mention weiterhin vorhanden', '<@111>' in line)


def test_hints_badge():
    res = {'solvedCount': 2, 'attemptCount': 2, 'solvers': [
        {'name': 'Anna', 'discordId': '111', 'timeSeconds': 45, 'hintsUsed': 2},
        {'name': 'Ben', 'discordId': None, 'timeSeconds': 30, 'hintsUsed': 0},
    ]}
    line = dr.format_solver_line(res)
    check('mit Tipps → 💡 hinter dem Namen', '<@111> (45s) (💡)' in line)
    check('ohne Tipps → keine 💡', 'Ben (30s)' in line and 'Ben (30s) (💡)' not in line)


def test_hints_badge_without_time():
    res = {'solvedCount': 1, 'attemptCount': 1, 'solvers': [
        {'name': 'Anna', 'discordId': '111', 'timeSeconds': 0, 'hintsUsed': 1},
    ]}
    line = dr.format_solver_line(res)
    check('mit Tipps, ohne Zeit → "<@111> (💡)"', '<@111> (💡)' in line)


def test_remember_current_roundtrip():
    dr.DAILY_FILE = f'/tmp/test_daily_post_{os.getpid()}.json'
    if os.path.exists(dr.DAILY_FILE):
        os.remove(dr.DAILY_FILE)
    dr.remember(123, 456, 789)
    cur = dr.current()
    check('current() liefert gespeicherten Post',
          cur is not None and cur['channel_id'] == 123 and cur['message_id'] == 456 and cur['puzzle_id'] == 789)

    # current() prüft KEIN Datum mehr (intentional: vermeidet eingefrorenes Embed
    # zwischen UTC-Mitternacht und dem nächsten /daily-Lauf).
    from core.json_store import atomic_write
    stale = dict(cur); stale['date'] = '2000-01-01'
    atomic_write(dr.DAILY_FILE, stale)
    check('altes Datum → current() gibt trotzdem Daten zurück', dr.current() is not None)

    os.remove(dr.DAILY_FILE)


def test_remember_midnight_rollover():
    """UTC-Datumswechsel zwischen Haupt-Post und Spiegel-Post desselben Puzzles
    darf die posts-Liste und 'since' NICHT resetten (sonst verwaist das erste
    Channel-Embed und bekommt nie wieder Solver-Updates)."""
    dr.DAILY_FILE = f'/tmp/test_daily_post_mn_{os.getpid()}.json'
    if os.path.exists(dr.DAILY_FILE):
        os.remove(dr.DAILY_FILE)
    orig_today = dr._today
    try:
        # Haupt-Post um 23:59 am Tag 1
        dr._today = lambda: '2026-07-11'
        dr.remember(111, 1001, 789)
        since1 = dr.current()['since']

        # Spiegel-Post um 00:00 am Tag 2 — GLEICHES Puzzle
        dr._today = lambda: '2026-07-12'
        dr.remember(222, 2002, 789)

        cur = dr.current()
        cids = [p['channel_id'] for p in cur['posts']]
        check('Rollover: beide Posts gemerkt', cids == [111, 222])
        check('Rollover: since bleibt vom ersten Post', cur['since'] == since1)
        check('Rollover: Primaer-Post bleibt Channel 1', cur['channel_id'] == 111)

        # Neues Puzzle (andere ID) → Reset wie gehabt
        dr.remember(111, 3003, 999)
        cur = dr.current()
        check('neues Puzzle → posts-Reset', len(cur['posts']) == 1)
        check('neues Puzzle → neue puzzle_id', cur['puzzle_id'] == 999)
        check('neues Puzzle → since neu', cur['since'] != since1)
    finally:
        dr._today = orig_today
        if os.path.exists(dr.DAILY_FILE):
            os.remove(dr.DAILY_FILE)


def main():
    for t in (test_no_solvers, test_mentions_and_names, test_truncates_long_list,
              test_anonymous_counted, test_only_anonymous, test_all_solved_hides_try_count,
              test_fmt_time, test_time_display, test_time_zero_hidden,
              test_hints_badge, test_hints_badge_without_time,
              test_remember_current_roundtrip, test_remember_midnight_rollover):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle daily_results-Tests bestanden.')


if __name__ == '__main__':
    main()
