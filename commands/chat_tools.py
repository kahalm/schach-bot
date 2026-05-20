"""Chat-Tools: Anthropic Tool-Use Definitionen + Executor fuer den KI-Chat.

6 Tools die Claude im DM-Chat aufrufen kann:
- list_books, suggest_book, get_training_status (read-only)
- set_training (write)
- send_puzzle, send_next (side-effect)
"""

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
# Dispatcher
# ---------------------------------------------------------------------------

_HANDLERS = {
    'list_books': _tool_list_books,
    'suggest_book': _tool_suggest_book,
    'get_training_status': _tool_get_training_status,
    'set_training': _tool_set_training,
    'send_puzzle': _tool_send_puzzle,
    'send_next': _tool_send_next,
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
