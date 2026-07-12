"""Chat-Tools: Anthropic Tool-Use Definitionen + Executor fuer den KI-Chat.

11 Tools die Claude im DM-Chat aufrufen kann:
- list_books, suggest_book, get_training_status (read-only)
- get_version, get_help, get_release_notes (read-only, Info)
- set_training (write)
- send_puzzle, send_next, send_library_book (side-effect)
- analyze_move (Zuganalyse mit Lichess Cloud-Eval)
"""

import asyncio
import json
import logging

log = logging.getLogger('schach-bot')

# ---------------------------------------------------------------------------
# Tool-Schema-Definitionen (Anthropic-Format)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        'name': 'list_books',
        'description': (
            'Listet alle verfuegbaren Puzzle-Buecher mit Metadaten auf: '
            'Nummer, Name, Schwierigkeit, Bewertung, Anzahl Linien, Tags, Beschreibung.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': [],
        },
    },
    {
        'name': 'suggest_book',
        'description': (
            'Schlaegt Puzzle-Buecher vor basierend auf Schwierigkeit, Thema oder Suchbegriff. '
            'Durchsucht sowohl Puzzle-Buecher als auch die Schachbuch-Bibliothek.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'difficulty': {
                    'type': 'string',
                    'description': 'Schwierigkeitsgrad: Anfaenger, Fortgeschritten oder Meister',
                    'enum': ['Anfaenger', 'Fortgeschritten', 'Meister'],
                },
                'query': {
                    'type': 'string',
                    'description': 'Suchbegriff fuer Thema, Tag oder Buchtitel (z.B. "Taktik", "Endspiel")',
                },
            },
            'required': [],
        },
    },
    {
        'name': 'get_training_status',
        'description': (
            'Zeigt den Trainingsfortschritt des Users: aktives Buch, Position, '
            'Gesamtlinien und Tages-Puzzle-Statistik.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {},
            'required': [],
        },
    },
    {
        'name': 'set_training',
        'description': (
            'Setzt oder aendert das Trainingsbuch des Users. '
            'buch=0 beendet das aktive Training. '
            'buch=1..N waehlt das Buch mit dieser Nummer (aus list_books).'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'buch': {
                    'type': 'integer',
                    'description': 'Buchnummer (1-basiert). 0 = Training beenden.',
                },
            },
            'required': ['buch'],
        },
    },
    {
        'name': 'send_puzzle',
        'description': (
            'Sendet zufaellige Puzzles per DM an den User. '
            'Optional aus einem bestimmten Buch.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'count': {
                    'type': 'integer',
                    'description': 'Anzahl Puzzles (1-20, Standard: 1)',
                    'default': 1,
                },
                'buch': {
                    'type': 'integer',
                    'description': 'Buchnummer (1-basiert, 0 = alle Buecher)',
                    'default': 0,
                },
            },
            'required': [],
        },
    },
    {
        'name': 'send_next',
        'description': (
            'Sendet die naechsten Puzzles aus dem aktiven Trainingsbuch per DM. '
            'Der User muss vorher mit set_training ein Buch gewaehlt haben.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'count': {
                    'type': 'integer',
                    'description': 'Anzahl Linien (1-20, Standard: 1)',
                    'default': 1,
                },
            },
            'required': [],
        },
    },
    {
        'name': 'analyze_move',
        'description': (
            'Analysiert einen Schachzug im Puzzle-Kontext. '
            'Prueft ob er korrekt ist und holt bei falschen Zuegen '
            'eine Engine-Bewertung. Gibt bei falschen Zuegen '
            'fen_after_response zurueck fuer Folgezug-Analyse.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'move': {
                    'type': 'string',
                    'description': 'Zug in SAN oder UCI',
                },
                'fen': {
                    'type': 'string',
                    'description': 'Optionaler FEN-Override',
                },
            },
            'required': ['move'],
        },
    },
    {
        'name': 'get_version',
        'description': 'Gibt Bot-Version, Git-SHA und Uptime/Startzeit zurueck.',
        'input_schema': {'type': 'object', 'properties': {}, 'required': []},
    },
    {
        'name': 'get_help',
        'description': (
            'Zeigt verfuegbare Slash-Commands. '
            'Optional nach Bereich filtern: puzzle, bibliothek, community, info.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'bereich': {
                    'type': 'string',
                    'description': 'Optionaler Bereich: puzzle, bibliothek, community, info',
                },
            },
            'required': [],
        },
    },
    {
        'name': 'get_release_notes',
        'description': 'Zeigt die letzten Aenderungen/Release-Notes aus dem Changelog.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'version': {
                    'type': 'string',
                    'description': 'Optionale bestimmte Version (z.B. "2.34.0")',
                },
                'anzahl': {
                    'type': 'integer',
                    'description': 'Anzahl Versionen (1-10, Standard: 3)',
                },
            },
            'required': [],
        },
    },
    {
        'name': 'send_library_book',
        'description': (
            'Sucht ein Buch in der Schachbuch-Bibliothek und sendet es per DM. '
            'Findet Buecher nach Titel, Autor oder Suchbegriff. '
            'Bei mehreren Formaten (PDF/EPUB/DJVU) wird das bevorzugte gesendet.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'description': 'Suchbegriff (Titel, Autor oder Thema)',
                },
                'format': {
                    'type': 'string',
                    'description': 'Bevorzugtes Format: pdf, epub, djvu (Standard: pdf)',
                    'enum': ['pdf', 'epub', 'djvu'],
                },
            },
            'required': ['query'],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool-Handler
