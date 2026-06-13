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


def _patch_post(fn):
    rh.requests.post = fn


def test_send_heartbeat_ok():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    rh.ROOKHUB_WEB_URL = ''
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured['url'] = url
        captured['json'] = json
        return _FakeResp(204)

    _patch_post(fake_post)
    ok = rh.send_heartbeat()
    check('send_heartbeat True', ok is True)
    check('send_heartbeat ruft /api/client-log', captured['url'].endswith('/api/client-log'))
    check('send_heartbeat kind=heartbeat_bot', captured['json']['kind'] == 'heartbeat_bot')


def test_send_heartbeat_no_url():
    rh.ROOKHUB_API_URL = ''
    rh.ROOKHUB_WEB_URL = ''
    check('send_heartbeat ohne URL → False', rh.send_heartbeat() is False)


def test_send_heartbeat_falls_back_to_web():
    rh.ROOKHUB_API_URL = ''
    rh.ROOKHUB_WEB_URL = 'http://web:8087'
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured['url'] = url
        return _FakeResp(204)

    _patch_post(fake_post)
    rh.send_heartbeat()
    check('send_heartbeat Fallback auf Web-URL', captured['url'] == 'http://web:8087/api/client-log')


def test_lookup_and_url():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    rh.ROOKHUB_WEB_URL = 'https://rookhub.example'
    _patch_get(lambda url, params=None, timeout=None: _FakeResp(200, {'id': 7}))
    check('lookup_puzzle_id', rh.lookup_puzzle_id('book.pgn:1.1') == 7)
    check('puzzle_web_url (web base)', rh.puzzle_web_url(7) == 'https://rookhub.example/puzzles/book/7')
    check('web_url_for_line', rh.web_url_for_line('book.pgn:1.1') == 'https://rookhub.example/puzzles/book/7')
    check('puzzle_web_url None → None', rh.puzzle_web_url(None) is None)


def test_url_no_fallback_to_api():
    # Bewusst KEIN Fallback auf die API-/interne URL (sonst landen interne Docker-Adressen
    # in Discord-Posts). Ohne ROOKHUB_WEB_URL → kein Link.
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    rh.ROOKHUB_WEB_URL = ''
    check('web_url ohne WEB_URL → None', rh.puzzle_web_url(3) is None)


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


def test_lookup_200_without_id_not_cached():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    rh._id_cache.clear()
    calls = {'n': 0}
    def fake_get(url, params=None, timeout=None):
        calls['n'] += 1
        return _FakeResp(200, {})  # 200 ohne id (transient, z. B. während Import)
    _patch_get(fake_get)
    check('200-ohne-id → None', rh.lookup_puzzle_id('y.pgn:1') is None)
    rh.lookup_puzzle_id('y.pgn:1')
    check('200-ohne-id NICHT gecached (erneuter HTTP-Call)', calls['n'] == 2)


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


def test_game_from_puzzle_startply_minus1():
    # startPly=-1: FEN IST die Trainingsstellung → nichts vorspielen, Lösung ab moves[0].
    # (Bücher wie "1001 Chess Exercises": FEN = Puzzle-Stellung, Zug 1 = Lösung.)
    dto = {
        'fen': '4k2r/1p2npbp/p1b1p1p1/P1q3B1/4P3/2N2N2/1PQ2PPP/3R2K1 w k - 0 1',
        'moves': 'c3d5 e6d5 e4d5',
        'startPly': -1,
        'title': 'Ex', 'chapter': '', 'bookFileName': 'b.pgn',
    }
    game, solution = rh.game_from_puzzle(dto)
    board = game.board()
    check('startPly=-1: Weiss am Zug (FEN unveraendert)', board.turn == chess.WHITE)
    check('startPly=-1: kein Vorspiel (Sd5 noch NICHT gespielt)',
          board.piece_at(chess.D5) is None)
    check('startPly=-1: Loesung = ALLE moves', solution == ['c3d5', 'e6d5', 'e4d5'])
    check('startPly=-1: erster Loesungszug = c3d5',
          list(game.mainline_moves())[0].uci() == 'c3d5')


