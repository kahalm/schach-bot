"""
Unit-Tests fuer puzzle/buttons.py.

Standalone-Script. Discord wird vor dem Import gemockt.

Ausfuehren: python tests/test_buttons.py
"""

import sys
import os
import unittest.mock as _mock
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Pfad-Setup
# ---------------------------------------------------------------------------

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# ---------------------------------------------------------------------------
# Discord-Mocking
# ---------------------------------------------------------------------------

def _passthrough_decorator(**kwargs):
    def deco(func):
        return func
    return deco

def _passthrough_single(func):
    return func

for mod_name in (
    'discord', 'discord.ext', 'discord.ext.tasks', 'discord.ext.commands',
    'discord.ui', 'discord.app_commands',
    'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',
    'PIL.ImageChops', 'PIL.ImageOps',
    'svglib', 'svglib.svglib',
    'reportlab', 'reportlab.graphics', 'reportlab.graphics.renderPM',
    'requests',
    'dotenv',
):
    sys.modules.setdefault(mod_name, _mock.MagicMock())

sys.modules['dotenv'].load_dotenv = lambda: None

_discord = sys.modules['discord']
_discord.ButtonStyle = MagicMock()
_discord.ButtonStyle.success = 'success'
_discord.ButtonStyle.danger = 'danger'
_discord.ButtonStyle.secondary = 'secondary'

_ui = sys.modules['discord.ui']


class FakeView:
    def __init__(self, **kw):
        self.children = []
    def add_item(self, item):
        self.children.append(item)


class FakeButton:
    def __init__(self, **kw):
        self.style = kw.get('style', '')
        self.emoji = kw.get('emoji', None)
        self.label = kw.get('label', '')
        self.custom_id = kw.get('custom_id', '')
        self.row = kw.get('row', 0)
        self.callback = None


_ui.View = FakeView
_ui.Button = FakeButton
_ui.button = lambda **kw: _passthrough_single

# discord.ui muss auch ueber discord.ui erreichbar sein (from discord import ui)
_discord.ui = _ui


# ---------------------------------------------------------------------------
# Test-Runner
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Imports (NACH Mocking)
# ---------------------------------------------------------------------------

import puzzle.buttons as btn_mod


def reset():
    btn_mod._clicks.clear()


# ===================================================================
# TESTS
# ===================================================================


def test_count_empty():
    """Tests: _count bei leerer Registry."""
    print('[_count empty]')
    reset()
    check('unregistrierte msg_id: 0', btn_mod._count(999, 'x') == 0)
    check('unregistriertes emoji: 0', btn_mod._count(999, 'y') == 0)


def test_apply_click_basic():
    """Tests: _apply_click Grundfunktion."""
    print('[_apply_click basic]')
    reset()

    # Erster Klick: +1
    delta, removed = btn_mod._apply_click(1, 'x', user_id=10)
    check('erster Klick: delta=+1', delta == 1)
    check('erster Klick: removed=None', removed is None)
    check('count=1', btn_mod._count(1, 'x') == 1)

    # Toggle-Off: -1
    delta, removed = btn_mod._apply_click(1, 'x', user_id=10)
    check('toggle-off: delta=-1', delta == -1)


def test_apply_click_mutex():
    """Tests: Mutex-Paare."""
    print('[_apply_click mutex]')
    reset()

    # Klick auf check, dann cross: check wird entfernt
    btn_mod._apply_click(1, '\u2705', user_id=10)
    delta, removed = btn_mod._apply_click(1, '\u274c', user_id=10)
    check('cross entfernt check: removed', removed == '\u2705')
    check('cross entfernt check: check count=0', btn_mod._count(1, '\u2705') == 0)
    check('cross entfernt check: cross count=1', btn_mod._count(1, '\u274c') == 1)

    # Klick auf thumbsup, dann thumbsdown
    reset()
    btn_mod._apply_click(2, '\U0001f44d', user_id=20)
    delta, removed = btn_mod._apply_click(2, '\U0001f44e', user_id=20)
    check('thumbsdown entfernt thumbsup', removed == '\U0001f44d')
    check('thumbsdown count=1', btn_mod._count(2, '\U0001f44e') == 1)

    # Trash hat keinen Partner
    reset()
    btn_mod._apply_click(3, '\U0001f5d1', user_id=30)
    delta, removed = btn_mod._apply_click(3, '\U0001f5d1', user_id=30)
    check('trash: kein Partner (toggle)', removed is None)


def test_multi_user():
    """Tests: Mehrere User."""
    print('[multi_user]')
    reset()

    btn_mod._apply_click(1, '\u2705', user_id=10)
    btn_mod._apply_click(1, '\u2705', user_id=20)
    check('2 User: count=2', btn_mod._count(1, '\u2705') == 2)

    # Einer toggled
    btn_mod._apply_click(1, '\u2705', user_id=10)
    check('1 toggled: count=1', btn_mod._count(1, '\u2705') == 1)

    # User 20 noch drin
    users = btn_mod._clicks[1]['\u2705']
    check('User 20 noch drin', 20 in users)


def test_lru_eviction():
    """Tests: LRU-Eviction bei >500 Messages."""
    print('[lru_eviction]')
    reset()

    for i in range(501):
        btn_mod._apply_click(1000 + i, '\u2705', user_id=1)

    # Erste Message evicted
    check('erste evicted: count=0', btn_mod._count(1000, '\u2705') == 0)
    # Letzte noch da
    check('letzte noch da', btn_mod._count(1500, '\u2705') == 1)
    # Groesse <= 500
    check('Groesse <= 500', len(btn_mod._clicks) <= 500)


def test_fresh_view():
    """Tests: fresh_view erzeugt View mit Counter=0."""
    print('[fresh_view]')
    reset()

    view = btn_mod.fresh_view()
    labels = [c.label for c in view.children if hasattr(c, 'label')]
    check('alle Labels = 0', all(l == '0' for l in labels), f'labels={labels}')
    check('5 Buttons', len(view.children) == 5, f'got {len(view.children)}')


def test_puzzle_view_structure():
    """Tests: PuzzleView hat korrekte Struktur."""
    print('[PuzzleView structure]')
    reset()

    view = btn_mod.PuzzleView()
    check('5 children', len(view.children) == 5)
    ids = [c.custom_id for c in view.children if hasattr(c, 'custom_id')]
    check('custom_id beginnt mit puzzle:', all(cid.startswith('puzzle:') for cid in ids))


# ===================================================================
# MAIN
# ===================================================================

if __name__ == '__main__':
    print('=== test_buttons.py ===\n')
    test_count_empty()
    test_apply_click_basic()
    test_apply_click_mutex()
    test_multi_user()
    test_lru_eviction()
    test_fresh_view()
    test_puzzle_view_structure()
    print(f'\n--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
