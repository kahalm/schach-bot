"""Puzzle-Auswahl: Linien laden, cachen, filtern, zufaellig/sequentiell waehlen."""

import io
import os
import pickle
import random
import logging

import chess
import chess.pgn

from puzzle.state import (
    BOOKS_DIR,
    _load_books_config, _invalidate_books_config_cache,
    _load_ignore_list, _invalidate_ignore_cache,
    _load_chapter_ignore_list, _invalidate_chapter_ignore_cache,
    _is_chapter_ignored,
    load_puzzle_state, save_puzzle_state,
)
from puzzle.processing import _flatten_null_move_variations, _has_training_comment, _split_for_blind
from core.paths import CONFIG_DIR
from core.json_store import _lock_for

log = logging.getLogger('schach-bot')

# ---------------------------------------------------------------------------
# Chapter-Helpers (brauchen load_all_lines)
# ---------------------------------------------------------------------------

def _find_chapter_prefix(book_filename: str, chapter: int) -> str | None:
    """Findet das tatsächliche Chapter-Präfix-Format (z.B. '003' vs '3') anhand
    existierender Linien im Buch."""
    for lid, _ in load_all_lines():
        if not lid.startswith(book_filename + ':'):
            continue
        round_part = lid.split(':', 1)[1]
        if '.' not in round_part:
            continue
        chap_str = round_part.split('.', 1)[0]
        try:
            if int(chap_str) == chapter:
                return chap_str
        except ValueError:
            continue
    return None