# ---------------------------------------------------------------------------

async def _tool_list_books(tool_input, ctx) -> str:
    from puzzle.selection import _list_pgn_files, load_all_lines
    from puzzle.state import _load_books_config
    from puzzle.processing import _clean_book_name

    books = _list_pgn_files()
    config = _load_books_config()
    all_lines = load_all_lines()

    # Linien pro Buch zaehlen
    lines_per_book = {}
    for lid, _ in all_lines:
        book_fn = lid.split(':')[0]
        lines_per_book[book_fn] = lines_per_book.get(book_fn, 0) + 1

    result = []
    for i, fn in enumerate(books, 1):
        meta = config.get(fn, {})
        entry = {
            'nummer': i,
            'name': _clean_book_name(fn),
            'difficulty': meta.get('difficulty', ''),
            'rating': meta.get('rating', 0),
            'linien': lines_per_book.get(fn, 0),
            'blind': meta.get('blind', False),
            'random_pool': meta.get('random', True),
        }
        if meta.get('tags'):
            entry['tags'] = meta['tags']
        if meta.get('description'):
            entry['description'] = meta['description']
        result.append(entry)

    return json.dumps(result, ensure_ascii=False)


async def _tool_suggest_book(tool_input, ctx) -> str:
    from puzzle.state import _load_books_config
    from puzzle.selection import _list_pgn_files
    from puzzle.processing import _clean_book_name

    config = _load_books_config()
    books = _list_pgn_files()
    difficulty = tool_input.get('difficulty', '')
    query = tool_input.get('query', '').lower()

    # Puzzle-Buecher filtern
    matches = []
    for i, fn in enumerate(books, 1):
        meta = config.get(fn, {})
        name = _clean_book_name(fn)
        # Schwierigkeitsfilter
        if difficulty and meta.get('difficulty', '') != difficulty:
            continue
        # Suchbegriff in Name, Tags oder Description
        if query:
            searchable = f"{name} {' '.join(meta.get('tags', []))} {meta.get('description', '')}".lower()
            if query not in searchable:
                continue
        matches.append({
            'nummer': i,
            'name': name,
            'difficulty': meta.get('difficulty', ''),
            'rating': meta.get('rating', 0),
            'tags': meta.get('tags', []),
            'description': meta.get('description', ''),
        })

    # Bibliothek durchsuchen (falls query vorhanden)
    library_results = []
    if query:
        try:
            from library import _search_library
            lib_hits = _search_library(query, limit=5)
            for e in lib_hits:
                author = e.get('author', '')
                if isinstance(author, list):
                    author = ', '.join(author)
                library_results.append({
                    'title': e.get('title', ''),
                    'author': author,
                    'tags': e.get('tags', []),
                    'type': 'bibliothek',
                })
        except Exception:
            pass  # Bibliothek nicht verfuegbar

    result = {'puzzle_buecher': matches}
    if library_results:
        result['bibliothek'] = library_results

    return json.dumps(result, ensure_ascii=False)


