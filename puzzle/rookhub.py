"""RookHub-Client: Puzzles vom RookHub-Portal beziehen und verlinken.

Ersetzt die frühere Lichess-Anbindung. Der Bot wählt keine Puzzles mehr lokal
für Daily/Random/Blind, sondern fragt RookHub nach einem Puzzle aus dem passenden
Pool und postet den Link `…/puzzles/book/{id}`.

Bewusst ohne discord-Abhängigkeit (nur requests + python-chess), damit eigenständig
testbar.
"""

import os
import logging
import threading

import chess
import chess.pgn
import requests

log = logging.getLogger('schach-bot')

ROOKHUB_API_URL = os.getenv('ROOKHUB_API_URL', '').rstrip('/')
ROOKHUB_WEB_URL = os.getenv('ROOKHUB_WEB_URL', '').rstrip('/')

_TIMEOUT = 15
# Kürzerer Timeout für den (häufigen, per Puzzle aufgerufenen) Link-Lookup, damit ein
# langsames/nicht erreichbares RookHub nicht ganze Commands blockiert.
_LOOKUP_TIMEOUT = 4

# In-Memory-Cache line_id → id (None = in RookHub nicht vorhanden). Stabil, da RookHub-IDs
# sich nicht ändern; wird beim Bot-Neustart geleert (deckt nachträgliche Importe ab).
_id_cache: dict[str, int | None] = {}
_id_cache_lock = threading.Lock()


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


def lookup_puzzle_id(line_id: str, timeout: int = _LOOKUP_TIMEOUT) -> int | None:
    """Schlägt die RookHub-ID eines Puzzles anhand seiner line_id nach (gecached)."""
    if not ROOKHUB_API_URL or not line_id:
        return None
    with _id_cache_lock:
        if line_id in _id_cache:
            return _id_cache[line_id]
    try:
        r = requests.get(_api('/api/book-puzzles/by-line-id'),
                         params={'lineId': line_id}, timeout=timeout)
        if r.status_code == 404:
            with _id_cache_lock:
                _id_cache[line_id] = None  # echtes 404: in RookHub nicht vorhanden → dauerhaft cachen
            return None
        r.raise_for_status()
        pid = r.json().get('id')
        if pid is not None:
            with _id_cache_lock:
                _id_cache[line_id] = pid  # nur echte IDs cachen
        # 200 ohne id (z. B. während eines Imports / Proxy-Fehlerseite) gilt als transient
        # → NICHT cachen, damit ein späterer Aufruf erneut versucht.
        return pid
    except requests.RequestException as e:
        # Transiente Fehler NICHT cachen (nächster Aufruf darf erneut versuchen).
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

    ``fen`` + ``moves`` enthalten die KOMPLETTE Partie; ``startPly`` markiert den
    Trainingsstart (analog zur RookHub-Lös-UI):

    * ``startPly = -1`` → ``fen`` IST bereits die Trainingsstellung; nichts
      vorspielen, Lösung = ``moves[0:]`` (z. B. Bücher mit FEN = Puzzle-Stellung).
    * ``startPly = k ≥ 0`` → ``moves[0..k]`` vorspulen (``moves[k]`` ist der
      Setup-/Gegnerzug in die Trainingsstellung), Lösung = ``moves[k+1:]``.

    Fehlt ``startPly`` (alte/fremde DTOs), gilt ``0`` (klassisch: ``moves[0]`` als
    Setup, Lösung ab ``moves[1]``).

    Es wird bis zur Trainingsstellung vorgespielt, sodass ``game.board()`` die
    Stellung liefert, ab der gelöst wird (passend für ``safe_render_board`` /
    ``build_puzzle_embed``). Rückgabe: ``(game, solution_uci)``.
    """
    fen = dto['fen']
    moves = (dto.get('moves') or '').split()
    start_ply = dto.get('startPly')
    if start_ply is None:
        start_ply = 0

    # Anzahl Halbzüge, die bis zur Trainingsstellung vorgespielt werden.
    # startPly=-1 → 0 (kein Vorspiel); startPly=k → k+1 (inkl. Setup-Zug moves[k]).
    setup_count = min(max(0, start_ply + 1), len(moves))

    board = chess.Board(fen)
    for uci in moves[:setup_count]:
        # parse_uci validiert die Legalität (wirft bei illegalem/ungültigem Zug) – so wird
        # ein kaputtes DTO vom Aufrufer als „Puzzle überspringen" behandelt statt still ein
        # korruptes Brett zu posten.
        board.push(board.parse_uci(uci))

    solution = moves[setup_count:]

    game = chess.pgn.Game()
    game.headers['Event'] = dto.get('bookFileName') or 'RookHub'
    game.headers['White'] = dto.get('title') or ''
    game.headers['Black'] = dto.get('chapter') or ''
    game.setup(board)

    node = game
    solboard = board.copy()
    for uci in solution:
        mv = solboard.parse_uci(uci)  # validiert jeden Lösungszug gegen die Stellung
        solboard.push(mv)
        node = node.add_variation(mv)

    return game, solution
