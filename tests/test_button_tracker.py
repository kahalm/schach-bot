"""
Unit-Tests fuer core/button_tracker.py (ClickTracker).

Standalone-Script. Kein Discord-Mocking noetig.

Ausfuehren: python tests/test_button_tracker.py
"""

import sys
import os

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

from core.button_tracker import ClickTracker

PASS = 'OK  '
FAIL = 'FAIL'
total = 0
failed = 0


def check(label, ok, detail=''):
    global total, failed
    total += 1
    if ok:
        print(f'  {PASS} {label}')
    else:
        failed += 1
        msg = f'  {FAIL} {label}'
        if detail:
            msg += f'  ({detail})'
        print(msg)


def test_toggle():
    t = ClickTracker(mutex_pairs={})
    delta, removed = t.apply_click(1, '👍', 100)
    check('erster Klick +1', delta == 1 and removed is None)
    check('count == 1', t.count(1, '👍') == 1)
    delta, removed = t.apply_click(1, '👍', 100)
    check('zweiter Klick (gleicher User) -1', delta == -1)
    check('count == 0 nach Toggle', t.count(1, '👍') == 0)


def test_mutex_pair():
    t = ClickTracker(mutex_pairs={'👍': '👎', '👎': '👍'})
    t.apply_click(5, '👎', 100)
    delta, removed = t.apply_click(5, '👍', 100)
    check('Gegenstimme entfernt Partner', delta == 1 and removed == '👎')
    check('Partner-count == 0', t.count(5, '👎') == 0)
    check('eigener count == 1', t.count(5, '👍') == 1)


def test_independent_users():
    t = ClickTracker(mutex_pairs={})
    t.apply_click(1, '🧩', 100)
    t.apply_click(1, '🧩', 200)
    check('zwei verschiedene User -> count 2', t.count(1, '🧩') == 2)


def test_lru_eviction():
    t = ClickTracker(mutex_pairs={}, cap=2)
    t.apply_click(1, 'a', 1)
    t.apply_click(2, 'a', 1)
    t.apply_click(3, 'a', 1)   # draengt msg_id 1 raus
    check('aeltester evicted', t.count(1, 'a') == 0)
    check('neuere bleiben', t.count(2, 'a') == 1 and t.count(3, 'a') == 1)


def test_get_emoji_users_and_clear():
    t = ClickTracker(mutex_pairs={})
    t.apply_click(9, '✅', 100)
    check('get_emoji_users liefert Mapping', t.get_emoji_users(9).get('✅') == {100})
    check('leeres Mapping fuer unbekannte msg', t.get_emoji_users(999) == {})
    t.clear()
    check('clear leert alles', t.count(9, '✅') == 0)


if __name__ == '__main__':
    print('=== test_button_tracker.py ===\n')
    test_toggle()
    test_mutex_pair()
    test_independent_users()
    test_lru_eviction()
    test_get_emoji_users_and_clear()
    print(f'\n--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
