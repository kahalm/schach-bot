"""Tests für core/reinforcement.py — State-Tracking und Empfänger-Ermittlung.

Ausführen: python tests/test_reinforcement.py
"""

import os
import sys
import tempfile
import shutil

# Pfad-Setup
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

# Schwere Deps stubbben
import unittest.mock as _mock
for _mod in ('discord', 'discord.ext', 'discord.ext.tasks', 'discord.ext.commands',
             'discord.app_commands', 'requests', 'dotenv', 'anthropic',
             'PIL', 'PIL.Image', 'chess', 'chess.pgn'):
    sys.modules.setdefault(_mod, _mock.MagicMock())

import core.reinforcement as rf

_failures = []


def check(name, cond):
    print(('  OK   ' if cond else '  FAIL ') + name)
    if not cond:
        _failures.append(name)


def _tmp_file():
    """Gibt einen temporären Pfad zurück (leer, wird von reinforcement als State-File genutzt)."""
    fd, path = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    os.remove(path)  # noch nicht existieren → reinforce erzeugt es beim ersten Write
    return path


def test_not_yet_notified():
    print('[not_yet_notified — frischer State]')
    rf.REINFORCE_FILE = _tmp_file()
    try:
        check('puzzle frisch → noch nicht benachrichtigt',
              not rf._already_notified('puzzle', '42', '111'))
        check('weekly frisch → noch nicht benachrichtigt',
              not rf._already_notified('weekly', '7', '222'))
        check('goals frisch → noch nicht benachrichtigt',
              rf.goals_not_yet_notified_today('333'))
    finally:
        if os.path.exists(rf.REINFORCE_FILE):
            os.remove(rf.REINFORCE_FILE)


def test_mark_and_check():
    print('[mark_notified → already_notified]')
    rf.REINFORCE_FILE = _tmp_file()
    try:
        rf._mark_notified('puzzle', '42', '111')
        check('nach Mark → already_notified=True', rf._already_notified('puzzle', '42', '111'))
        check('anderer User → noch nicht benachrichtigt',
              not rf._already_notified('puzzle', '42', '999'))
        check('anderes Puzzle → noch nicht benachrichtigt',
              not rf._already_notified('puzzle', '99', '111'))

        rf._mark_notified('goals', '2026-06-07', '555')
        check('goals nach Mark → goals_not_yet_notified_today=False für 555',
              rf._already_notified('goals', '2026-06-07', '555'))
        check('goals für anderen User → noch nicht markiert',
              not rf._already_notified('goals', '2026-06-07', '666'))
    finally:
        if os.path.exists(rf.REINFORCE_FILE):
            os.remove(rf.REINFORCE_FILE)


def test_idempotent_mark():
    print('[idempotent: doppeltes Mark → kein Duplikat in Liste]')
    rf.REINFORCE_FILE = _tmp_file()
    try:
        rf._mark_notified('weekly', '3', '111')
        rf._mark_notified('weekly', '3', '111')
        from core.json_store import atomic_read
        data = atomic_read(rf.REINFORCE_FILE, default=rf._default)
        ids = data['weekly']['3']
        check('nur einmal in Liste', ids.count('111') == 1)
    finally:
        if os.path.exists(rf.REINFORCE_FILE):
            os.remove(rf.REINFORCE_FILE)


def test_new_puzzle_solvers():
    print('[new_puzzle_solvers — nur Motivation-Subs]')
    rf.REINFORCE_FILE = _tmp_file()
    orig_subs = rf._motivation_subscriber_ids
    rf._motivation_subscriber_ids = lambda: {'111', '222'}  # Anna + Ben sind Subs
    try:
        solvers = [
            {'discordId': '111', 'name': 'Anna', 'timeSeconds': 45},
            {'discordId': '222', 'name': 'Ben', 'timeSeconds': 90},
            {'discordId': '999', 'name': 'Nicht-Sub', 'timeSeconds': 10},
            {'name': 'Anon'},  # kein discordId
        ]
        new = rf.new_puzzle_solvers(42, solvers)
        check('nur Subs (Anna+Ben)', len(new) == 2)
        check('Nicht-Sub nicht dabei', all(s['discordId'] != '999' for s in new))
        check('Anon nicht dabei', all(s.get('discordId') for s in new))

        rf._mark_notified('puzzle', '42', '111')
        new2 = rf.new_puzzle_solvers(42, solvers)
        check('nach Mark für Anna: nur Ben', len(new2) == 1 and new2[0]['discordId'] == '222')
    finally:
        rf._motivation_subscriber_ids = orig_subs
        if os.path.exists(rf.REINFORCE_FILE):
            os.remove(rf.REINFORCE_FILE)


