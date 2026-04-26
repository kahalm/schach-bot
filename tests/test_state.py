"""
Unit-Tests fuer puzzle/state.py.

Standalone-Script. Discord wird vor dem Import gemockt.

Ausfuehren: python tests/test_state.py
"""

import sys
import os
import json
import tempfile
import shutil
import unittest.mock as _mock
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Pfad-Setup
# ---------------------------------------------------------------------------

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# ---------------------------------------------------------------------------
# Discord-Mocking (minimal, wie test_commands.py)
# ---------------------------------------------------------------------------

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

import core.paths
import puzzle.state as state_mod
from core.json_store import _locks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir = None
_orig_config_dir = None


def setup():
    global _tmpdir, _orig_config_dir
    _tmpdir = tempfile.mkdtemp(prefix='schach_test_state_')
    _orig_config_dir = core.paths.CONFIG_DIR
    core.paths.CONFIG_DIR = _tmpdir

    # Patch file paths
    state_mod.IGNORE_FILE = os.path.join(_tmpdir, 'puzzle_ignore.json')
    state_mod.CHAPTER_IGNORE_FILE = os.path.join(_tmpdir, 'chapter_ignore.json')
    state_mod.PUZZLE_STATE_FILE = os.path.join(_tmpdir, 'puzzle_state.json')
    state_mod.USER_STUDIES_FILE = os.path.join(_tmpdir, 'user_studies.json')

    # Reset caches
    state_mod._ignore_cache = None
    state_mod._chapter_ignore_cache = None
    state_mod._books_config_cache = None
    state_mod._puzzle_msg_ids.clear()
    state_mod._endless_sessions.clear()
    _locks.clear()


def teardown():
    global _tmpdir, _orig_config_dir
    if _orig_config_dir is not None:
        core.paths.CONFIG_DIR = _orig_config_dir
        _orig_config_dir = None
    if _tmpdir:
        shutil.rmtree(_tmpdir, ignore_errors=True)
        _tmpdir = None
    _locks.clear()


# ===================================================================
# TESTS
# ===================================================================


def test_puzzle_msg_registry():
    """Tests fuer Puzzle-Nachrichten-Registry."""
    print('[puzzle_msg_registry]')
    setup()
    try:
        # Register
        state_mod._register_puzzle_msg(100, 'book.pgn:1.1', 'normal')
        check('register: is_puzzle_message', state_mod.is_puzzle_message(100))

        # get_line_id
        check('get_line_id', state_mod.get_puzzle_line_id(100) == 'book.pgn:1.1')

        # get_mode
        check('get_mode normal', state_mod.get_puzzle_mode(100) == 'normal')

        # mode=blind
        state_mod._register_puzzle_msg(101, 'book.pgn:2.1', 'blind')
        check('get_mode blind', state_mod.get_puzzle_mode(101) == 'blind')

        # Unregistered
        check('unregistered: is_puzzle_message=False',
              not state_mod.is_puzzle_message(999))
        check('unregistered: get_line_id=None',
              state_mod.get_puzzle_line_id(999) is None)
        check('unregistered: get_mode=None',
              state_mod.get_puzzle_mode(999) is None)

        # LRU-Eviction (Cap=500)
        for i in range(501):
            state_mod._register_puzzle_msg(1000 + i, f'book.pgn:{i}.1', 'normal')
        # Erste ID (1000) sollte evicted sein
        check('LRU-Eviction: erste evicted',
              not state_mod.is_puzzle_message(1000))
    finally:
        teardown()


def test_ignore_system():
    """Tests fuer Puzzle-Ignore-Liste."""
    print('[ignore_system]')
    setup()
    try:
        # Leere Liste
        result = state_mod._load_ignore_list()
        check('leere Ignore-Liste', len(result) == 0)

        # ignore
        state_mod.ignore_puzzle('book.pgn:1.1')
        result = state_mod._load_ignore_list()
        check('ignore: enthalten', 'book.pgn:1.1' in result)

        # Idempotenz
        state_mod.ignore_puzzle('book.pgn:1.1')
        result = state_mod._load_ignore_list()
        check('ignore: idempotent', len(result) == 1)

        # Zweites ignorieren
        state_mod.ignore_puzzle('book.pgn:2.1')
        result = state_mod._load_ignore_list()
        check('zweites ignore', len(result) == 2)

        # unignore
        state_mod.unignore_puzzle('book.pgn:1.1')
        result = state_mod._load_ignore_list()
        check('unignore: entfernt', 'book.pgn:1.1' not in result)
        check('unignore: anderes bleibt', 'book.pgn:2.1' in result)

        # Cache-Invalidierung: nach ignore ist Cache frisch
        state_mod._ignore_cache = None
        result = state_mod._load_ignore_list()
        check('Cache-Reload: korrekt', 'book.pgn:2.1' in result)

        # Datei-Inhalt
        with open(state_mod.IGNORE_FILE, encoding='utf-8') as f:
            data = json.load(f)
        check('Datei-Inhalt ist sortierte Liste', isinstance(data, list))
    finally:
        teardown()


