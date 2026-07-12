"""Puzzle-Auswahl: Linien laden, cachen, filtern, zufaellig/sequentiell waehlen."""

import io
import os
import pickle
import random
import logging
import tempfile
import threading

import chess
import chess.pgn

import core.paths

from puzzle.state import (
    BOOKS_DIR,
    _load_books_config, _invalidate_books_config_cache,
    _load_ignore_list, _invalidate_ignore_cache,
    _load_chapter_ignore_list, _invalidate_chapter_ignore_cache,
    _is_chapter_ignored,
    load_puzzle_state, save_puzzle_state,
)
from puzzle.processing import _flatten_null_move_variations, _has_training_comment
from core.json_store import atomic_update
import puzzle.state as _pzstate  # fuer dynamischen PUZZLE_STATE_FILE-Pfad (Test-Patching)

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

_lines_cache: list[tuple[str, chess.pgn.Game]] | None = None
_lines_cache_fp: tuple | None = None
_lines_lock = threading.Lock()


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


def _lines_cache_file() -> str:
    """Pfad des Pickle-Disk-Caches (CONFIG_DIR zur Laufzeit, testbar)."""
    return os.path.join(core.paths.CONFIG_DIR, 'lines_cache.pkl')


def _load_disk_cache(fp: tuple) -> list[tuple[str, chess.pgn.Game]] | None:
    """Lädt den Pickle-Cache, wenn sein Fingerprint zu `fp` passt — sonst None."""
    try:
        with open(_lines_cache_file(), 'rb') as f:
            payload = pickle.load(f)
        if payload.get('fp') == fp:
            return payload['lines']
    except (FileNotFoundError, OSError, pickle.UnpicklingError,
            EOFError, AttributeError, KeyError, ImportError, IndexError):
        pass
    return None


def _save_disk_cache(fp: tuple, lines: list) -> None:
    """Schreibt den Pickle-Cache atomar (best-effort — Fehler nur loggen)."""
    path = _lines_cache_file()
    try:
        dir_name = os.path.dirname(path) or '.'
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as f:
                pickle.dump({'fp': fp, 'lines': lines}, f,
                            protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        log.warning('Linien-Disk-Cache konnte nicht geschrieben werden: %s', e)


def clear_lines_cache() -> None:
    """In-Memory- UND Disk-Cache löschen. Nächster ``load_all_lines()`` parst neu
    (/reindex muss ein echtes Re-Parse erzwingen)."""
    global _lines_cache, _lines_cache_fp
    with _lines_lock:
        _lines_cache = None
        _lines_cache_fp = None
    try:
        os.remove(_lines_cache_file())
    except OSError:
        pass
    _invalidate_books_config_cache()
    _invalidate_ignore_cache()
    _invalidate_chapter_ignore_cache()


def load_all_lines() -> list[tuple[str, chess.pgn.Game]]:
    """Alle Linien aus .pgn-Dateien in BOOKS_DIR laden – gecached.

    Cache-Hierarchie: In-Memory → Pickle-Disk-Cache (überlebt Neustarts,
    Fingerprint aus Datei-mtimes/-Größen + Bot-VERSION) → volles Re-Parse.
    """
    global _lines_cache, _lines_cache_fp

    fp = _books_fingerprint()

    with _lines_lock:
        # 1) In-Memory-Cache
        if _lines_cache is not None and _lines_cache_fp == fp:
            return _lines_cache

    # 2) Disk-Cache (z.B. nach Bot-Neustart — spart das Multi-MB-PGN-Parsing)
    lines = _load_disk_cache(fp)
    if lines is not None:
        log.info('Puzzle-Linien aus Disk-Cache geladen: %d Linien', len(lines))
    else:
        # 3) Volles Re-Parse (ausserhalb des Locks — kann laenger dauern)
        lines = _parse_all_lines()
        log.info('Puzzle-Linien geparst: %d Linien', len(lines))
        _save_disk_cache(fp, lines)

    with _lines_lock:
        _lines_cache = lines
        _lines_cache_fp = fp

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

def book_training_lines(book_filename: str) -> list[tuple[str, chess.pgn.Game]]:
    """Ignore-/Kapitel-gefilterte Linien eines Buchs.

    Gemeinsame Basis für die sequentielle Auswahl UND die Fortschrittsanzeige —
    Positions-Index und Total müssen auf derselben (gefilterten) Liste beruhen.
    """
    all_lines = load_all_lines()
    ignored = _load_ignore_list()
    chapter_ignored = _load_chapter_ignore_list()
    return [(lid, g) for lid, g in all_lines
            if lid.startswith(book_filename + ':')
            and lid not in ignored
            and not _is_chapter_ignored(lid, chapter_ignored)]


def pick_sequential_lines(book_filename: str, start: int, count: int
                          ) -> list[tuple[str, chess.pgn.Game]]:
    """Gibt bis zu `count` Linien ab Position `start` zurück (sequentiell)."""
    book_lines = book_training_lines(book_filename)
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

    # Laden + Auswahl + Markieren atomar unter dem State-Datei-Lock, damit
    # parallele Aufrufe (Daily-Post + /puzzle) keine Linie doppelt waehlen oder
    # sich gegenseitig ueberschreiben (Lost Update beim posted-Set).
    by_id = dict(all_lines)
    pool_ids = set(by_id)
    chosen_ids: list[str] = []

    def _select(state):
        if not isinstance(state, dict):
            state = {'posted': []}
        posted = set(state.get('posted', []))
        remaining = [lid for lid in by_id if lid not in posted]
        if not remaining:
            # Nur die Linien dieses Pools aus posted entfernen, nicht alles
            posted -= pool_ids
            remaining = list(by_id)
            log.info('Alle Linien im Pool gepostet – starte von vorne (Pool: %d Linien).', len(pool_ids))
        k = max(1, min(count, len(remaining)))
        picked = random.sample(remaining, k)
        posted.update(picked)
        chosen_ids[:] = picked
        state['posted'] = list(posted)
        return state

    atomic_update(_pzstate.PUZZLE_STATE_FILE, _select, default=lambda: {'posted': []})
    return [(lid, by_id[lid]) for lid in chosen_ids]


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
