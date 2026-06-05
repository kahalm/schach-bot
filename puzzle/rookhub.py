"""RookHub-Client: Puzzles vom RookHub-Portal beziehen und verlinken.

Ersetzt die frühere Lichess-Anbindung. Der Bot wählt keine Puzzles mehr lokal
für Daily/Random/Blind, sondern fragt RookHub nach einem Puzzle aus dem passenden
Pool und postet den Link `…/puzzles/book/{id}`.

Bewusst ohne discord-Abhängigkeit (nur requests + python-chess), damit eigenständig
testbar.
"""

import hashlib
import hmac
import os
import logging
import threading
from datetime import datetime, timezone

import chess
import chess.pgn
import requests

log = logging.getLogger('schach-bot')

ROOKHUB_API_URL = os.getenv('ROOKHUB_API_URL', '').rstrip('/')
ROOKHUB_WEB_URL = os.getenv('ROOKHUB_WEB_URL', '').rstrip('/')
# Geteiltes HMAC-Secret fuer den Bot-Stats-Endpoint (== RookHubs SchachBot__StatsSecret).
# Leer → get_player_progress liefert immer None (Feature inaktiv).
ROOKHUB_STATS_SECRET = os.getenv('ROOKHUB_STATS_SECRET', '')

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


def send_heartbeat(timeout: int = _LOOKUP_TIMEOUT) -> bool:
    """Sendet ein Lebenszeichen an RookHubs ``/api/client-log`` (landet in ``rookhub-logs-*`` in
    Elasticsearch), damit der log-watcher einen toten/hängenden Bot an AUSBLEIBENDEN Heartbeats
    erkennt — der Bot selbst loggt nicht nach ES. Fire-and-forget: Fehler werden geschluckt.

    Nutzt die API-URL oder (Fallback, via nginx-Proxy) die Web-URL. ``True`` bei erfolgreichem POST.
    """
    base = ROOKHUB_API_URL or ROOKHUB_WEB_URL
    if not base:
        return False
    try:
        requests.post(f'{base}/api/client-log',
                      json={'kind': 'heartbeat_bot', 'detail': 'alive', 'url': '/bot'},
                      timeout=timeout)
        return True
    except requests.RequestException as e:
        log.debug('RookHub send_heartbeat fehlgeschlagen: %s', e)
        return False


def get_puzzle(pool: str = 'random', exclude=None, book_id=None, timeout: int = _TIMEOUT) -> dict | None:
    """Holt ein zufälliges Buch-Puzzle aus dem Pool (``daily`` | ``random`` | ``blind``).

    ``book_id`` (RookHub-Buch-ID) überschreibt den Pool-Filter → zufälliges Puzzle aus genau
    diesem Buch. Gibt das BookPuzzleDto als dict zurück oder ``None`` (kein Puzzle / Fehler).
    """
    if not ROOKHUB_API_URL:
        log.warning('ROOKHUB_API_URL nicht gesetzt – kann kein Puzzle von RookHub holen.')
        return None
    params = {'pool': pool}
    if exclude:
        params['exclude'] = ','.join(str(e) for e in exclude)
    if book_id:
        params['bookId'] = book_id
    try:
        r = requests.get(_api('/api/book-puzzles/random'), params=params, timeout=timeout)
        if r.status_code == 404:
            log.info('RookHub: kein Puzzle im Pool "%s" (bookId=%s).', pool, book_id)
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        log.warning('RookHub get_puzzle(%s) fehlgeschlagen: %s', pool, e)
        return None


