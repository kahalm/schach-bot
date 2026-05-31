"""RookHub-Client: Puzzles vom RookHub-Portal beziehen und verlinken.

Ersetzt die frühere Lichess-Anbindung. Der Bot wählt keine Puzzles mehr lokal
für Daily/Random/Blind, sondern fragt RookHub nach einem Puzzle aus dem passenden
Pool und postet den Link `…/puzzles/book/{id}`.

Bewusst ohne discord-Abhängigkeit (nur requests + python-chess), damit eigenständig
testbar.
"""

import os
import logging

import chess
import chess.pgn
import requests

log = logging.getLogger('schach-bot')

ROOKHUB_API_URL = os.getenv('ROOKHUB_API_URL', '').rstrip('/')
ROOKHUB_WEB_URL = os.getenv('ROOKHUB_WEB_URL', '').rstrip('/')

_TIMEOUT = 15


def _api(path: str) -> str:
    return f'{ROOKHUB_API_URL}{path}'


def get_puzzle(pool: str = 'random', exclude=None, timeout: int = _TIMEOUT) -> dict | None:
    """Holt ein zufälliges Buch-Puzzle aus dem Pool (``daily`` | ``random`` | ``blind``).

    Gibt das BookPuzzleDto als dict zurück oder ``None`` (kein Puzzle / Fehler).
    """
    if not ROOKHUB_API_URL:
        log.warning('ROOKHUB_API_URL nicht gesetzt – kann kein Puzzle von RookHub holen.')
        return None
    params = {'pool': pool}
    if exclude:
        params['exclude'] = ','.join(str(e) for e in exclude)
    try:
        r = requests.get(_api('/api/book-puzzles/random'), params=params, timeout=timeout)
        if r.status_code == 404:
            log.info('RookHub: kein Puzzle im Pool "%s".', pool)
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        log.warning('RookHub get_puzzle(%s) fehlgeschlagen: %s', pool, e)
        return None


def lookup_puzzle_id(line_id: str, timeout: int = _TIMEOUT) -> int | None:
    """Schlägt die RookHub-ID eines Puzzles anhand seiner line_id nach."""
    if not ROOKHUB_API_URL or not line_id:
        return None
    try:
        r = requests.get(_api('/api/book-puzzles/by-line-id'),
                         params={'lineId': line_id}, timeout=timeout)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get('id')
    except requests.RequestException as e:
        log.debug('RookHub lookup_puzzle_id(%s) fehlgeschlagen: %s', line_id, e)
        return None


def puzzle_web_url(puzzle_id: int | None) -> str | None:
    """Baut die anklickbare RookHub-URL zum interaktiven Lösen."""
    if puzzle_id is None:
        return None
    base = ROOKHUB_WEB_URL or ROOKHUB_API_URL
    return f'{base}/puzzles/book/{puzzle_id}' if base else None


def web_url_for_line(line_id: str) -> str | None:
    """Convenience: line_id → RookHub-Link (Lookup + URL-Bau)."""
    return puzzle_web_url(lookup_puzzle_id(line_id))


def game_from_puzzle(dto: dict) -> tuple[chess.pgn.Game, list[str]]:
    """Baut aus einem RookHub-BookPuzzleDto ein ``chess.pgn.Game``.

    RookHub speichert ``fen`` = Stellung vor dem Setup-Zug und ``moves`` als
    leerzeichengetrennte UCI-Züge, wobei ``moves[0]`` der Setup-/Gegnerzug ist und
    der Spieler ab ``moves[1]`` löst (analog zur RookHub-Lös-UI).

    Es wird ``moves[0]`` gespielt, sodass ``game.board()`` die **Trainingsposition**
    liefert (passend für ``safe_render_board`` / ``build_puzzle_embed``). Rückgabe:
    ``(game, solution_uci)`` mit ``solution_uci = moves[1:]``.
    """
    fen = dto['fen']
    moves = (dto.get('moves') or '').split()

    board = chess.Board(fen)
    if moves:
        board.push(chess.Move.from_uci(moves[0]))  # Setup-Zug → Trainingsposition

    game = chess.pgn.Game()
    game.headers['Event'] = dto.get('bookFileName') or 'RookHub'
    game.headers['White'] = dto.get('title') or ''
    game.headers['Black'] = dto.get('chapter') or ''
    game.setup(board)

    node = game
    for uci in moves[1:]:
        node = node.add_variation(chess.Move.from_uci(uci))

    return game, moves[1:]