def test_game_from_puzzle_startply_midline():
    # startPly=3: ganze Partie ab Grundstellung; Marker an moves[3]=b8c6 → Setup-Zug,
    # vorgespult werden moves[0..3], geloest ab moves[4]=f1b5.
    dto = {
        'fen': 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
        'moves': 'e2e4 e7e5 g1f3 b8c6 f1b5 a7a6',
        'startPly': 3,
        'title': 'T', 'chapter': '', 'bookFileName': 'b.pgn',
    }
    game, solution = rh.game_from_puzzle(dto)
    board = game.board()
    check('startPly=3: Weiss am Zug (nach 1.e4 e5 2.Nf3 Nc6)', board.turn == chess.WHITE)
    check('startPly=3: Sf3 steht (vorgespult)', board.piece_at(chess.F3) is not None)
    check('startPly=3: Sc6 steht (Setup-Zug gespielt)', board.piece_at(chess.C6) is not None)
    check('startPly=3: Loesung = moves[4:]', solution == ['f1b5', 'a7a6'])
    check('startPly=3: erster Loesungszug = f1b5 (Lb5)',
          list(game.mainline_moves())[0].uci() == 'f1b5')


def test_get_daily_leaderboard_ok():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured['url'] = url
        captured['params'] = params
        return _FakeResp(200, {'period': '2026-06', 'entries': [{'name': 'Anna', 'points': 28}]})

    _patch_get(fake_get)
    data = rh.get_daily_leaderboard('2026-06')
    check('get_daily_leaderboard gibt dict', data is not None and data['period'] == '2026-06')
    check('get_daily_leaderboard ruft /daily/leaderboard',
          captured['url'].endswith('/api/book-puzzles/daily/leaderboard'))
    check('get_daily_leaderboard month-param', captured['params'] == {'month': '2026-06'})


def test_get_daily_leaderboard_no_month():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured['params'] = params
        return _FakeResp(200, {'period': '2026-06', 'entries': []})

    _patch_get(fake_get)
    rh.get_daily_leaderboard()
    check('get_daily_leaderboard ohne Monat → params None', captured['params'] is None)


def test_get_daily_leaderboard_no_url():
    rh.ROOKHUB_API_URL = ''
    check('get_daily_leaderboard ohne URL → None', rh.get_daily_leaderboard('2026-06') is None)


def test_get_daily_hall_of_fame_ok():
    rh.ROOKHUB_API_URL = 'http://rookhub:5001'
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured['url'] = url
        captured['params'] = params
        return _FakeResp(200, {'mostSolved': [], 'mostGolds': [], 'fastest': None})

    _patch_get(fake_get)
    data = rh.get_daily_hall_of_fame(top=3)
    check('get_daily_hall_of_fame gibt dict', data is not None and 'mostSolved' in data)
    check('get_daily_hall_of_fame ruft /daily/hall-of-fame',
          captured['url'].endswith('/api/book-puzzles/daily/hall-of-fame'))
    check('get_daily_hall_of_fame top-param', captured['params'] == {'top': 3})


def main():
    for t in (test_get_puzzle_ok, test_get_puzzle_404, test_get_puzzle_no_url,
              test_send_heartbeat_ok, test_send_heartbeat_no_url, test_send_heartbeat_falls_back_to_web,
              test_lookup_and_url, test_url_no_fallback_to_api,
              test_lookup_caches_hit, test_lookup_caches_404,
              test_lookup_200_without_id_not_cached,
              test_game_from_puzzle_illegal_raises, test_game_from_puzzle,
              test_game_from_puzzle_startply_minus1, test_game_from_puzzle_startply_midline,
              test_get_daily_leaderboard_ok, test_get_daily_leaderboard_no_month,
              test_get_daily_leaderboard_no_url, test_get_daily_hall_of_fame_ok):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle RookHub-Client-Tests bestanden.')


if __name__ == '__main__':
    main()