def get_books(timeout: int = _TIMEOUT) -> list:
    """Liste der Puzzle-Bücher von RookHub: Einträge mit ``bookId``, ``bookFileName``,
    ``difficulty``, ``bookRating``, ``tags``, ``puzzleCount``. Leere Liste bei Fehler.
    """
    if not ROOKHUB_API_URL:
        log.warning('ROOKHUB_API_URL nicht gesetzt – kann keine Bücher von RookHub holen.')
        return []
    try:
        r = requests.get(_api('/api/book-puzzles/books'), timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except (requests.RequestException, ValueError) as e:
        log.warning('RookHub get_books fehlgeschlagen: %s', e)
        return []


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


def get_daily_results(puzzle_id, since: str | None = None, timeout: int = _TIMEOUT) -> dict | None:
    """Holt die Solver-Ergebnisse eines Buch-Puzzles (Tagespuzzle) von RookHub.

    Rückgabe: dict ``{solvedCount, attemptCount, solvers:[{name, discordId?, discordUsername?}]}``
    oder ``None`` (Fehler / API-URL fehlt).
    """
    if not ROOKHUB_API_URL or not puzzle_id:
        return None
    params = {}
    if since:
        params['since'] = since
    try:
        r = requests.get(_api(f'/api/book-puzzles/{puzzle_id}/results'), params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        log.debug('get_daily_results(%s) fehlgeschlagen: %s', puzzle_id, e)
        return None


def get_player_progress(discord_id, timeout: int = _TIMEOUT) -> dict | None:
    """Holt den Trainings-/Puzzle-Fortschritt eines mit RookHub verknuepften Spielers.

    Authentifiziert ueber eine HMAC-Signatur (``X-Bot-Signature: sha256=<hex>``) ueber die Discord-ID
    mit dem geteilten ``ROOKHUB_STATS_SECRET`` (== RookHubs ``SchachBot__StatsSecret``).

    Rueckgabe: ``BotPlayerProgressDto`` als dict (``username``, ``displayName``, ``today`` mit
    ``goal``/``puzzles``/``book``/``play``/``status``/``weekDaysMet``/``weeklyDaysTarget``, ``puzzles``-Stats)
    — oder ``None``, wenn der Spieler NICHT verknuepft ist (404), das Feature/Secret fehlt oder ein
    Fehler auftritt. ``None`` heisst fuer den Aufrufer: keine Motivation, stattdessen Verknuepfungs-Hinweis.
    """
    if not ROOKHUB_API_URL or not ROOKHUB_STATS_SECRET or discord_id is None:
        return None
    did = str(discord_id)
    sig = hmac.new(ROOKHUB_STATS_SECRET.encode('utf-8'), did.encode('utf-8'),
                   hashlib.sha256).hexdigest()
    try:
        r = requests.get(_api(f'/api/bot/player-progress/{did}'),
                         headers={'X-Bot-Signature': f'sha256={sig}'}, timeout=timeout)
        if r.status_code == 404:
            # Nicht verknuepft (oder Feature serverseitig aus) → kein Fortschritt.
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        log.warning('RookHub get_player_progress(%s) fehlgeschlagen: %s', did, e)
        return None


def get_weekly_posts(timeout: int = _TIMEOUT) -> list | None:
    """Liste der Wochenposts von RookHub (`GET /api/weekly-posts`).

    Jeder Eintrag: ``id``, ``title``, ``fileName``, ``fileSize``, ``scheduledAt`` (ISO), ``createdAt``,
    ``updatedAt`` — absteigend nach ``scheduledAt``. ``None`` bei Fehler / fehlender API-URL.
    """
    if not ROOKHUB_API_URL:
        log.warning('ROOKHUB_API_URL nicht gesetzt – kann keine Wochenposts holen.')
        return None
    try:
        r = requests.get(_api('/api/weekly-posts'), timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except (requests.RequestException, ValueError) as e:
        log.warning('RookHub get_weekly_posts fehlgeschlagen: %s', e)
        return None


def weekly_web_url(weekly_id: int | None) -> str | None:
    """Anklickbare RookHub-URL zum Durchspielen eines Wochenposts — `…/weekly/{id}`.

    Nutzt strikt ROOKHUB_WEB_URL (sonst kein Link, damit keine internen Adressen nach Discord gelangen).
    """
    if weekly_id is None or not ROOKHUB_WEB_URL:
        return None
    return f'{ROOKHUB_WEB_URL}/weekly/{weekly_id}'


def puzzle_web_url(puzzle_id: int | None) -> str | None:
    """Baut die anklickbare RookHub-URL zum interaktiven Lösen.

    Nutzt strikt ROOKHUB_WEB_URL — kein Fallback auf ROOKHUB_API_URL, sonst
    landen interne Docker-Adressen (z. B. http://10.24.13.6:8087) in
    User-Posts auf Discord. Wenn WEB_URL nicht konfiguriert ist: kein Link.
    """
    if puzzle_id is None or not ROOKHUB_WEB_URL:
        return None
    return f'{ROOKHUB_WEB_URL}/puzzles/book/{puzzle_id}'


def daily_web_url(date_str: str | None = None) -> str | None:
    """RookHub-Link zum Tagespuzzle eines Datums — `…/puzzles/daily/{yyyyMMdd}`.

    Default = heutiges UTC-Datum (entspricht der serverseitigen Daily-Zuordnung).
    Stabil/teilbar: dieselbe Datums-URL zeigt immer dasselbe Tagespuzzle, unabhängig
    von der Puzzle-ID. Ohne ROOKHUB_WEB_URL: kein Link.
    """
    if not ROOKHUB_WEB_URL:
        return None
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
    return f'{ROOKHUB_WEB_URL}/puzzles/daily/{date_str}'


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
