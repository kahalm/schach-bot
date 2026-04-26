"""
Unit-Tests fuer core/stats.py.

Standalone-Script. Kein Discord-Mocking noetig (pure stdlib).

Ausfuehren: python tests/test_stats.py
"""

import sys
import os
import tempfile
import shutil

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

import core.paths
import core.stats as stats_mod
from core.json_store import _locks

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
# Helpers
# ---------------------------------------------------------------------------

_tmpdir = None
_orig_config_dir = None


def setup():
    global _tmpdir, _orig_config_dir
    _tmpdir = tempfile.mkdtemp(prefix='schach_test_stats_')
    _orig_config_dir = core.paths.CONFIG_DIR
    core.paths.CONFIG_DIR = _tmpdir

    stats_mod.STATS_FILE = os.path.join(_tmpdir, 'user_stats.json')
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


def test_inc_basic():
    """Tests: inc Grundfunktion."""
    print('[inc basic]')
    setup()
    try:
        # Neuer User
        stats_mod.inc(42, 'solved')
        result = stats_mod.get(42)
        check('neuer User: solved=1', result.get('solved') == 1)

        # Inkrement
        stats_mod.inc(42, 'solved')
        result = stats_mod.get(42)
        check('Inkrement: solved=2', result.get('solved') == 2)

        # Zweites Inkrement
        stats_mod.inc(42, 'solved', 3)
        result = stats_mod.get(42)
        check('Inkrement +3: solved=5', result.get('solved') == 5)

        # Zweiter Key
        stats_mod.inc(42, 'failed')
        result = stats_mod.get(42)
        check('zweiter Key: failed=1', result.get('failed') == 1)
    finally:
        teardown()


def test_inc_negative():
    """Tests: inc mit negativem Delta (Reaction-Entfernung)."""
    print('[inc negative]')
    setup()
    try:
        stats_mod.inc(42, 'solved', 1)
        stats_mod.inc(42, 'solved', -1)
        result = stats_mod.get(42)
        check('delta -1: solved=0', result.get('solved') == 0)

        # Ergebnis kann negativ werden
        stats_mod.inc(42, 'solved', -1)
        result = stats_mod.get(42)
        check('negativ moeglich', result.get('solved') == -1)
    finally:
        teardown()


def test_inc_multiple_users():
    """Tests: Separate Eintraege pro User."""
    print('[inc multiple users]')
    setup()
    try:
        stats_mod.inc(1, 'solved', 5)
        stats_mod.inc(2, 'solved', 3)

        # Separate Eintraege
        check('User 1: solved=5', stats_mod.get(1).get('solved') == 5)
        check('User 2: solved=3', stats_mod.get(2).get('solved') == 3)
    finally:
        teardown()


def test_get_empty():
    """Tests: get bei unbekanntem User / leerer Datei."""
    print('[get empty]')
    setup()
    try:
        # Unbekannter User
        result = stats_mod.get(9999)
        check('unbekannter User: {}', result == {})

        # Leere Datei (vor jeglichem Schreiben)
        result = stats_mod.get_all()
        check('leere Datei: {}', result == {})
    finally:
        teardown()


def test_get_all():
    """Tests: get_all."""
    print('[get_all]')
    setup()
    try:
        stats_mod.inc(1, 'a', 1)
        stats_mod.inc(2, 'b', 2)

        result = stats_mod.get_all()
        check('get_all: 2 User', len(result) == 2)
        # Keys sind Strings
        check('Keys sind Strings', all(isinstance(k, str) for k in result.keys()))
    finally:
        teardown()


# ===================================================================
# MAIN
# ===================================================================

if __name__ == '__main__':
    print('=== test_stats.py ===\n')
    test_inc_basic()
    test_inc_negative()
    test_inc_multiple_users()
    test_get_empty()
    test_get_all()
    print(f'\n--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