def _list_chapters(book_filename: str) -> dict[str, int]:
    """Gibt alle Kapitel-Präfixe eines Buchs mit Anzahl Linien zurück."""
    counts: dict[str, int] = {}
    for lid, _ in load_all_lines():
        if not lid.startswith(book_filename + ':'):
            continue
        round_part = lid.split(':', 1)[1]
        if '.' not in round_part:
            continue
        chap = round_part.split('.', 1)[0]
        counts[chap] = counts.get(chap, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# PGN-Datei-Listing
# ---------------------------------------------------------------------------

def _list_pgn_files() -> list[str]:
    """Gibt sortierte Liste aller PGN-Dateien im Books-Verzeichnis zurück."""
    if not os.path.isdir(BOOKS_DIR):
        return []
    return sorted(f for f in os.listdir(BOOKS_DIR) if f.endswith('.pgn'))


# ---------------------------------------------------------------------------
# Linien-Cache
# ---------------------------------------------------------------------------

_FATAL_STATUS = (
    chess.STATUS_NO_WHITE_KING
    | chess.STATUS_NO_BLACK_KING
    | chess.STATUS_TOO_MANY_KINGS
    | chess.STATUS_PAWNS_ON_BACKRANK
    | chess.STATUS_OPPOSITE_CHECK
    | chess.STATUS_EMPTY
    | chess.STATUS_TOO_MANY_CHECKERS
)

PUZZLE_CACHE_FILE = os.path.join(CONFIG_DIR, 'puzzle_lines.pkl')

_lines_cache: list[tuple[str, chess.pgn.Game]] | None = None
_lines_cache_fp: tuple | None = None


def _books_fingerprint() -> tuple:
    """(filename, mtime, size) für jede .pgn in BOOKS_DIR + books.json.

    Enthält auch VERSION, damit Code-Änderungen am Parser (z.B.
    _flatten_null_move_variations) den Cache automatisch invalidieren.
    """
    from core.version import VERSION
    items: list = [('__version__', VERSION)]
    if os.path.isdir(BOOKS_DIR):
        for fn in sorted(os.listdir(BOOKS_DIR)):
            if fn.endswith('.pgn') or fn == 'books.json':
                p = os.path.join(BOOKS_DIR, fn)
                try:
                    st = os.stat(p)
                    items.append((fn, st.st_mtime_ns, st.st_size))
                except OSError:
                    pass
    return tuple(items)


def clear_lines_cache() -> None:
    """In-Memory- und Disk-Cache löschen. Nächster ``load_all_lines()`` parst neu."""
    global _lines_cache, _lines_cache_fp
    _lines_cache = None
    _lines_cache_fp = None
    _invalidate_books_config_cache()
    _invalidate_ignore_cache()
    _invalidate_chapter_ignore_cache()
    try:
        os.remove(PUZZLE_CACHE_FILE)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning('Pickle-Cache löschen fehlgeschlagen: %s', e)


def load_all_lines() -> list[tuple[str, chess.pgn.Game]]:
    """Alle Linien aus .pgn-Dateien in BOOKS_DIR laden – gecached."""
    global _lines_cache, _lines_cache_fp

    fp = _books_fingerprint()

    # 1) In-Memory-Cache
    if _lines_cache is not None and _lines_cache_fp == fp:
        return _lines_cache

    # 2) Disk-Cache (nur einmal pro Restart relevant)
    pkl_lock = _lock_for(PUZZLE_CACHE_FILE)
    with pkl_lock:
        if os.path.exists(PUZZLE_CACHE_FILE):
            try:
                with open(PUZZLE_CACHE_FILE, 'rb') as f:
                    blob = pickle.load(f)
                if isinstance(blob, dict) and blob.get('fp') == fp:
                    _lines_cache = blob['lines']
                    _lines_cache_fp = fp
                    log.info('Puzzle-Cache geladen (%d Linien aus %s)',
                             len(_lines_cache), PUZZLE_CACHE_FILE)
                    return _lines_cache
            except Exception as e:
                log.warning('Puzzle-Cache nicht ladbar (%s) – parse neu.', e)

    # 3) Volles Re-Parse
    lines = _parse_all_lines()

    _lines_cache = lines
    _lines_cache_fp = fp
    with pkl_lock:
        try:
            os.makedirs(os.path.dirname(PUZZLE_CACHE_FILE), exist_ok=True)
            with open(PUZZLE_CACHE_FILE, 'wb') as f:
                pickle.dump({'fp': fp, 'lines': lines}, f, protocol=pickle.HIGHEST_PROTOCOL)
            log.info('Puzzle-Cache geschrieben (%d Linien → %s)',
                     len(lines), PUZZLE_CACHE_FILE)
        except Exception as e:
            log.warning('Puzzle-Cache schreiben fehlgeschlagen: %s', e)

    return lines


def _parse_all_lines() -> list[tuple[str, chess.pgn.Game]]:
    """Tatsächlicher Parser; immer alle PGNs neu lesen + filtern."""
    lines: list[tuple[str, chess.pgn.Game]] = []
    if not os.path.isdir(BOOKS_DIR):
        log.error('Books-Verzeichnis nicht gefunden: %s', BOOKS_DIR)
        return lines
    invalid_count = 0
    for filename in sorted(os.listdir(BOOKS_DIR)):
        if not filename.endswith('.pgn'):
            continue
        filepath = os.path.join(BOOKS_DIR, filename)
        try:
            with open(filepath, encoding='utf-8', errors='replace') as f:
                pgn_text = f.read()
        except OSError as e:
            log.error('Kann PGN-Datei nicht lesen: %s – %s', filepath, e)
            continue
        pgn_text = _flatten_null_move_variations(pgn_text)
        stream = io.StringIO(pgn_text)
        consecutive_errors = 0
        _MAX_CONSECUTIVE_ERRORS = 50
        while True:
            try:
                game = chess.pgn.read_game(stream)
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                log.debug('Malformierter PGN-Eintrag in %s: %s', filename, e)
                if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    log.warning('Zu viele aufeinanderfolgende Parse-Fehler in %s, abgebrochen.', filename)
                    break
                continue
            if game is None:
                break
            if 'FEN' in game.headers and not game.headers['FEN'].strip():
                continue
            if not game.variations or game.variations[0].move == chess.Move.null():
                continue
            try:
                root_board = game.board()
            except Exception as e:
                log.debug('Board-Setup fehlgeschlagen in %s (%s): %s',
                          filename, game.headers.get('Round', ''), e)
                invalid_count += 1
                continue
            status = root_board.status()
            if status & _FATAL_STATUS:
                round_header = game.headers.get('Round', '')
                log.debug('Illegale Stellung übersprungen in %s:%s – status=%d',
                          filename, round_header, status)
                invalid_count += 1
                continue
            round_header = game.headers.get('Round', '')
            line_id = f"{filename}:{round_header}"
            lines.append((line_id, game))
    if invalid_count:
        log.info('%d illegale Stellungen aus dem Pool ausgeschlossen.', invalid_count)
    return lines


# ---------------------------------------------------------------------------
# Auswahl-Funktionen
# ---------------------------------------------------------------------------

def pick_sequential_lines(book_filename: str, start: int, count: int
                          ) -> list[tuple[str, chess.pgn.Game]]:
    """Gibt bis zu `count` Linien ab Position `start` zurück (sequentiell)."""
    all_lines = load_all_lines()
    ignored = _load_ignore_list()
    chapter_ignored = _load_chapter_ignore_list()
    book_lines = [(lid, g) for lid, g in all_lines
                  if lid.startswith(book_filename + ':')
                  and lid not in ignored
                  and not _is_chapter_ignored(lid, chapter_ignored)]
    end = min(start + count, len(book_lines))
    return book_lines[start:end]


def get_random_books() -> list[str]:
    """Liefert Liste der für Zufalls-/Daily-Auswahl freigegebenen Bücher."""
    config = _load_books_config()
    return [fn for fn, meta in config.items() if meta.get('random', True)]


def pick_random_lines(count: int = 1,
                      book_filename: str | None = None,
                      ) -> list[tuple[str, chess.pgn.Game]]:
    """Bis zu `count` zufällige noch nicht gepostete Linien wählen."""
    all_lines = load_all_lines()
    ignored = _load_ignore_list()
    chapter_ignored = _load_chapter_ignore_list()
    if book_filename:
        all_lines = [(lid, g) for lid, g in all_lines
                     if lid.startswith(book_filename + ':')]
    else:
        random_books = set(get_random_books())
        all_lines = [(lid, g) for lid, g in all_lines
                     if lid.split(':')[0] in random_books]
    all_lines = [(lid, g) for lid, g in all_lines
                 if lid not in ignored
                 and not _is_chapter_ignored(lid, chapter_ignored)]
    all_lines = [(lid, g) for lid, g in all_lines if _has_training_comment(g)]
    if not all_lines:
        return []

    state  = load_puzzle_state()
    posted = set(state.get('posted', []))

    remaining = [(lid, g) for lid, g in all_lines if lid not in posted]
    if not remaining:
        posted    = set()
        remaining = all_lines
        log.info('Alle Linien gepostet – starte von vorne.')

    count  = max(1, min(count, len(remaining)))
    chosen = random.sample(remaining, count)
    for lid, _ in chosen:
        posted.add(lid)
    save_puzzle_state({'posted': list(posted)})
    return chosen


def pick_random_line() -> tuple[str, chess.pgn.Game] | None:
    """Kompatibilitäts-Wrapper – wählt genau eine Linie."""
    result = pick_random_lines(1)
    return result[0] if result else None


def find_line_by_id(line_id: str) -> tuple[str, chess.pgn.Game] | None:
    """Sucht eine Linie anhand ihrer line_id (exakt oder Suffix-Match)."""
    line_id = line_id.strip()
    if len(line_id) > 200:
        return None
    if line_id.lower().startswith('id:'):
        line_id = line_id[3:].lstrip()
    all_lines = load_all_lines()
    for lid, game in all_lines:
        if lid == line_id:
            return (lid, game)
    for lid, game in all_lines:
        if lid.endswith(':' + line_id):
            return (lid, game)
    return None


def get_blind_books() -> list[str]:
    """Liefert Liste der für Blind-Modus freigegebenen Buch-Dateinamen."""
    config = _load_books_config()
    return [fn for fn, meta in config.items() if meta.get('blind')]


def pick_random_blind_lines(count: int,
                            book_filename: str | None,
                            x_moves: int,
                            ) -> list[tuple[str, chess.pgn.Game]]:
    """Wählt zufällige Linien aus Blind-Büchern mit ≥ x_moves Vorlauf."""
    config = _load_books_config()
    blind_books = {fn for fn, meta in config.items() if meta.get('blind')}
    if book_filename:
        if book_filename not in blind_books:
            return []
        eligible_files = {book_filename}
    else:
        eligible_files = blind_books
    if not eligible_files:
        return []

    all_lines = load_all_lines()
    ignored = _load_ignore_list()
    chapter_ignored = _load_chapter_ignore_list()
    candidates: list[tuple[str, chess.pgn.Game]] = []
    for lid, g in all_lines:
        fn = lid.split(':')[0]
        if fn not in eligible_files:
            continue
        if lid in ignored:
            continue
        if _is_chapter_ignored(lid, chapter_ignored):
            continue
        if _split_for_blind(g, x_moves) is None:
            continue
        candidates.append((lid, g))

    if not candidates:
        return []
    count = max(1, min(count, len(candidates)))
    return random.sample(candidates, count)
