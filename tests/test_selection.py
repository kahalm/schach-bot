"""
Unit-Tests fuer puzzle/selection.py.

Standalone-Script. Discord + chess werden gemockt bzw. mit echten PGNs getestet.

Ausfuehren: python tests/test_selection.py
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
# Discord-Mocking
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
import puzzle.selection as sel_mod
from core.json_store import _locks

# ---------------------------------------------------------------------------
# Synthetische PGN-Dateien
# ---------------------------------------------------------------------------

# Minimales PGN mit [%tqu]-Annotation (3 Runden)
_PGN_A = """\
[Event "Test A"]
[Round "1.1"]
[FEN "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"]

1... e5 {[%tqu "En","","","e7e5","",10]} *

[Event "Test A"]
[Round "1.2"]
[FEN "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"]

1... d5 {[%tqu "En","","","d7d5","",10]} *

[Event "Test A"]
[Round "2.1"]
[FEN "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"]

1... c5 {[%tqu "En","","","c7c5","",10]} *
"""

# 2 Runden, random:false, blind:true
_PGN_B = """\
[Event "Test B"]
[Round "1.1"]
[FEN "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"]

1... Nf6 {[%tqu "En","","","g8f6","",10]} *

[Event "Test B"]
[Round "1.2"]
[FEN "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"]