def test_chapter_ignore():
    """Tests fuer Chapter-Ignore."""
    print('[chapter_ignore]')
    setup()
    try:
        # Leere Liste
        result = state_mod._load_chapter_ignore_list()
        check('leere Chapter-Ignore-Liste', len(result) == 0)

        # ignore_chapter
        state_mod.ignore_chapter('book.pgn', '003')
        result = state_mod._load_chapter_ignore_list()
        check('ignore_chapter: enthalten', 'book.pgn:003' in result)

        # unignore_chapter
        state_mod.unignore_chapter('book.pgn', '003')
        result = state_mod._load_chapter_ignore_list()
        check('unignore_chapter: entfernt', 'book.pgn:003' not in result)

        # _is_chapter_ignored: positiv
        ignored_set = {'book.pgn:003'}
        check('_is_chapter_ignored positiv',
              state_mod._is_chapter_ignored('book.pgn:003.1', ignored_set))

        # _is_chapter_ignored: negativ (anderes Kapitel)
        check('_is_chapter_ignored negativ',
              not state_mod._is_chapter_ignored('book.pgn:004.1', ignored_set))

        # _is_chapter_ignored: malformed (kein Doppelpunkt)
        check('_is_chapter_ignored malformed',
              not state_mod._is_chapter_ignored('nocolon', ignored_set))
    finally:
        teardown()


def test_get_chapter_from_line_id():
    """Tests fuer get_chapter_from_line_id."""
    print('[get_chapter_from_line_id]')
    setup()
    try:
        # Valide ID
        result = state_mod.get_chapter_from_line_id('book.pgn:003.1')
        check('valide ID', result == ('book.pgn', '003'))

        # Anderes Format
        result = state_mod.get_chapter_from_line_id('file.pgn:12.5')
        check('anderes Format', result == ('file.pgn', '12'))

        # Kein Doppelpunkt
        result = state_mod.get_chapter_from_line_id('nocolon')
        check('kein Doppelpunkt: None', result is None)

        # Kein Punkt
        result = state_mod.get_chapter_from_line_id('book.pgn:nopunkt')
        check('kein Punkt: None', result is None)
    finally:
        teardown()


def test_endless_sessions():
    """Tests fuer Endless-Modus."""
    print('[endless_sessions]')
    setup()
    try:
        # Start
        state_mod.start_endless(42, 'book.pgn')
        check('start: is_endless', state_mod.is_endless(42))

        # get_session
        session = state_mod.get_endless_session(42)
        check('get_session: book', session['book'] == 'book.pgn')
        check('get_session: count=0', session['count'] == 0)

        # Stop
        count = state_mod.stop_endless(42)
        check('stop: count=0', count == 0)
        check('stop: nicht mehr endless', not state_mod.is_endless(42))

        # Stale-Eviction (time-Mock)
        state_mod.start_endless(99, None)
        # Manuell last_active in die Vergangenheit setzen
        state_mod._endless_sessions[99]['last_active'] = 0
        # is_endless ruft _evict_stale_endless auf
        check('stale eviction', not state_mod.is_endless(99))
    finally:
        teardown()


def test_puzzle_state_persistence():
    """Tests fuer Puzzle-State (save/load)."""
    print('[puzzle_state_persistence]')
    setup()
    try:
        # Default
        result = state_mod.load_puzzle_state()
        check('Default: posted=[]', result == {'posted': []})

        # save/load
        state_mod.save_puzzle_state({'posted': ['a', 'b']})
        result = state_mod.load_puzzle_state()
        check('save/load', result == {'posted': ['a', 'b']})

        # Ueberschreiben
        state_mod.save_puzzle_state({'posted': ['c']})
        result = state_mod.load_puzzle_state()
        check('ueberschreiben', result == {'posted': ['c']})

        # Datei existiert
        check('Datei existiert', os.path.exists(state_mod.PUZZLE_STATE_FILE))
    finally:
        teardown()


# ===================================================================
# MAIN
# ===================================================================

if __name__ == '__main__':
    print('=== test_state.py ===\n')
    test_puzzle_msg_registry()
    test_ignore_system()
    test_chapter_ignore()
    test_get_chapter_from_line_id()
    test_endless_sessions()
    test_puzzle_state_persistence()
    print(f'\n--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