async def _tool_get_training_status(tool_input, ctx) -> str:
    from puzzle.state import _get_user_training, _get_user_puzzle_count
    from puzzle.selection import load_all_lines, _list_pgn_files
    from puzzle.processing import _clean_book_name

    user_id = ctx['user_id']
    training = _get_user_training(user_id)
    today_count, total_count = _get_user_puzzle_count(user_id)

    result = {
        'puzzles_heute': today_count,
        'puzzles_gesamt': total_count,
    }

    if training:
        book_fn = training['book']
        pos = training['position']
        all_lines = load_all_lines()
        total = sum(1 for lid, _ in all_lines if lid.startswith(book_fn + ':'))
        books = _list_pgn_files()
        kurs_nr = books.index(book_fn) + 1 if book_fn in books else 0
        result['training'] = {
            'buch': _clean_book_name(book_fn),
            'buch_nummer': kurs_nr,
            'position': pos,
            'total': total,
            'fortschritt_prozent': (pos * 100 // total) if total else 0,
        }
    else:
        result['training'] = None

    return json.dumps(result, ensure_ascii=False)


async def _tool_set_training(tool_input, ctx) -> str:
    from puzzle.selection import _list_pgn_files
    from puzzle.state import _set_user_training, _clear_user_training, _get_user_training
    from puzzle.processing import _clean_book_name

    user_id = ctx['user_id']
    buch = tool_input.get('buch', 0)

    if buch == 0:
        _clear_user_training(user_id)
        return json.dumps({'status': 'Training beendet.'}, ensure_ascii=False)

    books = _list_pgn_files()
    if not books:
        return json.dumps({'error': 'Keine Buecher gefunden.'}, ensure_ascii=False)

    if buch < 1 or buch > len(books):
        return json.dumps(
            {'error': f'Buch {buch} nicht gefunden. Gueltig: 1-{len(books)}.'},
            ensure_ascii=False)

    book_fn = books[buch - 1]
    # Position beibehalten falls selbes Buch
    training = _get_user_training(user_id)
    if training and training.get('book') == book_fn:
        pos = training['position']
    else:
        pos = 0

    _set_user_training(user_id, book_fn, pos)
    name = _clean_book_name(book_fn)
    return json.dumps(
        {'status': f'Training auf "{name}" (Nr. {buch}) gesetzt, Position {pos}.'},
        ensure_ascii=False)


async def _tool_send_puzzle(tool_input, ctx) -> str:
    from puzzle.posting import post_puzzle

    channel = ctx.get('channel')
    if not channel:
        return json.dumps({'error': 'Kein DM-Channel verfuegbar.'}, ensure_ascii=False)

    count = max(1, min(tool_input.get('count', 1), 20))
    buch = tool_input.get('buch', 0)
    user_id = ctx['user_id']

    sent = await post_puzzle(channel, count=count, book_idx=buch, user_id=user_id)
    return json.dumps({'gesendet': sent, 'angefragt': count}, ensure_ascii=False)


async def _tool_send_next(tool_input, ctx) -> str:
    from puzzle.commands import send_next_training

    channel = ctx.get('channel')
    if not channel:
        return json.dumps({'error': 'Kein DM-Channel verfuegbar.'}, ensure_ascii=False)

    count = max(1, min(tool_input.get('count', 1), 20))
    user_id = ctx['user_id']

    result = await send_next_training(channel, user_id, count)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# analyze_move: Zuganalyse mit Lichess Cloud-Eval
# ---------------------------------------------------------------------------

def _fetch_cloud_eval(fen: str) -> dict | None:
    """Holt Stockfish-Bewertung von Lichess Cloud-Eval API.

    Gibt dict mit 'depth', 'pvs' bei Erfolg, None bei 404/Fehler.
    """
    import requests
    from puzzle.lichess import LICHESS_API_TIMEOUT

    try:
        resp = requests.get(
            'https://lichess.org/api/cloud-eval',
            params={'fen': fen, 'multiPv': 1},
            timeout=LICHESS_API_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json()
        log.debug('Cloud-Eval %d fuer FEN %s', resp.status_code, fen)
        return None
    except Exception as e:
        log.debug('Cloud-Eval Fehler fuer FEN %s: %s', fen, e)
        return None


def _uci_line_to_san(fen: str, uci_moves_str: str) -> list[str]:
    """Konvertiert eine UCI-Zugfolge in SAN-Notation.

    >>> _uci_line_to_san('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1', 'e7e5 g1f3')
    ['e5', 'Nf3']
    """
    import chess
    board = chess.Board(fen)
    san_moves = []
    for uci_str in uci_moves_str.strip().split():
        try:
            move = chess.Move.from_uci(uci_str)
        except (chess.InvalidMoveError, ValueError):
            log.debug('Ungueltiger UCI-Zug: %r', uci_str)
            break
        if move not in board.legal_moves:
            log.debug('Illegaler UCI-Zug: %r in FEN %s', uci_str, board.fen())
            break
        san_moves.append(board.san(move))
        board.push(move)
    return san_moves


_GERMAN_PIECES = {'D': 'Q', 'S': 'N', 'T': 'R', 'L': 'B'}


def _normalize_move(move_str: str) -> str:
    """Normalisiert Zug-Eingabe: deutsche Figurenbuchstaben + Annotationen.

    D→Q, S→N, T→R, L→B. Trailing +, #, !, ? werden entfernt.
    """
    s = move_str.strip().rstrip('+#!?')
    if s and s[0] in _GERMAN_PIECES:
        s = _GERMAN_PIECES[s[0]] + s[1:]
    return s


def _parse_first_solution_move(fen: str, solution: str):
    """Extrahiert den ersten Zug aus dem Loesungs-PGN.

    Versucht zuerst PGN-Parser, dann Fallback auf direktes SAN-Parsing.
    Gibt chess.Move oder None zurueck.
    """
    import chess
    import io
    import chess.pgn
    import re

    # Methode 1: PGN-Parser
    try:
        pgn_str = f'[FEN "{fen}"]\n\n{solution}'
        game = chess.pgn.read_game(io.StringIO(pgn_str))
        if game and game.variations:
            return game.variations[0].move
    except Exception as e:
        log.debug('Solution PGN-Parse fehlgeschlagen: %s (solution=%r)', e, solution[:80])

    # Methode 2: Fallback — ersten gueltigen SAN-Token direkt parsen
    board = chess.Board(fen)
    for token in re.findall(r'[A-Za-z][A-Za-z0-9+#=x-]*', solution):
        if token in ('vs', 'KQkq', 'KQ', 'kq'):
            continue
        try:
            return board.parse_san(token)
        except (chess.InvalidMoveError, chess.IllegalMoveError,
                chess.AmbiguousMoveError, ValueError):
            continue

    log.warning('Kein gueltiger Zug in Loesung gefunden: %r (fen=%s)', solution[:80], fen)
    return None


def _is_followup_position(puzzle_fen: str | None, override_fen: str) -> bool:
    """Plausibilitaetscheck: Stammt ``override_fen`` aus der Puzzle-Stellung ab?

    Erlaubt nur Stellungen, die echte Folgestellungen sein KOENNEN — kein
    vollwertiger Beweis (keine Pfadsuche), aber ein billiger Filter gegen frei
    uebergebene Fremd-Stellungen: je Figurentyp+Farbe darf die Override-Stellung
    nicht MEHR Figuren haben als die Puzzle-Stellung (Material nimmt im Spiel nur
    ab — abgesehen von Umwandlung, die durch das Gesamt-Material-Limit gedeckt
    ist), und die Zugzahl darf nicht VOR dem Puzzle-Start liegen.
    """
    import chess
    if not puzzle_fen:
        return False
    try:
        base = chess.Board(puzzle_fen)
        cand = chess.Board(override_fen)
    except ValueError:
        return False

    # Material je (Farbe, Typ) darf nicht zunehmen.
    for color in (chess.WHITE, chess.BLACK):
        for ptype in (chess.PAWN, chess.KNIGHT, chess.BISHOP,
                      chess.ROOK, chess.QUEEN, chess.KING):
            if (len(cand.pieces(ptype, color))
                    > len(base.pieces(ptype, color))):
                return False
    # Gesamt-Figurenzahl darf nicht steigen (faengt Umwandlungs-Tricks ab).
    if chess.popcount(cand.occupied) > chess.popcount(base.occupied):
        return False
    # Zugzahl darf nicht vor dem Puzzle-Start liegen.
    if cand.fullmove_number < base.fullmove_number:
        return False
    return True


def _analyze_move_sync(move_str: str, user_id: int, fen_override: str | None = None) -> dict:
    """Sync-Kernlogik: Zug parsen, gegen Loesung pruefen, Cloud-Eval holen."""
    import chess

    from puzzle.state import get_puzzle_context

    # Aktives Puzzle ist Pflicht — auch bei fen_override (Folge-Stellung). So kann der
    # Bot nicht fuer beliebige, frei uebergebene Stellungen eine Cloud-Eval ausloesen.
    ctx = get_puzzle_context(user_id)
    if not ctx:
        return {'error': 'Kein aktives Puzzle vorhanden.'}

    if fen_override:
        # fen_override soll NUR eine Folge-Stellung des aktiven Puzzles sein
        # (Folgezug-Analyse), keine frei waehlbare Stellung — sonst liesse sich
        # der Bot als allgemeiner Engine-Analyse-Dienst missbrauchen (Cloud-Eval
        # fuer beliebige Eroeffnungs-/Partie-Stellungen). Wir erzwingen, dass die
        # uebergebene Stellung plausibel aus der Puzzle-Stellung HERVORGEHT:
        # gleiche/weniger Figuren je Typ+Farbe (Material kann nur ab-, nie zunehmen)
        # und Zugzahl >= Puzzle-Start.
        if not _is_followup_position(ctx.get('fen'), fen_override):
            return {'error': 'fen-Override muss eine Folgestellung des aktiven Puzzles sein.'}
        fen = fen_override
        solution = None
    else:
        fen = ctx.get('fen')
        solution = ctx.get('solution')

    if not fen:
        return {'error': 'Keine FEN-Stellung verfuegbar.'}

    try:
        board = chess.Board(fen)
    except ValueError:
        return {'error': 'Ungueltige FEN-Stellung.'}

    # Normalisierung: deutsche Notation + Annotationen
    normalized = _normalize_move(move_str)

    # Zug parsen: erst SAN (original + normalisiert), dann UCI
    move = None
    for candidate in (move_str.strip(), normalized):
        try:
            move = board.parse_san(candidate)
            break
        except (chess.InvalidMoveError, chess.IllegalMoveError,
                chess.AmbiguousMoveError, ValueError):
            pass

    if move is None:
        try:
            move = chess.Move.from_uci(move_str.strip())
            if move not in board.legal_moves:
                move = None
        except (chess.InvalidMoveError, ValueError):
            move = None

    if move is None:
        return {'error': f'Ungueltiger Zug: {move_str}'}

    user_move_san = board.san(move)

    # Gegen Loesung pruefen
    if solution:
        first_sol_move = _parse_first_solution_move(fen, solution)
        if first_sol_move and move == first_sol_move:
            sol_board = chess.Board(fen)
            result = {'is_correct': True, 'user_move_san': user_move_san,
                      'message': 'Der Zug ist korrekt!'}
            # Gegenzug aus Loesung extrahieren
            try:
                import io
                import chess.pgn
                pgn_str = f'[FEN "{fen}"]\n\n{solution}'
                game = chess.pgn.read_game(io.StringIO(pgn_str))
                if game and game.variations:
                    first_node = game.variations[0]
                    if first_node.variations:
                        reply_move = first_node.variations[0].move
                        sol_board.push(first_sol_move)
                        result['opponent_reply_san'] = sol_board.san(reply_move)
            except Exception:
                pass
            return result

    # Falscher Zug → Cloud-Eval nach dem Zug
    board.push(move)
    eval_fen = board.fen()
    cloud = _fetch_cloud_eval(eval_fen)

    result = {'is_correct': False, 'user_move_san': user_move_san}

    if cloud and cloud.get('pvs'):
        pv = cloud['pvs'][0]
        result['depth'] = cloud.get('depth', 0)
        # Eval aus Sicht des Ziehenden (invertieren, da jetzt Gegner dran)
        if 'cp' in pv:
            result['eval_cp'] = -pv['cp']
        elif 'mate' in pv:
            result['eval_mate'] = -pv['mate']
        # Beste Antwort / Linie
        moves_uci = pv.get('moves', '').strip()
        if moves_uci:
            san_line = _uci_line_to_san(eval_fen, moves_uci)
            if san_line:
                result['best_response_san'] = san_line[0]
                result['best_line_san'] = ' '.join(san_line)
                # FEN nach User-Zug + Gegenzug fuer Folgezug-Analyse
                uci_parts = moves_uci.split()
                try:
                    response_move = chess.Move.from_uci(uci_parts[0])
                    board.push(response_move)
                    result['fen_after_response'] = board.fen()
                except (chess.InvalidMoveError, ValueError) as e:
                    log.debug('Cloud-Eval Gegenzug ungueltig: %s', e)

    return result


async def _tool_analyze_move(tool_input, ctx) -> str:
    move_str = tool_input.get('move', '')
    fen_override = tool_input.get('fen')
    user_id = ctx.get('user_id', 0)

    result = await asyncio.to_thread(
        _analyze_move_sync, move_str, user_id, fen_override)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Info-Tools: get_version, get_help, get_release_notes
# ---------------------------------------------------------------------------

async def _tool_get_version(tool_input, ctx) -> str:
    from core.version import VERSION, GIT_SHA, START_TIME
    return json.dumps({
        'version': VERSION,
        'git_sha': GIT_SHA,
        'start_time': START_TIME.isoformat(),
    }, ensure_ascii=False)


async def _tool_get_help(tool_input, ctx) -> str:
    from bot import _help_fields
    bereich = tool_input.get('bereich', '').lower().strip()
    if bereich:
        title, fields = _help_fields(bereich, is_admin=False)
        if not fields:
            return json.dumps({
                'error': f'Unbekannter Bereich: {bereich}',
                'verfuegbar': ['puzzle', 'bibliothek', 'community', 'info'],
            }, ensure_ascii=False)
        return json.dumps({
            'bereich': title,
            'commands': [{'name': name, 'description': value}
                         for name, value in fields],
        }, ensure_ascii=False)
    # Uebersicht aller Bereiche
    bereiche = {}
    for b in ('puzzle', 'bibliothek', 'community', 'info'):
        title, fields = _help_fields(b, is_admin=False)
        bereiche[b] = {
            'titel': title,
            'commands': [name for name, _ in fields],
        }
    return json.dumps(bereiche, ensure_ascii=False)


async def _tool_get_release_notes(tool_input, ctx) -> str:
    from commands.release_notes import _parse_changelog
    entries = _parse_changelog()
    if not entries:
        return json.dumps({'error': 'Kein Changelog gefunden.'}, ensure_ascii=False)
    version = tool_input.get('version', '')
    if version:
        entries = [e for e in entries if e['version'] == version]
        if not entries:
            return json.dumps(
                {'error': f'Version {version} nicht im Changelog.'},
                ensure_ascii=False)
    else:
        anzahl = max(1, min(tool_input.get('anzahl', 3), 10))
        entries = entries[:anzahl]
    return json.dumps(entries, ensure_ascii=False)


# ---------------------------------------------------------------------------
# send_library_book: Buch aus Bibliothek per DM senden
# ---------------------------------------------------------------------------

async def _tool_send_library_book(tool_input, ctx) -> str:
    import asyncio
    import os
    import discord
    from core import stats
    import library as _lib
    from library import (
        _search_library, _collect_formats, _author_str,
        _sftpgo_configured, _sftpgo_message, _sftpgo_password_message, _MAX_UPLOAD,
    )

    channel = ctx.get('channel')
    if not channel:
        return json.dumps({'error': 'Kein DM-Channel verfuegbar.'}, ensure_ascii=False)

    query = tool_input.get('query', '').strip()
    if not query:
        return json.dumps({'error': 'Kein Suchbegriff angegeben.'}, ensure_ascii=False)

    preferred = tool_input.get('format', 'pdf')

    hits = _search_library(query, limit=5)
    if not hits:
        return json.dumps(
            {'error': f'Kein Buch gefunden fuer: {query}'},
            ensure_ascii=False)

    entry = hits[0]
    title = entry.get('title', '')
    author = _author_str(entry.get('author', ''))

    # Gemeinfreiheits-Sperre: gleiche Regel wie /bibliothek (_send_book) —
    # noch nicht freie Bücher werden auch via Chat-Tool nicht ausgeliefert.
    if _lib._is_locked(entry):
        rel = _lib._pd_release(entry)
        return json.dumps(
            {'error': f'Buch ist noch urheberrechtlich geschützt und erst ab '
                      f'{rel.strftime("%d.%m.%Y")} gemeinfrei — nicht teilbar.',
             'title': title},
            ensure_ascii=False)

    formats = _collect_formats(entry)
    if not formats:
        return json.dumps(
            {'error': 'Buch gefunden aber keine Datei verfuegbar', 'title': title},
            ensure_ascii=False)

    # Format waehlen: bevorzugt → Fallback pdf→epub→djvu
    if preferred in formats:
        fmt = preferred
    else:
        for fallback in ('pdf', 'epub', 'djvu'):
            if fallback in formats:
                fmt = fallback
                break
        else:
            fmt = next(iter(formats))

    path = formats[fmt]
    # Disk-/Netz-I/O (Bücher liegen auf Syncthing-/Netzpfaden) NICHT im Event-Loop
    # (wie library._send_book); OSError = Datei zwischenzeitlich verschoben/gelöscht.
    try:
        size = await asyncio.to_thread(os.path.getsize, path)
        size_mb = round(size / (1024 * 1024), 1)

        if size <= _MAX_UPLOAD:
            book_file = await asyncio.to_thread(
                lambda: discord.File(path, filename=os.path.basename(path)))
            await channel.send(
                content=f'📖 **{title}** — {author} `[{fmt.upper()}]`',
                file=book_file)
        elif _sftpgo_configured():
            await channel.send(_sftpgo_message(entry, path, fmt))
            pw_msg = _sftpgo_password_message()
            if pw_msg:
                await channel.send(pw_msg)
        else:
            return json.dumps(
                {'error': f'Datei zu gross ({size_mb} MB, Discord-Limit 8 MB)',
                 'title': title},
                ensure_ascii=False)
    except OSError:
        return json.dumps(
            {'error': 'Datei nicht mehr verfügbar (evtl. zwischenzeitlich '
                      'synchronisiert/verschoben).',
             'title': title},
            ensure_ascii=False)

    user_id = ctx.get('user_id', 0)
    await asyncio.to_thread(stats.inc, user_id, 'downloads')

    return json.dumps(
        {'sent': True, 'title': title, 'author': author,
         'format': fmt, 'size_mb': size_mb},
        ensure_ascii=False)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_HANDLERS = {
    'list_books': _tool_list_books,
    'suggest_book': _tool_suggest_book,
    'get_training_status': _tool_get_training_status,
    'set_training': _tool_set_training,
    'send_puzzle': _tool_send_puzzle,
    'send_next': _tool_send_next,
    'analyze_move': _tool_analyze_move,
    'get_version': _tool_get_version,
    'get_help': _tool_get_help,
    'get_release_notes': _tool_get_release_notes,
    'send_library_book': _tool_send_library_book,
}


async def execute_tool(name: str, tool_input: dict, ctx: dict) -> str:
    """Fuehrt ein Chat-Tool aus und gibt das Ergebnis als String zurueck."""
    handler = _HANDLERS.get(name)
    if not handler:
        return json.dumps({'error': f'Unbekanntes Tool: {name}'}, ensure_ascii=False)
    try:
        return await handler(tool_input, ctx)
    except Exception as e:
        log.exception('Chat-Tool %s fehlgeschlagen', name)
        return json.dumps({'error': f'Tool-Fehler: {e}'}, ensure_ascii=False)
