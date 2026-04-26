"""
Unit-Tests fuer core/event_log.py.

Standalone-Script. Discord wird vor dem Import gemockt.

Ausfuehren: python tests/test_event_log.py
"""

import sys
import os
import json
import time
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
import core.event_log as elog_mod

# Elo-Lookup mocken (wird lazy importiert)
import commands.elo as elo_mod_ref


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir = None
_orig_config_dir = None


def setup():
    global _tmpdir, _orig_config_dir
    _tmpdir = tempfile.mkdtemp(prefix='schach_test_elog_')
    _orig_config_dir = core.paths.CONFIG_DIR
    core.paths.CONFIG_DIR = _tmpdir

    elog_mod.REACTION_LOG_FILE = os.path.join(_tmpdir, 'reaction_log.jsonl')

    # Elo-Cache zuruecksetzen
    elog_mod._elo_cache.clear()
    elog_mod._elo_cache_ts = 0.0


def teardown():
    global _tmpdir, _orig_config_dir
    if _orig_config_dir is not None:
        core.paths.CONFIG_DIR = _orig_config_dir
        _orig_config_dir = None
    if _tmpdir:
        shutil.rmtree(_tmpdir, ignore_errors=True)
        _tmpdir = None


# ===================================================================
# TESTS
# ===================================================================


def test_log_reaction_basic():
    """Tests: log_reaction schreibt korrekte JSONL-Eintraege."""
    print('[log_reaction basic]')
    setup()
    try:
        # Elo-Lookup mocken
        elo_mod_ref.get_current = MagicMock(return_value=1500)

        elog_mod.log_reaction(user_id=42, line_id='book.pgn:1.1',
                              mode='normal', emoji='x', delta=1)

        # Datei existiert
        check('Datei existiert', os.path.exists(elog_mod.REACTION_LOG_FILE))

        # 1 Zeile
        with open(elog_mod.REACTION_LOG_FILE, encoding='utf-8') as f:
            lines = f.readlines()
        check('1 Zeile', len(lines) == 1)

        # JSON-Felder korrekt
        entry = json.loads(lines[0])
        check('user korrekt', entry['user'] == 42)
        check('line_id korrekt', entry['line_id'] == 'book.pgn:1.1')

        # ISO-Timestamp
        check('ISO-Timestamp', 'T' in entry['ts'] and '+' in entry['ts'])
    finally:
        teardown()


def test_log_multiple():
    """Tests: Mehrere Eintraege."""
    print('[log_multiple]')
    setup()
    try:
        elo_mod_ref.get_current = MagicMock(return_value=None)

        for i in range(3):
            elog_mod.log_reaction(user_id=i, line_id=f'b.pgn:{i}.1',
                                  mode='normal', emoji='y', delta=1)

        with open(elog_mod.REACTION_LOG_FILE, encoding='utf-8') as f:
            lines = f.readlines()
        check('3 Zeilen', len(lines) == 3)

        # read_all gibt 3 zurueck
        entries = elog_mod.read_all()
        check('read_all: 3 Eintraege', len(entries) == 3)

        # Reihenfolge stimmt
        check('Reihenfolge: user 0 zuerst', entries[0]['user'] == 0)
    finally:
        teardown()


def test_read_all_empty():
    """Tests: read_all bei leerer/fehlender Datei."""
    print('[read_all empty]')
    setup()
    try:
        # Nicht-existente Datei
        result = elog_mod.read_all()
        check('nicht-existent: []', result == [])

        # Leere Datei
        with open(elog_mod.REACTION_LOG_FILE, 'w', encoding='utf-8') as f:
            pass
        result = elog_mod.read_all()
        check('leere Datei: []', result == [])
    finally:
        teardown()


def test_read_all_limit():
    """Tests: read_all mit Limit."""
    print('[read_all limit]')
    setup()
    try:
        elo_mod_ref.get_current = MagicMock(return_value=None)

        for i in range(10):
            elog_mod.log_reaction(user_id=i, line_id=f'b.pgn:{i}.1',
                                  mode='normal', emoji='z', delta=1)

        entries = elog_mod.read_all(limit=5)
        check('limit=5: 5 Eintraege', len(entries) == 5)
        check('limit=5: letzte 5 (user=5 zuerst)', entries[0]['user'] == 5)
    finally:
        teardown()


def test_rotate_log():
    """Tests: rotate_log kuerzt auf _MAX_LOG_LINES."""
    print('[rotate_log]')
    setup()
    try:
        # _MAX_LOG_LINES temporaer auf 5 setzen
        old_max = elog_mod._MAX_LOG_LINES
        elog_mod._MAX_LOG_LINES = 5

        # 10 Zeilen schreiben (direkt, nicht ueber log_reaction)
        with open(elog_mod.REACTION_LOG_FILE, 'w', encoding='utf-8') as f:
            for i in range(10):
                f.write(json.dumps({'i': i}) + '\n')

        elog_mod.rotate_log()

        with open(elog_mod.REACTION_LOG_FILE, encoding='utf-8') as f:
            lines = f.readlines()

        check('Rotation: 5 Zeilen', len(lines) == 5, f'got {len(lines)}')

        # Neueste bleiben (i=5..9)
        first = json.loads(lines[0])
        check('neueste bleiben: i=5', first['i'] == 5)

        # Keine Rotation noetig wenn <= MAX
        elog_mod.rotate_log()
        with open(elog_mod.REACTION_LOG_FILE, encoding='utf-8') as f:
            lines2 = f.readlines()
        check('keine unnoetige Rotation', len(lines2) == 5)

        elog_mod._MAX_LOG_LINES = old_max
    finally:
        teardown()


def test_elo_caching():
    """Tests: Elo-Cache mit TTL."""
    print('[elo_caching]')
    setup()
    try:
        call_count = 0
        def fake_get_current(uid):
            nonlocal call_count
            call_count += 1
            return 1800

        elo_mod_ref.get_current = fake_get_current

        # Erster Aufruf: kein Cache
        elo1 = elog_mod._current_elo(42)
        check('erster Aufruf: Wert korrekt', elo1 == 1800)

        # Zweiter Aufruf: Cache-Hit
        calls_before = call_count
        elo2 = elog_mod._current_elo(42)
        check('Cache-Hit: kein erneuter Aufruf', call_count == calls_before)

        # TTL-Ablauf simulieren
        elog_mod._elo_cache_ts = time.monotonic() - elog_mod._ELO_CACHE_TTL - 1
        elo3 = elog_mod._current_elo(42)
        check('TTL-Ablauf: erneuter Aufruf', call_count == calls_before + 1)
    finally:
        teardown()


# ===================================================================
# MAIN
# ===================================================================

if __name__ == '__main__':
    print('=== test_event_log.py ===\n')
    test_log_reaction_basic()
    test_log_multiple()
    test_read_all_empty()
    test_read_all_limit()
    test_rotate_log()
    test_elo_caching()
    print(f'\n--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
