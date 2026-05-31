"""Standalone-Tests für den RookHub-Client (puzzle/rookhub.py).

Ausführen: python tests/test_rookhub.py
Braucht nur python-chess + requests (kein discord, keine PGN-Daten).
"""

import os
import sys
import importlib.util

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

import chess

# rookhub.py direkt per Pfad laden – umgeht puzzle/__init__.py (discord-abhängig),
# da rookhub.py selbst keine paket-internen Importe hat.
_spec = importlib.util.spec_from_file_location(
    'rookhub_standalone', os.path.join(_REPO, 'puzzle', 'rookhub.py'))
rh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rh)


_failures = []


def check(name, cond):
    print(('  OK   ' if cond else '  FAIL ') + name)
    if not cond:
        _failures.append(name)


class _FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise rh.requests.HTTPError(f'status {self.status_code}')


def _patch_get(fn):
    rh.requests.get = fn


def test_get_puzzle_ok():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured['url'] = url
        captured['params'] = params
        return _FakeResp(200, {'id': 42, 'fen': 'x', 'moves': 'e2e4'})

    _patch_get(fake_get)
    dto = rh.get_puzzle('daily', exclude=[1, 2])
    check('get_puzzle gibt dto', dto is not None and dto['id'] == 42)
    check('get_puzzle ruft /random', captured['url'].endswith('/api/book-puzzles/random'))
    check('get_puzzle pool-param', captured['params']['pool'] == 'daily')
    check('get_puzzle exclude-param', captured['params']['exclude'] == '1,2')


def test_get_puzzle_404():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    _patch_get(lambda url, params=None, timeout=None: _FakeResp(404))
    check('get_puzzle 404 → None', rh.get_puzzle('blind') is None)


def test_get_puzzle_no_url():
    rh.ROOKHUB_API_URL = ''
    check('get_puzzle ohne API-URL → None', rh.get_puzzle('random') is None)


def test_lookup_and_url():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    rh.ROOKHUB_WEB_URL = 'https://rookhub.example'
    _patch_get(lambda url, params=None, timeout=None: _FakeResp(200, {'id': 7}))
    check('lookup_puzzle_id', rh.lookup_puzzle_id('book.pgn:1.1') == 7)
    check('puzzle_web_url (web base)', rh.puzzle_web_url(7) == 'https://rookhub.example/puzzles/book/7')
    check('web_url_for_line', rh.web_url_for_line('book.pgn:1.1') == 'https://rookhub.example/puzzles/book/7')
    check('puzzle_web_url None → None', rh.puzzle_web_url(None) is None)


def test_url_falls_back_to_api():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    rh.ROOKHUB_WEB_URL = ''
    check('web_url fällt auf API-URL zurück', rh.puzzle_web_url(3) == 'http://rookhub:5001/puzzles/book/3')


def test_lookup_caches_hit():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    rh._id_cache.clear()
    calls = {'n': 0}
    def fake_get(url, params=None, timeout=None):
        calls['n'] += 1
        return _FakeResp(200, {'id': 7})
    _patch_get(fake_get)
    check('lookup 1. Aufruf', rh.lookup_puzzle_id('b.pgn:1') == 7)
    check('lookup 2. Aufruf (cached)', rh.lookup_puzzle_id('b.pgn:1') == 7)
    check('nur 1 HTTP-Call dank Cache', calls['n'] == 1)


def test_lookup_caches_404():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    rh._id_cache.clear()
    calls = {'n': 0}
    def fake_get(url, params=None, timeout=None):
        calls['n'] += 1
        return _FakeResp(404)
    _patch_get(fake_get)
    check('404 → None', rh.lookup_puzzle_id('x.pgn:9') is None)
    check('404 2. Aufruf → None', rh.lookup_puzzle_id('x.pgn:9') is None)
    check('404 gecached (nur 1 Call)', calls['n'] == 1)


def test_game_from_puzzle_illegal_raises():
    # Illegaler Setup-Zug (e2e5 aus der Grundstellung) → parse_uci wirft →
    # der Aufrufer (post_rookhub_puzzle try/except) überspringt das Puzzle.
    import chess as _chess
    dto = {'fen': 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
           'moves': 'e2e5 e7e5'}
    raised = False
    try:
        rh.game_from_puzzle(dto)
    except (_chess.IllegalMoveError, _chess.InvalidMoveError, ValueError, AssertionError):
        raised = True
    check('illegaler moves[0] wirft (kein stilles Korrumpieren)', raised)


def test_game_from_puzzle():
    # fen = Grundstellung; moves[0]=e2e4 (Setup) → Trainingsposition (Schwarz am Zug),
    # Lösung = e7e5 g1f3
    dto = {
        'fen': 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
        'moves': 'e2e4 e7e5 g1f3',
        'title': 'Test', 'chapter': 'Kap', 'bookFileName': 'b.pgn',
    }
    game, solution = rh.game_from_puzzle(dto)
    board = game.board()
    check('Trainingsposition: Schwarz am Zug', board.turn == chess.BLACK)
    check('Trainingsposition: e4-Bauer steht', board.piece_at(chess.E4) is not None)
    check('Lösung = moves[1:]', solution == ['e7e5', 'g1f3'])
    mainline = list(game.mainline_moves())
    check('Mainline hat 2 Lösungszüge', len(mainline) == 2)
    check('erster Lösungszug e7e5', mainline[0].uci() == 'e7e5')
    check('Header Title→White', game.headers['White'] == 'Test')


def main():
    for t in (test_get_puzzle_ok, test_get_puzzle_404, test_get_puzzle_no_url,
              test_lookup_and_url, test_url_falls_back_to_api,
              test_lookup_caches_hit, test_lookup_caches_404,
              test_game_from_puzzle_illegal_raises, test_game_from_puzzle):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle RookHub-Client-Tests bestanden.')


if __name__ == '__main__':
    main()
