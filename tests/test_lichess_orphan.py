"""
Test: Verwaiste Lichess-Studie nach 429 wird gemerkt und wiederverwendet.

Szenario (offline, ohne Netz/Token):
  1. Neue Studie wird angelegt, danach 429 beim Kapitel-Import
     -> upload_to_lichess gibt None zurueck UND merkt die leere Studie als pending.
  2. Naechster Upload verwendet die pending-Studie wieder (legt KEINE neue an)
     und leert das pending-Feld.

Ausfuehren: python tests/test_lichess_orphan.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import test_helpers  # noqa: F401  -- stubt discord / PIL / svglib / reportlab

import chess
import chess.pgn

from core.json_store import atomic_read, atomic_write
import puzzle.lichess as lichess

_failed = 0


def check(label, ok, detail=''):
    global _failed
    print(f'  {"OK  " if ok else "FAIL"}   {label}{"  -> " + detail if detail else ""}')
    if not ok:
        _failed += 1


class FakeResp:
    def __init__(self, json_data=None, text='', status_code=200):
        self._json = json_data or {}
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')

    def json(self):
        return self._json


def _make_game():
    game = chess.pgn.Game()
    game.headers['White'] = 'Test'
    game.headers['Event'] = 'TestEvent'
    game.add_variation(chess.Move.from_uci('e2e4'))
    return game


def main():
    fd, cooldown_path = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    os.remove(cooldown_path)  # frisch: noch keine Datei

    # Modulzustand isolieren: Token aktiv, eigener Cooldown-/State-Pfad, kein fixes Study.
    lichess.LICHESS_TOKEN = 'test-token'
    lichess.LICHESS_COOLDOWN_FILE = cooldown_path
    lichess.PUZZLE_STUDY_ID = ''

    game = _make_game()

    # --- Phase 1: neue Studie angelegt, dann 429 beim Import ---
    def fake_429_on_import(method, url, **kw):
        if method == 'POST' and url.endswith('/api/study'):
            return FakeResp({'id': 'orphan1'})
        if method == 'GET' and '.pgn' in url:
            return FakeResp(text='')
        if 'import-pgn' in url:
            raise lichess.LichessRateLimitError()
        return FakeResp()

    lichess._lichess_request = fake_429_on_import
    url1 = lichess.upload_to_lichess(game)
    check('Phase1: kein URL bei 429', url1 is None, repr(url1))
    pending = atomic_read(cooldown_path).get('pending_study')
    check('Phase1: verwaiste Studie gemerkt', pending == 'orphan1', repr(pending))

    # --- Phase 2: naechster Upload verwendet die pending-Studie wieder ---
    created_new_again = {'hit': False}

    def fake_ok_reuse(method, url, **kw):
        if method == 'POST' and url.endswith('/api/study'):
            created_new_again['hit'] = True
            return FakeResp({'id': 'should-not-happen'})
        if method == 'GET' and '.pgn' in url:
            return FakeResp(text='')
        if 'import-pgn' in url:
            check('Phase2: Import in wiederverwendete Studie', 'orphan1' in url, url)
            return FakeResp({'chapters': [{'id': 'chap1'}]})
        return FakeResp()

    lichess._lichess_request = fake_ok_reuse
    url2 = lichess.upload_to_lichess(game)
    check('Phase2: KEINE neue Studie angelegt', not created_new_again['hit'])
    check('Phase2: URL zeigt auf recycelte Studie', bool(url2) and 'orphan1' in (url2 or ''), url2 or 'None')
    pending_after = atomic_read(cooldown_path).get('pending_study')
    check('Phase2: pending-Feld geleert', pending_after is None, repr(pending_after))

    try:
        os.remove(cooldown_path)
    except OSError:
        pass

    print(f'\n--- {3 + 3} checks erwartet, {_failed} fehlgeschlagen ---')
    if _failed:
        sys.exit(1)
    print('Lichess-Orphan-Tests bestanden.')


if __name__ == '__main__':
    main()