def test_new_weekly_completions():
    print('[new_weekly_completions — nur Motivation-Subs]')
    rf.REINFORCE_FILE = _tmp_file()
    orig_subs = rf._motivation_subscriber_ids
    rf._motivation_subscriber_ids = lambda: {'111', '333'}  # Anna + Carl sind Subs
    try:
        players = [
            {'discordId': '111', 'name': 'Anna', 'completed': True},
            {'discordId': '222', 'name': 'Ben-Nicht-Sub', 'completed': True},  # kein Sub
            {'discordId': '333', 'name': 'Carl', 'completed': True},
            {'discordId': '444', 'name': 'Dave', 'completed': False},   # noch nicht fertig
            {'name': 'Anon', 'completed': True},  # kein discordId
        ]
        new = rf.new_weekly_completions(7, players)
        check('nur Subs mit completed=True (Anna+Carl)', len(new) == 2)
        check('Ben-Nicht-Sub nicht dabei', all(p['discordId'] != '222' for p in new))
        check('Dave (nicht fertig) nicht dabei', all(p['discordId'] != '444' for p in new))
        check('Anon nicht dabei', all(p.get('discordId') for p in new))

        rf._mark_notified('weekly', '7', '333')
        new2 = rf.new_weekly_completions(7, players)
        check('nach Mark für Carl: nur Anna', len(new2) == 1 and new2[0]['discordId'] == '111')
    finally:
        rf._motivation_subscriber_ids = orig_subs
        if os.path.exists(rf.REINFORCE_FILE):
            os.remove(rf.REINFORCE_FILE)


def test_fmt_time():
    print('[_fmt_time]')
    check('0 → leer', rf._fmt_time(0) == '')
    check('45 s → "45s"', rf._fmt_time(45) == '45s')
    check('90 s → "1:30 min"', rf._fmt_time(90) == '1:30 min')
    check('60 s → "1:00 min"', rf._fmt_time(60) == '1:00 min')


def test_spawn_dm_throttle_and_gc():
    """spawn_dm haelt Task-Referenzen (GC-Schutz) + drosselt parallele DMs via Semaphore."""
    print('[spawn_dm]')
    import asyncio

    async def run():
        rf._dm_semaphore = asyncio.Semaphore(2)
        rf._MAX_CONCURRENT_DMS = 2
        rf._pending_tasks.clear()

        peak = {'concurrent': 0, 'max': 0}

        async def fake_dm():
            peak['concurrent'] += 1
            peak['max'] = max(peak['max'], peak['concurrent'])
            await asyncio.sleep(0.02)
            peak['concurrent'] -= 1

        tasks = [rf.spawn_dm(fake_dm()) for _ in range(6)]
        check('Tasks werden gehalten (GC-Schutz)', len(rf._pending_tasks) == 6)
        await asyncio.gather(*tasks)
        check('Tasks nach Abschluss freigegeben', len(rf._pending_tasks) == 0)
        check('max. 2 DMs gleichzeitig (Semaphore)', peak['max'] <= 2)

    asyncio.run(run())


def main():
    for t in (test_not_yet_notified, test_mark_and_check, test_idempotent_mark,
              test_new_puzzle_solvers, test_new_weekly_completions, test_fmt_time,
              test_spawn_dm_throttle_and_gc):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle reinforcement-Tests bestanden.')


if __name__ == '__main__':
    main()