1... Nc6 {[%tqu "En","","","b8c6","",10]} *
"""

_BOOKS_JSON = {
    'test_a.pgn': {'difficulty': 1, 'random': True, 'blind': False},
    'test_b.pgn': {'difficulty': 2, 'random': False, 'blind': True},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir = None
_orig_config_dir = None
_orig_books_dir = None


def setup():
    global _tmpdir, _orig_config_dir, _orig_books_dir
    _tmpdir = tempfile.mkdtemp(prefix='schach_test_sel_')
    _orig_config_dir = core.paths.CONFIG_DIR
    _orig_books_dir = state_mod.BOOKS_DIR
    core.paths.CONFIG_DIR = _tmpdir

    # Books-Dir im tmpdir
    books_dir = os.path.join(_tmpdir, 'books')
    os.makedirs(books_dir)
    state_mod.BOOKS_DIR = books_dir
    sel_mod.BOOKS_DIR = books_dir

    # PGN-Dateien schreiben
    with open(os.path.join(books_dir, 'test_a.pgn'), 'w', encoding='utf-8') as f:
        f.write(_PGN_A)
    with open(os.path.join(books_dir, 'test_b.pgn'), 'w', encoding='utf-8') as f:
        f.write(_PGN_B)
    with open(os.path.join(books_dir, 'books.json'), 'w', encoding='utf-8') as f:
        json.dump(_BOOKS_JSON, f)

    # File-Pfade patchen
    state_mod.IGNORE_FILE = os.path.join(_tmpdir, 'puzzle_ignore.json')
    state_mod.CHAPTER_IGNORE_FILE = os.path.join(_tmpdir, 'chapter_ignore.json')
    state_mod.PUZZLE_STATE_FILE = os.path.join(_tmpdir, 'puzzle_state.json')
    sel_mod.PUZZLE_CACHE_FILE = os.path.join(_tmpdir, 'puzzle_lines.pkl')

    # Caches leeren
    sel_mod._lines_cache = None
    sel_mod._lines_cache_fp = None
    state_mod._ignore_cache = None
    state_mod._chapter_ignore_cache = None
    state_mod._books_config_cache = None
    _locks.clear()


def teardown():
    global _tmpdir, _orig_config_dir, _orig_books_dir
    if _orig_config_dir is not None:
        core.paths.CONFIG_DIR = _orig_config_dir
        _orig_config_dir = None
    if _orig_books_dir is not None:
        state_mod.BOOKS_DIR = _orig_books_dir
        sel_mod.BOOKS_DIR = _orig_books_dir
        _orig_books_dir = None
    if _tmpdir:
        shutil.rmtree(_tmpdir, ignore_errors=True)
        _tmpdir = None
    sel_mod._lines_cache = None
    sel_mod._lines_cache_fp = None
    _locks.clear()


# ===================================================================
# TESTS
# ===================================================================


def test_list_pgn_files():
    """Tests fuer _list_pgn_files."""
    print('[_list_pgn_files]')
    setup()
    try:
        files = sel_mod._list_pgn_files()
        check('sortierte Liste', files == ['test_a.pgn', 'test_b.pgn'])

        # books.json nicht enthalten
        check('kein books.json', 'books.json' not in files)

        # Leerer Ordner
        empty_dir = os.path.join(_tmpdir, 'empty')
        os.makedirs(empty_dir)
        old = sel_mod.BOOKS_DIR
        sel_mod.BOOKS_DIR = empty_dir
        check('leerer Ordner: leer', sel_mod._list_pgn_files() == [])
        sel_mod.BOOKS_DIR = old
    finally:
        teardown()


def test_load_all_lines():
    """Tests fuer load_all_lines."""
    print('[load_all_lines]')
    setup()
    try:
        lines = sel_mod.load_all_lines()

        # 5 Linien total (3 aus test_a + 2 aus test_b)
        check('5 Linien geladen', len(lines) == 5, f'got {len(lines)}')

        # Korrekte Tupel
        lid, game = lines[0]
        check('Tupel: line_id ist str', isinstance(lid, str))

        # line_id-Format: "filename:round"
        check('line_id-Format', ':' in lid and lid.startswith('test_'))

        # Alle haben line_ids
        all_ids = [lid for lid, _ in lines]
        check('alle IDs vorhanden', len(all_ids) == 5)
    finally:
        teardown()


def test_fingerprint_and_cache():
    """Tests fuer _books_fingerprint und Cache."""
    print('[fingerprint_and_cache]')
    setup()
    try:
        fp1 = sel_mod._books_fingerprint()

        # Fingerprint ist Tupel
        check('Fingerprint ist Tupel', isinstance(fp1, tuple))

        # VERSION enthalten
        version_items = [item for item in fp1 if item[0] == '__version__']
        check('VERSION enthalten', len(version_items) == 1)

        # Cache-Hit: zweiter Aufruf nutzt Cache
        lines1 = sel_mod.load_all_lines()
        lines2 = sel_mod.load_all_lines()
        check('Cache-Hit: gleiche Referenz', lines1 is lines2)

        # clear_lines_cache
        sel_mod.clear_lines_cache()
        check('clear_lines_cache: cache=None', sel_mod._lines_cache is None)
    finally:
        teardown()


def test_chapter_helpers():
    """Tests fuer _find_chapter_prefix und _list_chapters."""
    print('[chapter_helpers]')
    setup()
    try:
        # _list_chapters
        chapters = sel_mod._list_chapters('test_a.pgn')
        check('_list_chapters: 2 Kapitel', len(chapters) == 2,
              f'got {len(chapters)}: {chapters}')
        check('_list_chapters: Kapitel 1 hat 2 Linien',
              chapters.get('1') == 2 or chapters.get('1.') == 2,
              f'chapters={chapters}')

        # _find_chapter_prefix
        prefix = sel_mod._find_chapter_prefix('test_a.pgn', 1)
        check('_find_chapter_prefix: gefunden', prefix == '1')

        # _find_chapter_prefix: nicht-existentes Kapitel
        prefix = sel_mod._find_chapter_prefix('test_a.pgn', 99)
        check('_find_chapter_prefix: nicht gefunden', prefix is None)

        # Nicht-existentes Buch
        chapters = sel_mod._list_chapters('nonexistent.pgn')
        check('nicht-existentes Buch: leer', len(chapters) == 0)
    finally:
        teardown()


def test_get_random_books():
    """Tests fuer get_random_books."""
    print('[get_random_books]')
    setup()
    try:
        result = sel_mod.get_random_books()
        check('nur random:true', 'test_a.pgn' in result)
        check('test_b nicht enthalten', 'test_b.pgn' not in result)
    finally:
        teardown()


def test_get_blind_books():
    """Tests fuer get_blind_books."""
    print('[get_blind_books]')
    setup()
    try:
        result = sel_mod.get_blind_books()
        check('nur blind:true', 'test_b.pgn' in result)
        check('test_a nicht enthalten', 'test_a.pgn' not in result)
    finally:
        teardown()


def test_find_line_by_id():
    """Tests fuer find_line_by_id."""
    print('[find_line_by_id]')
    setup()
    try:
        # Exakt-Match
        result = sel_mod.find_line_by_id('test_a.pgn:1.1')
        check('Exakt-Match', result is not None and result[0] == 'test_a.pgn:1.1')

        # Suffix-Match mit ':'
        result = sel_mod.find_line_by_id('1.1')
        check('Suffix-Match', result is not None and result[0].endswith(':1.1'))

        # Nicht gefunden
        result = sel_mod.find_line_by_id('nonexistent:99.99')
        check('nicht gefunden', result is None)

        # 'id:'-Prefix
        result = sel_mod.find_line_by_id('id:test_a.pgn:1.1')
        check('id:-Prefix', result is not None and result[0] == 'test_a.pgn:1.1')

        # Laenge >200
        result = sel_mod.find_line_by_id('x' * 201)
        check('Laenge >200: None', result is None)
    finally:
        teardown()


def test_pick_sequential_lines():
    """Tests fuer pick_sequential_lines."""
    print('[pick_sequential_lines]')
    setup()
    try:
        # Korrekte Anzahl
        result = sel_mod.pick_sequential_lines('test_a.pgn', 0, 2)
        check('korrekte Anzahl', len(result) == 2, f'got {len(result)}')

        # Ignorierte uebersprungen
        state_mod.ignore_puzzle('test_a.pgn:1.1')
        state_mod._ignore_cache = None
        result = sel_mod.pick_sequential_lines('test_a.pgn', 0, 10)
        ids = [lid for lid, _ in result]
        check('ignorierte uebersprungen', 'test_a.pgn:1.1' not in ids)
    finally:
        teardown()


# ===================================================================
# MAIN
# ===================================================================

if __name__ == '__main__':
    print('=== test_selection.py ===\n')
    test_list_pgn_files()
    test_load_all_lines()
    test_fingerprint_and_cache()
    test_chapter_helpers()
    test_get_random_books()
    test_get_blind_books()
    test_find_line_by_id()
    test_pick_sequential_lines()
    print(f'\n--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
