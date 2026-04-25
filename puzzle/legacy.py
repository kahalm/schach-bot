"""Puzzle-Funktionen: Board-Rendering, Lichess-Upload, PGN-Laden, Slash-Commands."""

import asyncio
import io
import json
from core import stats
import logging
import os
import pickle
import random
import re
import tempfile
import time as _time_mod
from collections import OrderedDict, defaultdict
from datetime import time, date as _date, datetime as _datetime

import chess
import chess.pgn
import discord
import requests
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM

log = logging.getLogger('schach-bot')

from core.json_store import atomic_read, atomic_write, atomic_update
from core.version import EMBED_COLOR
from puzzle.buttons import fresh_view as _fresh_button_view

# Lichess-/Discord-Limits für Truncation
_LICHESS_STUDY_NAME_MAX = 100
_LICHESS_CHAPTER_NAME_MAX = 70
_DISCORD_THREAD_NAME_MAX = 100

# Puzzle-Nachrichten-IDs für Reaction-Tracking (in-memory, reicht da Reactions
# typischerweise kurz nach dem Posten kommen).
# Wert: dict {'line_id': str, 'mode': 'normal'|'blind'}
# OrderedDict mit Cap, damit der Speicher nicht unbegrenzt wächst.
_PUZZLE_MSG_CAP = 500
_puzzle_msg_ids: OrderedDict[int, dict] = OrderedDict()
from core.paths import CONFIG_DIR
IGNORE_FILE = os.path.join(CONFIG_DIR, 'puzzle_ignore.json')
CHAPTER_IGNORE_FILE = os.path.join(CONFIG_DIR, 'chapter_ignore.json')

# Endless-Modus: aktive Sessions (in-memory)
# Jede Session hat 'last_active' — nach 2h Inaktivität wird automatisch aufgeräumt.
_endless_sessions: dict[int, dict] = {}   # user_id → {'book': str|None, 'count': int, 'last_active': float}
_ENDLESS_TIMEOUT_SECS = 7200  # 2 Stunden

def _evict_stale_endless():
    """Entfernt Endless-Sessions, die seit >2h inaktiv sind."""
    now = _time_mod.time()
    stale = [uid for uid, s in _endless_sessions.items()
             if now - s.get('last_active', 0) > _ENDLESS_TIMEOUT_SECS]
    for uid in stale:
        _endless_sessions.pop(uid, None)
    if stale:
        log.info('Endless: %d inaktive Session(s) aufgeräumt.', len(stale))

def _register_puzzle_msg(msg_id: int, line_id: str, mode: str = 'normal'):
    _puzzle_msg_ids[msg_id] = {'line_id': line_id, 'mode': mode}
    while len(_puzzle_msg_ids) > _PUZZLE_MSG_CAP:
        _puzzle_msg_ids.popitem(last=False)

def is_puzzle_message(msg_id: int) -> bool:
    return msg_id in _puzzle_msg_ids

def get_puzzle_line_id(msg_id: int) -> str | None:
    entry = _puzzle_msg_ids.get(msg_id)
    return entry['line_id'] if entry else None

def get_puzzle_mode(msg_id: int) -> str | None:
    """'normal' oder 'blind' — None wenn die Nachricht nicht registriert ist."""
    entry = _puzzle_msg_ids.get(msg_id)
    return entry['mode'] if entry else None

_ignore_cache: set[str] | None = None

def _load_ignore_list() -> set[str]:
    global _ignore_cache
    if _ignore_cache is None:
        _ignore_cache = set(atomic_read(IGNORE_FILE, default=list))
    return _ignore_cache

def _invalidate_ignore_cache():
    global _ignore_cache
    _ignore_cache = None

def ignore_puzzle(line_id: str):
    def _add(data):
        s = set(data)
        s.add(line_id)
        return sorted(s)
    atomic_update(IGNORE_FILE, _add, default=list)
    _invalidate_ignore_cache()

def unignore_puzzle(line_id: str):
    def _remove(data):
        s = set(data)
        s.discard(line_id)
        return sorted(s)
    atomic_update(IGNORE_FILE, _remove, default=list)
    _invalidate_ignore_cache()


_chapter_ignore_cache: set[str] | None = None

def _load_chapter_ignore_list() -> set[str]:
    """Lädt ignorierte Kapitel als Set von '<filename>:<chapter_prefix>'."""
    global _chapter_ignore_cache
    if _chapter_ignore_cache is None:
        _chapter_ignore_cache = set(atomic_read(CHAPTER_IGNORE_FILE, default=list))
    return _chapter_ignore_cache

def _invalidate_chapter_ignore_cache():
    global _chapter_ignore_cache
    _chapter_ignore_cache = None

def _is_chapter_ignored(line_id: str, chapter_ignored: set[str]) -> bool:
    """Prüft, ob die line_id zu einem ignorierten Kapitel gehört.
    Match: '<filename>:<prefix>.' (Punkt nach dem Präfix verhindert False-Positives)."""
    return any(line_id.startswith(prefix + '.') for prefix in chapter_ignored)

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

def ignore_chapter(book_filename: str, chapter_prefix: str):
    entry = f'{book_filename}:{chapter_prefix}'
    def _add(data):
        s = set(data)
        s.add(entry)
        return sorted(s)
    atomic_update(CHAPTER_IGNORE_FILE, _add, default=list)
    _invalidate_chapter_ignore_cache()

def unignore_chapter(book_filename: str, chapter_prefix: str):
    entry = f'{book_filename}:{chapter_prefix}'
    def _remove(data):
        s = set(data)
        s.discard(entry)
        return sorted(s)
    atomic_update(CHAPTER_IGNORE_FILE, _remove, default=list)
    _invalidate_chapter_ignore_cache()

def get_chapter_from_line_id(line_id: str) -> tuple[str, str] | None:
    """Extrahiert (book_filename, chapter_prefix) aus einer line_id, oder None."""
    if ':' not in line_id:
        return None
    fname, _, round_part = line_id.partition(':')
    if '.' not in round_part:
        return None
    return (fname, round_part.split('.', 1)[0])


# --- Endless-Modus ---

def start_endless(user_id: int, book_filename: str | None = None):
    _evict_stale_endless()
    _endless_sessions[user_id] = {'book': book_filename, 'count': 0,
                                  'last_active': _time_mod.time()}

def stop_endless(user_id: int) -> int:
    """Session beenden, gibt Anzahl gelöster Puzzles zurück."""
    session = _endless_sessions.pop(user_id, None)
    return session['count'] if session else 0

def is_endless(user_id: int) -> bool:
    _evict_stale_endless()
    return user_id in _endless_sessions


def _extract_study_id(url: str) -> str | None:
    """Extrahiert die Studien-ID aus einer Lichess-URL."""
    if not url:
        return None
    parts = url.rstrip('/').split('/')
    if 'study' in parts:
        sidx = parts.index('study')
        sid = parts[sidx + 1] if sidx + 1 < len(parts) else ''
        return sid or None
    return None


async def _upload_puzzles_async(
    pairs: list[tuple[chess.pgn.Game, chess.pgn.Game | None]],
    reuse_study_id: str | None = None,
) -> list[str]:
    """Upload-Pairs asynchron in einem Thread-Executor hochladen."""
    loop = asyncio.get_running_loop()
    if len(pairs) == 1:
        u = await loop.run_in_executor(
            None, lambda: upload_to_lichess(
                pairs[0][0], context_game=pairs[0][1],
                reuse_study_id=reuse_study_id))
        return [u] if u else []
    else:
        return await loop.run_in_executor(
            None, lambda: upload_many_to_lichess(
                pairs, reuse_study_id=reuse_study_id))


def _solution_pgn(game: chess.pgn.Game) -> str:
    """Exportiert die Lösung als bereinigten PGN-String (ohne Header, mit Varianten+Kommentaren)."""
    exporter = chess.pgn.StringExporter(headers=False, variations=True, comments=True)
    return _strip_pgn_annotations(game.accept(exporter))


def _clean_book_name(filename: str) -> str:
    """Entfernt PGN-Suffixe aus einem Buch-Dateinamen für die Anzeige."""
    return filename.removesuffix('_firstkey.pgn').removesuffix('.pgn')


def _list_pgn_files() -> list[str]:
    """Gibt sortierte Liste aller PGN-Dateien im Books-Verzeichnis zurück."""
    if not os.path.isdir(BOOKS_DIR):
        return []
    return sorted(f for f in os.listdir(BOOKS_DIR) if f.endswith('.pgn'))


def _export_pgn_for_lichess(game: chess.pgn.Game, headers=True,
                             variations=True, comments=True) -> str:
    """Exportiert ein Game als PGN und bereinigt es für Lichess."""
    exp = chess.pgn.StringExporter(
        headers=headers, variations=variations, comments=comments)
    return _clean_pgn_for_lichess(game.accept(exp))


async def _send_puzzle_followups(target, game: chess.pgn.Game,
                                 context: chess.pgn.Game | None,
                                 puzzle_url: str | None,
                                 line_id: str):
    """Lösung, Prelude und Lichess-Link als optionale Follow-ups senden."""
    pgn_moves = _solution_pgn(game)
    if pgn_moves:
        await _send_optional(target, f'Lösung: ||`{pgn_moves}`||', label=f'Lösung {line_id}')
    if context:
        prelude = _prelude_pgn(context, game)
        if prelude:
            await _send_optional(target, f'Ganze Partie: ||`{prelude}`||', label=f'Partie {line_id}')
    if puzzle_url:
        await _send_optional(target, f'[Klickbares Rätsel]({puzzle_url})', label=f'Lichess-Link {line_id}')


async def post_next_endless(bot, user_id: int):
    """Nächstes Puzzle im Endless-Modus per DM senden."""
    session = _endless_sessions.get(user_id)
    if not session:
        return

    book_filename = session['book']
    results = pick_random_lines(1, book_filename)
    if not results:
        # Keine Puzzles mehr → Session beenden
        try:
            user = await bot.fetch_user(user_id)
            dm = await user.create_dm()
            await dm.send('⚠️ Keine weiteren Puzzles verfügbar. Endless-Modus beendet.')
        except Exception as e:
            log.warning('Endless-Ende-DM fehlgeschlagen (user=%s): %s', user_id, e)
        _endless_sessions.pop(user_id, None)
        return

    line_id, original_game = results[0]
    game = _trim_to_training_position(original_game)
    context = original_game if game is not original_game else None

    books_config = _load_books_config()
    fname = line_id.split(':')[0]
    book_meta = books_config.get(fname, {})
    diff = book_meta.get('difficulty', '')
    rating = book_meta.get('rating', 0)

    # Upload
    reuse_study_id = _get_user_study_id(user_id)
    urls = await _upload_puzzles_async([(game, context)], reuse_study_id=reuse_study_id)
    puzzle_url = urls[0] if urls else None

    # Studie-ID speichern
    sid = _extract_study_id(puzzle_url)
    if sid:
        base_count, base_total = _get_user_puzzle_count(user_id)
        _set_user_study_id(user_id, sid, base_count + 1, base_total + 1)

    session['count'] += 1
    session['last_active'] = _time_mod.time()

    # DM senden
    try:
        user = await bot.fetch_user(user_id)
        dm = await user.create_dm()
    except Exception as e:
        log.warning('Endless-DM fehlgeschlagen (user=%s): %s – Session beendet', user_id, e)
        stop_endless(user_id)
        return

    try:
        board = game.board()
        turn = board.turn
        img = await asyncio.to_thread(_render_board, board)
    except Exception:
        turn, img = None, None

    embed = build_puzzle_embed(game, turn=turn, difficulty=diff, rating=rating, line_id=line_id)
    embed.set_footer(text=f'♾️ Endless-Modus · Puzzle #{session["count"]} · ID: {line_id}')

    if img:
        file = discord.File(img, filename='board.png')
        embed.set_image(url='attachment://board.png')
        msg = await dm.send(file=file, embed=embed)
    else:
        msg = await dm.send(embed=embed)

    _register_puzzle_msg(msg.id, line_id)
    await msg.edit(view=_fresh_button_view())

    # Lösung, Prelude, Lichess-Link
    await _send_puzzle_followups(dm, game, context, puzzle_url, line_id)

    stats.inc(user_id, 'puzzles', 1)


# --- Config (aus Umgebung) ---

LICHESS_API_TIMEOUT = 15  # Sekunden für Lichess-API-Requests
LICHESS_TOKEN     = os.getenv('LICHESS_TOKEN', '')
BOOKS_DIR         = os.getenv('BOOKS_DIR', 'books')
PUZZLE_STUDY_ID   = os.getenv('PUZZLE_STUDY_ID', '')
PUZZLE_HOUR       = int(os.getenv('PUZZLE_HOUR', '9'))
PUZZLE_MINUTE     = int(os.getenv('PUZZLE_MINUTE', '0'))
PUZZLE_STATE_FILE = os.path.join(CONFIG_DIR, 'puzzle_state.json')
USER_STUDIES_FILE = os.path.join(CONFIG_DIR, 'user_studies.json')
LICHESS_COOLDOWN_FILE = os.path.join(CONFIG_DIR, 'lichess_cooldown.json')
CHANNEL_ID        = int(os.getenv('CHANNEL_ID', '0'))

# ---------------------------------------------------------------------------
# Board-Bild (Lichess cburnett-Figuren via SVG-Download)
# ---------------------------------------------------------------------------

_SQ         = 60
_MAR        = 22
_LIGHT      = (240, 217, 181)
_DARK       = (181, 136,  99)
_BORDER_BG  = ( 49,  46,  43)
_LABEL_COL  = (210, 185, 150)

_PIECE_CODES = {
    (chess.KING,   chess.WHITE): 'wK',
    (chess.QUEEN,  chess.WHITE): 'wQ',
    (chess.ROOK,   chess.WHITE): 'wR',
    (chess.BISHOP, chess.WHITE): 'wB',
    (chess.KNIGHT, chess.WHITE): 'wN',
    (chess.PAWN,   chess.WHITE): 'wP',
    (chess.KING,   chess.BLACK): 'bK',
    (chess.QUEEN,  chess.BLACK): 'bQ',
    (chess.ROOK,   chess.BLACK): 'bR',
    (chess.BISHOP, chess.BLACK): 'bB',
    (chess.KNIGHT, chess.BLACK): 'bN',
    (chess.PAWN,   chess.BLACK): 'bP',
}

_piece_cache: dict[str, Image.Image] = {}

def _svg_to_pil(svg_bytes: bytes, size: int) -> Image.Image:
    """SVG-Bytes → PIL RGBA-Bild.
    Doppel-Render (schwarz + weiß) für artefaktfreies Alpha."""
    with tempfile.NamedTemporaryFile(suffix='.svg', mode='wb', delete=False) as f:
        f.write(svg_bytes)
        tmp = f.name
    try:
        drawing = svg2rlg(tmp)
    finally:
        os.unlink(tmp)
    sx = size / drawing.width
    sy = size / drawing.height
    drawing.width  = size
    drawing.height = size
    drawing.transform = (sx, 0, 0, sy, 0, 0)

    def render(bg: int) -> Image.Image:
        buf = io.BytesIO()
        renderPM.drawToFile(drawing, buf, fmt='PNG', bg=bg)
        buf.seek(0)
        return Image.open(buf).convert('RGB')

    img_black = render(0x000000)
    img_white = render(0xFFFFFF)
    # Alpha = 255 - Differenz: transparent wo Hintergrund durchscheint
    alpha = ImageOps.invert(ImageChops.difference(img_white, img_black).convert('L'))
    result = img_black.convert('RGBA')
    result.putalpha(alpha)
    return result

def _get_piece(code: str, size: int) -> Image.Image:
    if code not in _piece_cache:
        url  = f'https://lichess1.org/assets/piece/cburnett/{code}.svg'
        resp = requests.get(url, timeout=LICHESS_API_TIMEOUT)
        resp.raise_for_status()
        _piece_cache[code] = _svg_to_pil(resp.content, size)
        log.info('Figur geladen: %s', code)
    return _piece_cache[code]

def _label_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    _FONT_PATHS = [
        # Windows
        'C:/Windows/Fonts/arialbd.ttf',
        'C:/Windows/Fonts/arial.ttf',
        # Linux (DejaVu, Liberation)
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        # macOS
        '/System/Library/Fonts/Helvetica.ttc',
        '/Library/Fonts/Arial.ttf',
    ]
    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _render_board(board: chess.Board) -> io.BytesIO:
    """PNG einer Stellung mit Lichess-Figuren (cburnett) und Koordinaten."""
    s, m   = _SQ, _MAR
    total  = s * 8 + m * 2
    img    = Image.new('RGB', (total, total), _BORDER_BG)
    draw   = ImageDraw.Draw(img)
    font   = _label_font(m - 5)
    p_size = s - 4  # Figur etwas kleiner als Feld

    for sq in chess.SQUARES:
        f  = chess.square_file(sq)
        r  = chess.square_rank(sq)
        x  = m + f * s
        y  = m + (7 - r) * s
        sq_color = _LIGHT if (f + r) % 2 == 1 else _DARK
        draw.rectangle([x, y, x + s - 1, y + s - 1], fill=sq_color)

        piece = board.piece_at(sq)
        if not piece:
            continue
        code      = _PIECE_CODES[(piece.piece_type, piece.color)]
        piece_img = _get_piece(code, p_size)
        offset    = (s - p_size) // 2
        img.paste(piece_img, (x + offset, y + offset), piece_img)

    # Koordinaten
    for f in range(8):
        lbl = chr(ord('a') + f)
        bb  = draw.textbbox((0, 0), lbl, font=font)
        lw  = bb[2] - bb[0]
        cx  = m + f * s + s // 2
        draw.text((cx - lw // 2, m + 8 * s + 4), lbl, font=font, fill=_LABEL_COL)

    for r in range(8):
        lbl = str(r + 1)
        bb  = draw.textbbox((0, 0), lbl, font=font)
        lh  = bb[3] - bb[1]
        cy  = m + (7 - r) * s + s // 2
        draw.text((5, cy - lh // 2), lbl, font=font, fill=_LABEL_COL)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

# ---------------------------------------------------------------------------
# Bücher & Puzzle
# ---------------------------------------------------------------------------

def load_puzzle_state() -> dict:
    return atomic_read(PUZZLE_STATE_FILE, default=lambda: {'posted': []})


def save_puzzle_state(state: dict):
    atomic_write(PUZZLE_STATE_FILE, state)

def _load_user_studies() -> dict:
    return atomic_read(USER_STUDIES_FILE)

def _save_user_studies(data: dict):
    atomic_write(USER_STUDIES_FILE, data)

def _get_user_study_id(user_id: int) -> str | None:
    entry = _load_user_studies().get(str(user_id))
    if isinstance(entry, dict):
        val = entry.get('id')
    else:
        val = None
    log.info('User-Studie laden: user=%s → %s', user_id, val or 'neu')
    return val

def _get_user_puzzle_count(user_id: int) -> tuple[int, int]:
    """Gibt (heute, gesamt) zurück."""
    entry = _load_user_studies().get(str(user_id))
    if not isinstance(entry, dict):
        return 0, 0
    total = entry.get('total', 0)
    if entry.get('today') == _date.today().isoformat():
        return entry.get('count', 0), total
    return 0, total

def _set_user_study_id(user_id: int, study_id: str, count: int, total: int):
    data = _load_user_studies()
    key = str(user_id)
    prev = data.get(key) if isinstance(data.get(key), dict) else {}
    data[key] = {
        'id':    study_id,
        'today': _date.today().isoformat(),
        'count': count,
        'total': total,
    }
    # Training-State beibehalten
    if 'training' in prev:
        data[key]['training'] = prev['training']
    _save_user_studies(data)
    log.info('User-Studie gespeichert: user=%s study_id=%s count=%d total=%d', user_id, study_id, count, total)

_books_config_cache: dict | None = None

def _load_books_config() -> dict:
    """Lädt books.json mit Metadaten (z.B. difficulty) pro PGN-Datei."""
    global _books_config_cache
    if _books_config_cache is not None:
        return _books_config_cache
    p = os.path.join(BOOKS_DIR, 'books.json')
    try:
        with open(p, encoding='utf-8') as f:
            _books_config_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _books_config_cache = {}
    return _books_config_cache

def _invalidate_books_config_cache():
    global _books_config_cache
    _books_config_cache = None

def _get_user_training(user_id: int) -> dict | None:
    """Gibt {'book': ..., 'position': ...} oder None zurück."""
    entry = _load_user_studies().get(str(user_id))
    if isinstance(entry, dict):
        return entry.get('training')
    return None

def _set_user_training(user_id: int, book: str, position: int):
    """Setzt das Trainingsbuch und die Position für den User."""
    data = _load_user_studies()
    key = str(user_id)
    if key not in data or not isinstance(data[key], dict):
        data[key] = {}
    data[key]['training'] = {'book': book, 'position': position}
    _save_user_studies(data)

def _clear_user_training(user_id: int):
    """Entfernt die Trainingsbuch-Zuordnung."""
    data = _load_user_studies()
    key = str(user_id)
    if key in data and isinstance(data[key], dict):
        data[key].pop('training', None)
        _save_user_studies(data)

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

# Status-Bits, bei denen die Stellung als "echt kaputt" gilt und nicht
# gepostet werden soll. BAD_CASTLING_RIGHTS, INVALID_EP_SQUARE, TOO_MANY_*
# werden bewusst durchgelassen – die sind in PGN-Dumps häufig und stören
# weder Rendering noch Lösungs-Anzeige.
_FATAL_STATUS = (
    chess.STATUS_NO_WHITE_KING
    | chess.STATUS_NO_BLACK_KING
    | chess.STATUS_TOO_MANY_KINGS
    | chess.STATUS_PAWNS_ON_BACKRANK
    | chess.STATUS_OPPOSITE_CHECK
    | chess.STATUS_EMPTY
    | chess.STATUS_TOO_MANY_CHECKERS
)


# Cache für load_all_lines(): in-memory + Pickle auf Disk. Der Re-Parse aller
# PGNs (~6000 Spiele) dauert ~2 s; die Cache-Lookup nur ms. Invalidiert wird
# automatisch über (mtime, size) jeder PGN-Datei – externe Edits triggern
# also Re-Parse beim nächsten Aufruf. Manueller Reset via /reindex.
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
    """Alle Linien aus .pgn-Dateien in BOOKS_DIR laden – gecached.

    Rückgabewert wird im Speicher und als Pickle in
    ``config/puzzle_lines.pkl`` zwischengespeichert; bei unverändertem
    Fingerprint (mtime+size aller PGNs + books.json) wird der Cache
    zurückgegeben statt neu zu parsen.
    """
    global _lines_cache, _lines_cache_fp

    fp = _books_fingerprint()

    # 1) In-Memory-Cache
    if _lines_cache is not None and _lines_cache_fp == fp:
        return _lines_cache

    # 2) Disk-Cache (nur einmal pro Restart relevant)
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
        while True:
            try:
                game = chess.pgn.read_game(stream)
            except Exception as e:
                log.debug('Malformierter PGN-Eintrag in %s: %s', filename, e)
                continue  # malformierten Eintrag überspringen, Stream läuft weiter
            if game is None:
                break
            # Überspringen wenn FEN-Header vorhanden aber leer
            if 'FEN' in game.headers and not game.headers['FEN'].strip():
                continue
            # Überspringen wenn keine echten Züge vorhanden (z.B. Einleitungskapitel)
            if not game.variations or game.variations[0].move == chess.Move.null():
                continue
            # Stellung auf grobe Defekte prüfen (fehlende Könige, Bauern auf
            # Grundreihe, Nicht-am-Zug-Seite im Schach, leeres Brett, mehr als
            # 2 Schach-Geber). Trifft praktisch nur PGNs mit kaputtem FEN-
            # Header; Linien aus Standard-Startposition + legalen Zügen sind
            # per Konstruktion ok. Kosmetische Status-Bits wie
            # BAD_CASTLING_RIGHTS oder INVALID_EP_SQUARE werden toleriert.
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
                # Auf DEBUG: load_all_lines() wird pro Command aufgerufen, das
                # Pattern würde sonst bei jedem /puzzle das Terminal fluten.
                # Die Summe wird unten als INFO geloggt, landet im File-Log.
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

def get_random_books() -> list[str]:
    """Liefert Liste der für Zufalls-/Daily-Auswahl freigegebenen Bücher.

    Default für fehlendes Flag = ``True`` (neu hinzugefügte Bücher sind
    automatisch im Pool; einzelne Bücher können per ``random: false`` in
    ``books/books.json`` ausgeschlossen werden).
    """
    config = _load_books_config()
    return [fn for fn, meta in config.items() if meta.get('random', True)]


def pick_random_lines(count: int = 1,
                      book_filename: str | None = None,
                      ) -> list[tuple[str, chess.pgn.Game]]:
    """Bis zu `count` zufällige noch nicht gepostete Linien wählen.

    book_filename – nur Linien aus dieser Datei (None = alle ``random:true``-Bücher).

    Ohne expliziten ``book_filename`` werden ausschließlich Bücher mit
    ``random: true`` (Default ``true``) berücksichtigt – das gilt sowohl
    für ``/puzzle`` als auch für den täglichen Post.
    """
    all_lines = load_all_lines()
    ignored = _load_ignore_list()
    chapter_ignored = _load_chapter_ignore_list()
    if book_filename:
        all_lines = [(lid, g) for lid, g in all_lines
                     if lid.startswith(book_filename + ':')]
    else:
        # Pool auf für Zufallsauswahl freigegebene Bücher beschränken
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
    """Sucht eine Linie anhand ihrer line_id (exakt oder Suffix-Match).

    Toleriert ein vorangestelltes ``ID:`` (wie es im Embed-Footer steht),
    damit der User den Footer-String 1:1 in ``/puzzle id:`` einfügen kann.
    """
    line_id = line_id.strip()
    if line_id.lower().startswith('id:'):
        line_id = line_id[3:].lstrip()
    all_lines = load_all_lines()
    # Exakter Treffer
    for lid, game in all_lines:
        if lid == line_id:
            return (lid, game)
    # Suffix-Match (z.B. "Know_firstkey.pgn:003.007" matcht
    # "100 Tactical Patterns You Must Know_firstkey.pgn:003.007")
    for lid, game in all_lines:
        if lid.endswith(line_id):
            return (lid, game)
    return None


def _prelude_pgn(context: chess.pgn.Game, puzzle: chess.pgn.Game) -> str:
    """Züge aus context VOR der Puzzle-Startstellung exportieren (ohne Lösung)."""
    # Nur Brettposition vergleichen (ohne Halbzug-/Zugzähler)
    def _key(b): return b.board_fen() + (' w ' if b.turn == chess.WHITE else ' b ')
    target_board = _key(puzzle.board())
    # Puzzle-Stellung = Root der Originalpartie → kein Vorspiel
    if _key(context.board()) == target_board:
        return ''
    prelude = chess.pgn.Game()
    prelude.headers.clear()
    ctx_fen = context.board().fen()
    if ctx_fen != chess.STARTING_FEN:
        prelude.headers['SetUp'] = '1'
        prelude.headers['FEN'] = ctx_fen
    node_src = context
    node_dst = prelude
    while node_src.variations:
        child = node_src.variations[0]
        cb = child.board()
        child_key = cb.board_fen() + (' w ' if cb.turn == chess.WHITE else ' b ')
        node_dst = node_dst.add_variation(child.move)
        if child_key == target_board:
            break
        node_src = child
    exporter = chess.pgn.StringExporter(
        headers=False, variations=False, comments=False)
    result = prelude.accept(exporter).strip()
    # Leeres Vorspiel (keine Züge) ergibt nur "*" – nicht sinnvoll anzeigen.
    return '' if result == '*' else result

def _has_training_comment(game: chess.pgn.Game) -> bool:
    """Prüft ob irgendein Knoten in der Hauptlinie [%tqu] enthält."""
    node = game
    while True:
        if '[%tqu' in (node.comment or ''):
            return True
        if not node.variations:
            return False
        node = node.variations[0]

def _trim_to_training_position(game: chess.pgn.Game) -> chess.pgn.Game:
    """Spiel auf erste [%tqu]-Stellung kürzen.
    Ohne [%tqu]-Annotation → Original unverändert zurückgeben.

    Gibt ein neues Game ab der Position des [%tqu]-Knotens zurück,
    mit dessen Varianten als Lösungsbaum.
    """
    node = game
    while True:
        if '[%tqu' in (node.comment or ''):
            break
        if not node.variations:
            return game  # kein Trainingskommentar → Original
        node = node.variations[0]

    def _gather_comments(n: chess.pgn.GameNode) -> str:
        """Alle Kommentare aus einem Teilbaum sammeln (fuer Nullzug-Varianten)."""
        parts = []
        if n.starting_comment:
            parts.append(n.starting_comment)
        if n.comment:
            parts.append(n.comment)
        for v in n.variations:
            sub = _gather_comments(v)
            if sub:
                parts.append(sub)
        return ' '.join(parts)

    def _copy(src: chess.pgn.GameNode, dst: chess.pgn.GameNode,
              board: chess.Board):
        """Baum ab src nach dst kopieren; board ist die Stellung bei dst."""
        for var in src.variations:
            if var.move not in board.legal_moves:
                text = _gather_comments(var)
                if text:
                    dst.comment = ((dst.comment or '') + ' ' + text).strip()
                continue
            child = dst.add_variation(
                var.move,
                comment=var.comment,
                starting_comment=var.starting_comment,
                nags=list(var.nags),
            )
            next_board = board.copy()
            next_board.push(var.move)
            _copy(var, child, next_board)

    def _build(src_node):
        """Neues Game ab src_node's Stellung mit dessen Varianten bauen."""
        brd = src_node.board()
        g = chess.pgn.Game()
        g.setup(brd)
        for key, val in game.headers.items():
            if key not in ('FEN', 'SetUp'):
                g.headers[key] = val
        g.comment = re.sub(r'\[%tqu\b[^\]]*\]', '', src_node.comment or '').strip()
        _copy(src_node, g, brd)
        return g

    return _build(node)


# ---------------------------------------------------------------------------
# Blind-Modus: zeigt Stellung X Züge VOR der Trainingsposition.
# Der User muss die X Züge im Kopf spielen und dann das Puzzle lösen.
# ---------------------------------------------------------------------------

def _split_for_blind(original_game: chess.pgn.Game, x_moves: int):
    """Findet erstes [%tqu]-Node, gibt (blind_board, blind_san_list, puzzle_game) zurück.

    blind_board – Stellung X Halbzüge VOR der Trainingsposition (chess.Board)
    blind_san_list – Liste der X Züge in SAN, die zur Trainingsposition führen
    puzzle_game – chess.pgn.Game ab Trainingsposition (wie _trim_to_training_position)

    Gibt None zurück wenn die Linie kein [%tqu] hat oder weniger als x_moves
    Halbzüge davor enthält.
    """
    if x_moves < 1:
        return None
    nodes: list[chess.pgn.GameNode] = []
    node = original_game
    while True:
        nodes.append(node)
        if '[%tqu' in (node.comment or ''):
            break
        if not node.variations:
            return None  # kein Trainingskommentar
        node = node.variations[0]

    plies_before = len(nodes) - 1  # Root hat keinen .move
    # Wenn nicht genug Vorlauf-Züge vorhanden, so viele wie möglich nehmen.
    x_moves = min(x_moves, plies_before)
    if x_moves < 1:
        return None

    blind_root = nodes[-1 - x_moves]
    blind_board = blind_root.board()

    blind_san: list[str] = []
    b = blind_board.copy()
    for nxt in nodes[-x_moves:]:
        if nxt.move is None:
            return None
        try:
            blind_san.append(b.san(nxt.move))
        except Exception:
            return None
        b.push(nxt.move)

    puzzle_game = _trim_to_training_position(original_game)
    return blind_board, blind_san, puzzle_game


def _format_blind_moves(start_board: chess.Board, san_list: list[str]) -> str:
    """Formatiert SAN-Liste als '15. Nf3 Nc6 16. Bb5' (mit korrekter Zugnummer)."""
    parts: list[str] = []
    move_num = start_board.fullmove_number
    is_white = start_board.turn == chess.WHITE
    for i, san in enumerate(san_list):
        if is_white:
            parts.append(f'{move_num}.')
            parts.append(san)
        else:
            if i == 0:
                parts.append(f'{move_num}...')
            parts.append(san)
            move_num += 1
        is_white = not is_white
    return ' '.join(parts)


def get_blind_books() -> list[str]:
    """Liefert Liste der für Blind-Modus freigegebenen Buch-Dateinamen."""
    config = _load_books_config()
    return [fn for fn, meta in config.items() if meta.get('blind')]


def pick_random_blind_lines(count: int,
                            book_filename: str | None,
                            x_moves: int,
                            ) -> list[tuple[str, chess.pgn.Game]]:
    """Wählt zufällige Linien aus Blind-Büchern mit ≥ x_moves Vorlauf.

    Berücksichtigt ignore-/chapter-ignore-Listen, aktualisiert aber NICHT
    den `puzzle_state.posted`-Pool (damit reguläre /puzzle-Auswahl unbeeinflusst bleibt).
    """
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


def _flatten_null_move_variations(pgn_text: str) -> str:
    """Varianten mit Nullzuegen (--) in Kommentarbloecke umwandeln.

    python-chess kann Folgezuege nach ``--`` nicht validieren und verwirft
    sie samt Kommentaren.  Diese Funktion extrahiert den Kommentartext aus
    solchen Varianten und haengt ihn als ``{...}``-Block an die Hauptlinie,
    bevor python-chess den PGN-String parst.
    """
    result: list[str] = []
    i = 0
    n = len(pgn_text)
    while i < n:
        ch = pgn_text[i]
        if ch == '{':
            # Kommentarblock komplett uebernehmen
            end = pgn_text.find('}', i + 1)
            if end < 0:
                end = n - 1
            result.append(pgn_text[i:end + 1])
            i = end + 1
        elif ch == '(':
            # Variante finden: passende Klammer suchen
            j = i + 1
            depth = 1
            while j < n and depth > 0:
                c = pgn_text[j]
                if c == '{':
                    close = pgn_text.find('}', j + 1)
                    j = (close + 1) if close >= 0 else (n)
                elif c == '(':
                    depth += 1
                    j += 1
                elif c == ')':
                    depth -= 1
                    j += 1
                else:
                    j += 1
            var_content = pgn_text[i + 1:j - 1]
            # Pruefen ob -- ausserhalb von Kommentaren vorkommt
            without_comments = re.sub(r'\{[^}]*\}', '', var_content)
            if '--' in without_comments:
                # Alle Kommentartexte extrahieren und zusammenfuegen
                comments = re.findall(r'\{([^}]*)\}', var_content)
                merged = ' '.join(c.strip() for c in comments if c.strip())
                if merged:
                    result.append('{' + merged + '}')
            else:
                # Normale Variante: rekursiv vorverarbeiten
                inner = _flatten_null_move_variations(var_content)
                result.append('(' + inner + ')')
            i = j
        else:
            result.append(ch)
            i += 1
    return ''.join(result)


def _strip_pgn_annotations(text: str) -> str:
    """Entfernt grafische PGN-Annotationen aus einem exportierten PGN-String.

    Betroffen sind alle ``[%cmd ...]``-Blöcke, z.B.:
    - ``[%cal Gf4g5,...]``  — farbige Pfeile (colored arrows)
    - ``[%csl Ga2]``        — eingefärbte Felder (colored squares)
    - ``[%tqu ...]``        — ChessBase-Trainings-Quiz-Annotation

    Nach dem Entfernen werden leere Kommentarblöcke ``{  }`` und
    überflüssige Leerzeichen bereinigt.
    """
    # Alle [%...]-Blöcke entfernen
    text = re.sub(r'\[%\w+[^\]]*\]', '', text)
    # Leere Kommentarblöcke { } entfernen
    text = re.sub(r'\{\s*\}', '', text)
    # Mehrfache Leerzeichen zusammenführen
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def _clean_pgn_for_lichess(pgn_text: str) -> str:
    """ChessBase-spezifische Annotationen entfernen, die Lichess nicht versteht.

    Stellt außerdem sicher, dass jedes PGN mit ``[FEN ...]`` auch ein
    ``[SetUp "1"]`` mitführt – PGN-Spec verlangt das, und Lichess
    interpretiert sonst die Startfarbe falsch (auto-played Black-Move,
    obwohl FEN „Black to move\" sagt).
    """
    # [%tqu ...] entfernen
    pgn_text = re.sub(r'\[%tqu\b[^\]]*\]', '', pgn_text)
    # leere Kommentare {} entfernen
    pgn_text = re.sub(r'\{\s*\}', '', pgn_text)
    # SetUp "1" ergänzen, wenn FEN-Header vorhanden, aber SetUp fehlt
    if re.search(r'^\[FEN\s+"', pgn_text, re.MULTILINE) and \
       not re.search(r'^\[SetUp\s+"', pgn_text, re.MULTILINE):
        pgn_text = re.sub(r'(^\[FEN\s+"[^"]*"\])',
                          r'[SetUp "1"]\n\1',
                          pgn_text, count=1, flags=re.MULTILINE)
    return pgn_text

_LICHESS_COOLDOWN_SECS = 3600  # 1 Stunde


class LichessRateLimitError(Exception):
    pass


def _lichess_cooldown_until() -> float:
    """Liest den gespeicherten Cooldown-Zeitstempel (Unix-Zeit). 0 = kein Cooldown."""
    try:
        data = atomic_read(LICHESS_COOLDOWN_FILE)
        return float(data.get('until', 0))
    except (ValueError, TypeError, AttributeError):
        return 0.0


def _lichess_rate_limited() -> bool:
    """True wenn Lichess gerade im Rate-Limit-Cooldown ist."""
    return _time_mod.time() < _lichess_cooldown_until()


def _lichess_set_cooldown(retry_after: int | None = None):
    """Setzt den Cooldown-Zeitstempel und schreibt ihn auf Disk.

    retry_after – Sekunden aus dem Retry-After-Header (None = 1h Fallback).
    """
    secs  = retry_after if retry_after and retry_after > 0 else _LICHESS_COOLDOWN_SECS
    until = _time_mod.time() + secs
    atomic_write(LICHESS_COOLDOWN_FILE, {'until': until})
    log.warning('Lichess 429 – Cooldown bis %s gesetzt (%ds).',
                _datetime.fromtimestamp(until).strftime('%H:%M'), secs)


def _lichess_request(method: str, url: str, **kwargs):
    """Lichess-API-Request. Bei 429 wird ein persistenter Cooldown gesetzt."""
    resp = requests.request(method, url, **kwargs)
    if resp.status_code == 429:
        try:
            retry_after = int(resp.headers.get('Retry-After', 0))
        except (ValueError, TypeError):
            retry_after = 0
        _lichess_set_cooldown(retry_after or None)
        raise LichessRateLimitError()
    return resp


def upload_to_lichess(game: chess.pgn.Game,
                      context_game: chess.pgn.Game | None = None,
                      reuse_study_id: str | None = None,
                      _depth: int = 0) -> str | None:
    """Neue Lichess-Studie anlegen, PGN importieren und Kapitel-URL zurückgeben.

    game         – gekürztes Spiel ab Trainingsposition (Gamebook-Kapitel 1)
    context_game – vollständiges Originalspiel als Kapitel 2 (optional,
                   nur sinnvoll wenn Trainingsposition nicht am Anfang liegt)
    Gibt None zurück wenn Lichess im Cooldown ist.
    """
    if _lichess_rate_limited():
        remaining = int(_lichess_cooldown_until() - _time_mod.time())
        log.info('Lichess-Upload übersprungen (Cooldown noch %ds).', remaining)
        return None
    try:
        # Gamebook: nur Züge + Varianten, keine Kommentare (stören im Gamebook-Modus)
        pgn_text = _export_pgn_for_lichess(game, comments=False)
    except Exception as e:
        log.error('PGN-Export fehlgeschlagen: %s', e)
        return None

    h = dict(game.headers)
    line_name  = h.get('White', h.get('Event', 'Puzzle'))
    event_name = h.get('Event', 'Puzzle')
    # Orientierung: Seite am Zug = Seite des Studenten im Gamebook
    orientation = 'black' if game.board().turn == chess.BLACK else 'white'
    today      = _date.today().strftime('%d.%m.%Y')
    study_name = f'{event_name} – {today}'
    if len(study_name) > _LICHESS_STUDY_NAME_MAX:
        study_name = study_name[:_LICHESS_STUDY_NAME_MAX - 3] + '...'

    # Kontext-PGN vorbereiten (2. Kapitel: vollständiges Originalspiel)
    context_pgn = None
    context_name = None
    if context_game is not None:
        try:
            context_pgn = _export_pgn_for_lichess(context_game)
            ch = dict(context_game.headers)
            ctx_title = ch.get('White', ch.get('Event', 'Partie'))
            if len(ctx_title) > _LICHESS_CHAPTER_NAME_MAX:
                ctx_title = ctx_title[:_LICHESS_CHAPTER_NAME_MAX - 3] + '...'
            context_name = f'Partie: {ctx_title}'
        except Exception as e:
            log.warning('Kontext-PGN-Export fehlgeschlagen: %s', e)
            context_pgn = None

    auth_headers = {}
    if LICHESS_TOKEN:
        auth_headers['Authorization'] = f'Bearer {LICHESS_TOKEN}'

    # Kapitel in Studie importieren (benötigt LICHESS_TOKEN mit study:write)
    if LICHESS_TOKEN:
        try:
            # Bestehende Studie nutzen oder neue anlegen
            if reuse_study_id or PUZZLE_STUDY_ID:
                study_id = reuse_study_id or PUZZLE_STUDY_ID
                default_chapter_id = ''
            else:
                r = _lichess_request(
                    'POST', 'https://lichess.org/api/study',
                    data={
                        'name':       study_name,
                        'visibility': 'unlisted',
                        'computer':   'everyone',
                        'explorer':   'everyone',
                        'cloneable':  'everyone',
                        'shareable':  'everyone',
                        'chat':       'everyone',
                    },
                    headers=auth_headers,
                    timeout=LICHESS_API_TIMEOUT,
                )
                r.raise_for_status()
                study_id = r.json().get('id', '')
                # Leeres Auto-Kapitel merken – ID aus ChapterURL extrahieren
                pgn_resp = _lichess_request(
                    'GET', f'https://lichess.org/api/study/{study_id}.pgn',
                    headers=auth_headers,
                    timeout=LICHESS_API_TIMEOUT,
                )
                default_game = chess.pgn.read_game(io.StringIO(pgn_resp.text))
                if default_game:
                    chapter_url_hdr = default_game.headers.get('ChapterURL', '')
                    default_chapter_id = chapter_url_hdr.rstrip('/').split('/')[-1]
                    log.info('Leeres Auto-Kapitel: %s', default_chapter_id)
                else:
                    default_chapter_id = ''

            if study_id:
                # Kapitel 1: Gamebook ab Trainingsposition
                r2 = _lichess_request(
                    'POST', f'https://lichess.org/api/study/{study_id}/import-pgn',
                    data={'pgn': pgn_text, 'name': line_name, 'mode': 'gamebook',
                          'orientation': orientation},
                    headers=auth_headers,
                    timeout=LICHESS_API_TIMEOUT,
                )
                r2.raise_for_status()
                chapters = r2.json().get('chapters', [])
                chapter_id = chapters[-1].get('id', '') if chapters else ''
                log.info('Gamebook-Kapitel importiert: %s (chapter_id=%s)', line_name, chapter_id)

                # Studie voll → neue anlegen und nochmal versuchen (max 1× Rekursion)
                if not chapter_id and reuse_study_id and _depth < 1:
                    log.info('Studie %s voll – lege neue an.', reuse_study_id)
                    return upload_to_lichess(game, context_game=context_game,
                                            reuse_study_id=None, _depth=_depth + 1)

                # Kapitel 2: vollständiges Originalspiel (nur wenn vorhanden)
                if context_pgn:
                    r3 = _lichess_request(
                        'POST', f'https://lichess.org/api/study/{study_id}/import-pgn',
                        data={'pgn': context_pgn, 'name': context_name, 'mode': 'normal'},
                        headers=auth_headers,
                        timeout=LICHESS_API_TIMEOUT,
                    )
                    if r3.status_code == 200:
                        log.info('Kontext-Kapitel importiert: %s', context_name)
                    else:
                        log.warning('Kontext-Kapitel Import HTTP %s', r3.status_code)

                # Leeres Auto-Kapitel löschen
                if default_chapter_id:
                    rd = _lichess_request(
                        'DELETE', f'https://lichess.org/api/study/{study_id}/{default_chapter_id}',
                        headers=auth_headers,
                        timeout=LICHESS_API_TIMEOUT,
                    )
                    log.info('Auto-Kapitel geloescht: HTTP %s', rd.status_code)

                if chapter_id:
                    return f'https://lichess.org/study/{study_id}/{chapter_id}'
                return f'https://lichess.org/study/{study_id}'
        except LichessRateLimitError:
            return None  # Cooldown bereits geloggt
        except Exception as e:
            log.error('Lichess-Study-Upload fehlgeschlagen: %s', e)
            # Fallback auf standalone Import

    # Fallback: einfacher Spielimport ohne Account (nur wenn kein Cooldown)
    if _lichess_rate_limited():
        return None
    try:
        resp = _lichess_request(
            'POST', 'https://lichess.org/api/import',
            data={'pgn': pgn_text},
            headers=auth_headers,
            timeout=LICHESS_API_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get('url')
    except Exception as e:
        log.error('Lichess-Upload fehlgeschlagen: %s', e)
        return None

def upload_many_to_lichess(
    puzzles: list[tuple[chess.pgn.Game, chess.pgn.Game | None]],
    reuse_study_id: str | None = None,
) -> list[str]:
    """Mehrere Puzzles als Gamebook-Kapitel in eine gemeinsame Lichess-Studie laden.
    Gibt eine Liste von Kapitel-URLs zurück (eine pro Puzzle)."""
    if _lichess_rate_limited():
        remaining = int(_lichess_cooldown_until() - _time_mod.time())
        log.info('Lichess-Multi-Upload übersprungen (Cooldown noch %ds).', remaining)
        return []
    if not puzzles:
        return []
    if len(puzzles) == 1:
        u = upload_to_lichess(puzzles[0][0], context_game=puzzles[0][1], reuse_study_id=reuse_study_id)
        return [u] if u else []
    if not LICHESS_TOKEN:
        u = upload_to_lichess(puzzles[0][0], context_game=puzzles[0][1], reuse_study_id=reuse_study_id)
        return [u] if u else []

    auth_headers = {'Authorization': f'Bearer {LICHESS_TOKEN}'}

    try:
        if reuse_study_id:
            study_id = reuse_study_id
            default_chapter_id = ''
        else:
            today      = _date.today().strftime('%d.%m.%Y')
            study_name = f'Puzzles – {today}'
            r = _lichess_request(
                'POST', 'https://lichess.org/api/study',
                data={'name': study_name, 'visibility': 'unlisted', 'computer': 'everyone',
                      'explorer': 'everyone', 'cloneable': 'everyone',
                      'shareable': 'everyone', 'chat': 'everyone'},
                headers=auth_headers, timeout=LICHESS_API_TIMEOUT,
            )
            r.raise_for_status()
            study_id = r.json().get('id', '')
            if not study_id:
                return []

            # Leeres Auto-Kapitel merken
            pgn_resp = _lichess_request(
                'GET', f'https://lichess.org/api/study/{study_id}.pgn',
                headers=auth_headers, timeout=LICHESS_API_TIMEOUT,
            )
            default_chapter_id = ''
            if pgn_resp.status_code == 200:
                dg = chess.pgn.read_game(io.StringIO(pgn_resp.text))
                if dg:
                    default_chapter_id = dg.headers.get('ChapterURL', '').rstrip('/').split('/')[-1]

        # Kapitel importieren
        chapter_urls: list[str] = []
        for game, context in puzzles:
            try:
                pgn  = _export_pgn_for_lichess(game)
                h    = dict(game.headers)
                name = h.get('White', h.get('Event', 'Puzzle'))[:_LICHESS_CHAPTER_NAME_MAX]
                ori  = 'black' if game.board().turn == chess.BLACK else 'white'
                r_ch = _lichess_request(
                    'POST', f'https://lichess.org/api/study/{study_id}/import-pgn',
                    data={'pgn': pgn, 'name': name, 'mode': 'gamebook',
                          'orientation': ori},
                    headers=auth_headers, timeout=LICHESS_API_TIMEOUT,
                )
                r_ch.raise_for_status()
                chs = r_ch.json().get('chapters', [])
                ch_id = chs[-1].get('id', '') if chs else ''
                log.info('Gamebook-Kapitel importiert: %s (chapter_id=%s)', name, ch_id)

                # Studie voll → Rest in neue Studie
                if not ch_id and reuse_study_id:
                    remaining = puzzles[puzzles.index((game, context)):]
                    log.info('Studie %s voll – lege neue an fuer %d verbleibende Kapitel.',
                             reuse_study_id, len(remaining))
                    return chapter_urls + upload_many_to_lichess(remaining, reuse_study_id=None)

                if ch_id:
                    chapter_urls.append(f'https://lichess.org/study/{study_id}/{ch_id}')
                else:
                    chapter_urls.append(f'https://lichess.org/study/{study_id}')

                if context is not None:
                    ctx_pgn = _export_pgn_for_lichess(context)
                    ch      = dict(context.headers)
                    ctx_name = f'Partie: {ch.get("White", "Partie")[:64]}'
                    _lichess_request(
                        'POST', f'https://lichess.org/api/study/{study_id}/import-pgn',
                        data={'pgn': ctx_pgn, 'name': ctx_name, 'mode': 'normal'},
                        headers=auth_headers, timeout=LICHESS_API_TIMEOUT,
                    )
                    log.info('Kontext-Kapitel importiert: %s', ctx_name)
            except LichessRateLimitError:
                raise  # nach oben weitergeben → Studie wird nicht halb gefüllt
            except Exception as e:
                log.warning('Kapitel-Import übersprungen: %s', e)
                chapter_urls.append('')  # Platzhalter damit Index stimmt
            _time_mod.sleep(1)  # kurze Pause zwischen Kapiteln gegen Rate Limit

        # Auto-Kapitel löschen
        if default_chapter_id:
            _lichess_request(
                'DELETE', f'https://lichess.org/api/study/{study_id}/{default_chapter_id}',
                headers=auth_headers, timeout=LICHESS_API_TIMEOUT,
            )

        return chapter_urls
    except LichessRateLimitError:
        return []  # Cooldown bereits geloggt
    except Exception as e:
        log.error('Multi-Upload fehlgeschlagen: %s', e)
        return []


def build_puzzle_embed(game: chess.pgn.Game,
                       turn: chess.Color | None = None,
                       puzzle_num: int = 0,
                       puzzle_total: int = 0,
                       difficulty: str = '',
                       rating: int = 0,
                       line_id: str = '',
                       blind_moves: int = 0) -> discord.Embed:
    h = dict(game.headers)
    line_name  = h.get('White', h.get('Event', 'Linie'))
    event_name = h.get('Event', '')
    black_name = h.get('Black', '')

    # Kursname als Titel
    course = event_name or 'Puzzle'
    if len(course) > 80:
        course = course[:77] + '...'

    embed = discord.Embed(
        title=f'🧩 {course}',
        color=0x7fa650,
    )

    if black_name:
        embed.add_field(name='📖 Kapitel', value=f'||{black_name}||', inline=False)

    if line_name and line_name != event_name:
        embed.add_field(name='📝 Linie', value=f'||{line_name}||', inline=False)

    if difficulty:
        embed.add_field(name='📊 Schwierigkeit', value=difficulty, inline=True)

    # Bild wird extern via set_image gesetzt

    if turn is not None:
        turn_str = '⬜ Weiß am Zug' if turn == chess.WHITE else '⬛ Schwarz am Zug'
        embed.add_field(name='Am Zug', value=turn_str, inline=True)

    if puzzle_num > 0:
        stats = f'Heute: **{puzzle_num}** · Gesamt: **{puzzle_total}**'
        embed.add_field(name='\u200b', value=stats, inline=False)

    if line_id:
        footer = f'ID: {line_id}:blind:{blind_moves}' if blind_moves else f'ID: {line_id}'
    else:
        footer = '🧩 Tägliches Puzzle'
    embed.set_footer(text=footer)
    return embed


async def _resilient_send(target, *args, retries: int = 3, **kwargs):
    """Wie target.send(), aber mit Retry bei transienten Discord-5xx-Fehlern.

    Backoff: 1s, 2s, 4s. Wirft beim letzten Fehlversuch weiter.
    """
    delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            return await target.send(*args, **kwargs)
        except discord.errors.DiscordServerError as e:
            if attempt == retries:
                raise
            log.warning('Discord-5xx (Versuch %d/%d): %s – retry in %.1fs',
                        attempt, retries, e, delay)
            await asyncio.sleep(delay)
            delay = delay * 2 + random.uniform(0, 1)


async def _send_optional(target, *args, label: str = '', **kwargs):
    """Send, der bei Discord-5xx (auch nach Retries) nur loggt, nicht wirft."""
    try:
        return await _resilient_send(target, *args, **kwargs)
    except discord.errors.DiscordServerError as e:
        log.warning('Optionaler Send (%s) fehlgeschlagen nach Retries: %s', label, e)
    except Exception as e:
        log.warning('Optionaler Send (%s) fehlgeschlagen: %s', label, e)
    return None


async def post_puzzle(channel, count: int = 1, book_idx: int = 0, user_id: int | None = None) -> int:
    """Puzzles auswählen, auf Lichess hochladen und posten.

    count    – Anzahl Puzzles (1–20).
    book_idx – 1-basierte Buchnummer aus /kurs (0 = alle Bücher).
    user_id  – Discord-User-ID; wenn gesetzt, wird die Tages-Studie wiederverwendet.

    Gibt die Anzahl tatsächlich geposteter Puzzles zurück.
    """
    count = max(1, min(count, 20))

    # Buch bestimmen
    book_filename = None
    if book_idx > 0:
        books = _list_pgn_files()
        if books:
            if 1 <= book_idx <= len(books):
                book_filename = books[book_idx - 1]
            else:
                await channel.send(
                    f'⚠️ Buch {book_idx} nicht gefunden. `/kurs` zeigt die verfügbaren Bücher.'
                )
                return 0

    results = pick_random_lines(count, book_filename)
    if not results:
        await channel.send('⚠️ Keine Puzzle-Linien gefunden. Bitte .pgn-Dateien in den `books/`-Ordner legen.')
        return 0

    books_config = _load_books_config()

    # Trimmen
    puzzles: list[tuple[chess.pgn.Game, chess.pgn.Game | None, str, int, str]] = []
    for line_id, original_game in results:
        game    = _trim_to_training_position(original_game)
        context = original_game if game is not original_game else None
        fname   = line_id.split(':')[0]
        book_meta = books_config.get(fname, {})
        diff      = book_meta.get('difficulty', '')
        rating    = book_meta.get('rating', 0)
        puzzles.append((game, context, diff, rating, line_id))

    reuse_study_id = _get_user_study_id(user_id) if user_id else None
    base_count, base_total = _get_user_puzzle_count(user_id) if user_id else (0, 0)

    # Upload in Thread damit der Event Loop nicht blockiert
    upload_pairs = [(g, c) for g, c, _, _, _ in puzzles]
    urls = await _upload_puzzles_async(upload_pairs, reuse_study_id=reuse_study_id)

    # Studie-ID für diesen User+Tag speichern
    first_url = urls[0] if urls else None
    sid = _extract_study_id(first_url) if first_url and user_id else None
    if sid:
        _set_user_study_id(user_id, sid, base_count + len(puzzles), base_total + len(puzzles))

    # Thread-Name vom ersten Puzzle
    h = dict(puzzles[0][0].headers)
    event = h.get('Event', 'Puzzle')
    today = _date.today().strftime('%d.%m.%Y')
    thread_name = f'{event} – {today}'
    if len(thread_name) > 100:
        thread_name = thread_name[:_DISCORD_THREAD_NAME_MAX - 3] + '...'

    # Ziel: Thread (Server) oder direkt (DM / bestehender Thread)
    is_dm = isinstance(channel, discord.DMChannel)
    if is_dm or isinstance(channel, discord.Thread):
        target = channel
    else:
        target = await channel.create_thread(
            name=thread_name,
            type=discord.ChannelType.public_thread,
            auto_archive_duration=1440,
        )

    # Alle Puzzles als einzelne Bilder posten. Jede Iteration in try/except,
    # damit ein einzelner Crash (kaputtes Board, Discord-Edge-Case) nicht die
    # restlichen Puzzles verschluckt – der User soll bei /puzzle 5 auch dann 4
    # bekommen, wenn Nr. 2 schiefgeht.
    posted_ok = 0
    log.info('post_puzzle: poste %d Puzzle(s) in %s',
             len(puzzles), 'DM' if is_dm else f'thread {target.id}')
    for i, (game, context, diff, rating, lid) in enumerate(puzzles):
        try:
            puzzle_url = urls[i] if i < len(urls) else None
            puzzle_num   = (base_count + i + 1) if user_id else 0
            puzzle_total = (base_total + i + 1) if user_id else 0
            try:
                board = game.board()
                turn  = board.turn
                img   = await asyncio.to_thread(_render_board, board)
            except Exception as e:
                log.warning('Board-Render fehlgeschlagen (%s): %s', lid, e)
                turn = None
                img  = None

            embed = build_puzzle_embed(game, turn=turn, puzzle_num=puzzle_num, puzzle_total=puzzle_total, difficulty=diff, rating=rating, line_id=lid)
            # Haupt-Send: Brett + Embed. Nur das ist der Erfolgs-Anker;
            # alles danach (Lösung, Lichess-Link) ist optional und darf
            # bei Discord-5xx das Puzzle nicht als gescheitert markieren.
            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                msg = await _resilient_send(target, file=file, embed=embed)
            else:
                msg = await _resilient_send(target, embed=embed)
            posted_ok += 1
            _register_puzzle_msg(msg.id, lid)
        except Exception as e:
            log.exception('Puzzle %d/%d (%s) fehlgeschlagen: %s',
                          i + 1, len(puzzles), lid, e)
            continue

        # Ab hier ist das Puzzle „gepostet". Folgende Sends sind Beiwerk –
        # wenn Discord 5xx wirft, loggen wir, zählen aber nicht runter.
        try:
            await msg.edit(view=_fresh_button_view())
        except Exception as e:
            log.warning('Button-View-Edit fehlgeschlagen (%s): %s', lid, e)

        await _send_puzzle_followups(target, game, context, puzzle_url, lid)

    log.info('post_puzzle: %d/%d Puzzle(s) gepostet', posted_ok, len(puzzles))
    if user_id and posted_ok:
        stats.inc(user_id, 'puzzles', posted_ok)
    return posted_ok


async def post_blind_puzzle(channel,
                            moves: int,
                            count: int = 1,
                            book_idx: int = 0,
                            user_id: int | None = None):
    """Postet Blind-Puzzles: Stellung X Halbzüge VOR der Trainingsposition.

    moves    – Anzahl Halbzüge, die der User im Kopf spielen muss (≥1).
    count    – Anzahl Puzzles (1–20).
    book_idx – 1-basierte Buchnummer (0 = alle blind-fähigen Bücher).
    """
    moves = max(1, moves)
    count = max(1, min(count, 20))

    book_filename = None
    if book_idx > 0:
        books = _list_pgn_files()
        if books:
            if 1 <= book_idx <= len(books):
                book_filename = books[book_idx - 1]
            else:
                await channel.send(
                    f'⚠️ Buch {book_idx} nicht gefunden. `/kurs` zeigt verfügbare Bücher.'
                )
                return

    config = _load_books_config()
    if book_filename and not config.get(book_filename, {}).get('blind'):
        await channel.send(
            f'⚠️ Buch `{book_filename}` ist nicht für den Blind-Modus freigegeben.\n'
            'Setze in `books/books.json` `"blind": true` für dieses Buch.'
        )
        return

    results = pick_random_blind_lines(count, book_filename, moves)
    if not results:
        if not any(m.get('blind') for m in config.values()):
            await channel.send(
                '⚠️ Kein Buch hat `blind: true` in `books/books.json`. '
                'Bitte mindestens ein Buch dafür freigeben.'
            )
        else:
            await channel.send(
                f'⚠️ Kein Puzzle mit ≥{moves} Vorlauf-Zügen gefunden. '
                'Versuche eine kleinere `moves:`-Zahl oder ein anderes Buch.'
            )
        return

    h = dict(results[0][1].headers)
    event = h.get('Event', 'Blind-Puzzle')
    today = _date.today().strftime('%d.%m.%Y')
    thread_name = f'🙈 {event} (blind {moves}) – {today}'
    if len(thread_name) > 100:
        thread_name = thread_name[:_DISCORD_THREAD_NAME_MAX - 3] + '...'

    is_dm = isinstance(channel, discord.DMChannel)
    if is_dm:
        target = channel
    else:
        target = await channel.create_thread(
            name=thread_name,
            type=discord.ChannelType.public_thread,
            auto_archive_duration=1440,
        )

    posted = 0
    for line_id, original_game in results:
        split = _split_for_blind(original_game, moves)
        if split is None:
            continue
        blind_board, blind_san, puzzle_game = split

        fname = line_id.split(':')[0]
        meta = config.get(fname, {})
        diff = meta.get('difficulty', '')
        rating = meta.get('rating', 0)

        try:
            img = await asyncio.to_thread(_render_board, blind_board)
        except Exception as e:
            log.warning('Blind-Board-Render fehlgeschlagen: %s', e)
            img = None

        embed = build_puzzle_embed(
            puzzle_game,
            turn=blind_board.turn,
            difficulty=diff,
            rating=rating,
            line_id=line_id,
            blind_moves=moves,
        )
        embed.title = f'🙈 Blind-Puzzle ({moves} Züge)'
        blind_pgn = _format_blind_moves(blind_board, blind_san)
        embed.add_field(
            name='🙈 Spiele in Gedanken',
            value=f'`{blind_pgn}`\n_Visualisiere die Stellung danach und löse das Puzzle._',
            inline=False,
        )

        try:
            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                msg = await _resilient_send(target, file=file, embed=embed)
            else:
                msg = await _resilient_send(target, embed=embed)
            posted += 1
            _register_puzzle_msg(msg.id, line_id, mode='blind')
        except Exception as e:
            log.exception('Blind-Puzzle (%s) fehlgeschlagen: %s', line_id, e)
            continue

        try:
            await msg.edit(view=_fresh_button_view())
        except Exception as e:
            log.warning('Blind-Button-View-Edit fehlgeschlagen (%s): %s', line_id, e)

        pgn_moves = _solution_pgn(puzzle_game)
        if pgn_moves:
            await _send_optional(target, f'Lösung des Puzzles: ||`{pgn_moves}`||',
                                 label=f'Blind-Lösung {line_id}')

    if user_id and posted:
        stats.inc(user_id, 'blind_puzzles', posted)


# ---------------------------------------------------------------------------
# Slash-Commands registrieren
# ---------------------------------------------------------------------------

async def _cmd_puzzle(interaction: discord.Interaction, anzahl: int = 1, buch: int = 0,
                      id: str = '', user: discord.Member | None = None):
    target_user = user or interaction.user
    log.info('/puzzle von %s: anzahl=%d buch=%d id=%s user=%s',
             interaction.user, anzahl, buch, id, target_user)
    await interaction.response.defer(ephemeral=True)
    try:
        dm = await target_user.create_dm()
        target_uid = target_user.id

        if id:
            # Blind-Referenz: "lid:blind:N" → post_blind_puzzle
            _blind_moves = 0
            _lookup_id = id
            _blind_match = re.search(r':blind:(\d+)$', id, re.IGNORECASE)
            if _blind_match:
                _blind_moves = int(_blind_match.group(1))
                if _blind_moves > 50:
                    await interaction.followup.send(
                        '⚠️ Maximal 50 Blind-Züge erlaubt.', ephemeral=True)
                    return
                _lookup_id = id[:_blind_match.start()]

            result = find_line_by_id(_lookup_id)
            if not result:
                await interaction.followup.send(f'⚠️ Puzzle `{id}` nicht gefunden.', ephemeral=True)
                return

            if not _has_training_comment(result[1]):
                await interaction.followup.send(
                    f'⚠️ `{id}` hat keinen Trainingskommentar.', ephemeral=True)
                return

            if _blind_moves:
                if user:
                    await dm.send(f'**{interaction.user.display_name}** schickt dir ein Blind-Puzzle 🙈')
                line_id = result[0]
                orig = result[1]
                split = _split_for_blind(orig, _blind_moves)
                if split is None:
                    await interaction.followup.send(
                        f'⚠️ Puzzle `{line_id}` hat nicht genug Vorlauf-Züge für blind:{_blind_moves}.',
                        ephemeral=True)
                    return
                blind_board, blind_san, puzzle_game = split
                fname = line_id.split(':')[0]
                meta  = _load_books_config().get(fname, {})
                try:
                    img = await asyncio.to_thread(_render_board, blind_board)
                except Exception:
                    img = None
                embed = build_puzzle_embed(
                    puzzle_game, turn=blind_board.turn,
                    difficulty=meta.get('difficulty',''), rating=meta.get('rating', 0),
                    line_id=line_id, blind_moves=_blind_moves)
                embed.title = f'🙈 Blind-Puzzle ({_blind_moves} Züge)'
                blind_pgn = _format_blind_moves(blind_board, blind_san)
                embed.add_field(name='🙈 Spiele in Gedanken',
                                value=f'`{blind_pgn}`\n_Visualisiere die Stellung danach und löse das Puzzle._',
                                inline=False)
                if img:
                    file = discord.File(img, filename='board.png')
                    embed.set_image(url='attachment://board.png')
                    msg = await _resilient_send(dm, file=file, embed=embed)
                else:
                    msg = await _resilient_send(dm, embed=embed)
                _register_puzzle_msg(msg.id, line_id, mode='blind')
                try:
                    await msg.edit(view=_fresh_button_view())
                except Exception:
                    pass
                pgn_moves = _solution_pgn(puzzle_game)
                if pgn_moves:
                    await _send_optional(dm, f'Lösung des Puzzles: ||`{pgn_moves}`||', label=f'Blind-Lösung {line_id}')
                dest = f'an {target_user.mention}' if user else 'dir'
                await interaction.followup.send(f'🙈 Blind-Puzzle `{line_id}:blind:{_blind_moves}` {dest} per DM gesendet.', ephemeral=True)
                return

            line_id, original_game = result
            game = _trim_to_training_position(original_game)
            context = original_game if game is not original_game else None

            books_config = _load_books_config()
            fname = line_id.split(':')[0]
            book_meta = books_config.get(fname, {})
            diff = book_meta.get('difficulty', '')
            rating = book_meta.get('rating', 0)

            # Upload
            reuse_study_id = _get_user_study_id(target_uid)
            urls = await _upload_puzzles_async([(game, context)], reuse_study_id=reuse_study_id)
            puzzle_url = urls[0] if urls else None

            try:
                board = game.board()
                turn = board.turn
                img = await asyncio.to_thread(_render_board, board)
            except Exception:
                turn, img = None, None

            if user:
                await dm.send(f'**{interaction.user.display_name}** schickt dir ein Rätsel 🧩')

            embed = build_puzzle_embed(game, turn=turn, difficulty=diff, rating=rating, line_id=line_id)
            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                msg = await dm.send(file=file, embed=embed)
            else:
                msg = await dm.send(embed=embed)
            _register_puzzle_msg(msg.id, line_id)
            await msg.edit(view=_fresh_button_view())

            await _send_puzzle_followups(dm, game, context, puzzle_url, line_id)

            dest = f'an {target_user.mention}' if user else 'dir'
            await interaction.followup.send(
                f'✅ Puzzle `{line_id}` {dest} per DM gesendet.', ephemeral=True)
            return

        if user:
            await dm.send(f'**{interaction.user.display_name}** schickt dir ein Rätsel 🧩')
        sent = await post_puzzle(dm, count=anzahl, book_idx=buch, user_id=target_uid)
        dest = f'an {target_user.mention}' if user else 'dir'
        if sent == anzahl:
            msg = f'✅ {sent} Puzzle(s) wurde(n) {dest} per DM gesendet.'
        elif sent > 0:
            msg = f'⚠️ Nur {sent}/{anzahl} Puzzle(s) konnten {dest} gesendet werden – Details im Bot-Log.'
        else:
            msg = '❌ Es konnte kein Puzzle gesendet werden – Details im Bot-Log.'
        await interaction.followup.send(msg, ephemeral=True)
    except Exception as e:
        log.exception('/puzzle fehlgeschlagen: %s', e)
        await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)


async def _cmd_buecher(interaction: discord.Interaction, buch: int = 0):
    await interaction.response.defer(ephemeral=True)
    try:
        all_lines = load_all_lines()
        posted    = set(load_puzzle_state().get('posted', []))
        books_config = _load_books_config()

        # --- Detailansicht für ein einzelnes Buch ---
        if buch > 0:
            sorted_books = sorted(set(lid.split(':')[0] for lid, _ in all_lines))
            if buch > len(sorted_books):
                await interaction.followup.send(
                    f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die Liste.',
                    ephemeral=True)
                return
            book_fn = sorted_books[buch - 1]
            book_name = _clean_book_name(book_fn)
            meta  = books_config.get(book_fn, {})
            diff  = meta.get('difficulty', '')
            rat   = meta.get('rating', 0)
            stars = '★' * rat + '☆' * (10 - rat) if rat else ''

            # Persönlich abgehakte Puzzles (✅ oder ❌, netto >0)
            from core import event_log as _elog
            uid = interaction.user.id
            _net: dict[str, int] = {}
            for entry in _elog.read_all():
                if entry.get('user') != uid:
                    continue
                if entry.get('emoji') not in ('✅', '❌'):
                    continue
                lid_e = entry.get('line_id') or ''
                _net[lid_e] = _net.get(lid_e, 0) + entry.get('delta', 0)
            user_done: set[str] = {lid_e for lid_e, n in _net.items() if n > 0}

            # Kapitel aufbauen: round-Prefix → (name, total, done)
            chapter_ignored = _load_chapter_ignore_list()
            chapters: dict[str, dict] = {}
            for lid, game in all_lines:
                if lid.split(':')[0] != book_fn:
                    continue
                round_hdr = lid.split(':')[1] if ':' in lid else ''
                prefix = round_hdr.split('.')[0] if '.' in round_hdr else round_hdr
                if prefix not in chapters:
                    h = dict(game.headers)
                    chap_name = h.get('Black', '') or h.get('Event', '')
                    ignored_key = f'{book_fn}:{prefix}'
                    chapters[prefix] = {
                        'name': chap_name,
                        'total': 0,
                        'posted': 0,
                        'ignored': ignored_key in chapter_ignored,
                    }
                chapters[prefix]['total'] += 1
                if lid in user_done:
                    chapters[prefix]['posted'] += 1

            total_book  = sum(c['total']  for c in chapters.values())
            posted_book = sum(c['posted'] for c in chapters.values())

            flags = []
            if meta.get('random', True):  flags.append('🎲 Im Zufalls-/Daily-Pool')
            if meta.get('blind'):          flags.append('🙈 Blind-Modus')

            desc_parts = [f'**{posted_book}/{total_book}** von dir bewertet (✅/❌)']
            if diff:
                desc_parts.append(f'{diff}  {stars}' if stars else diff)
            desc_parts.extend(flags)

            embed = discord.Embed(
                title=f'📖 {book_name}',
                description='\n'.join(desc_parts),
                color=0x7fa650,
            )

            sorted_chapters = sorted(chapters.items())
            # Bis zu 25 Felder (Discord-Limit)
            for prefix, info in sorted_chapters[:25]:
                chap_num = int(prefix) if prefix.isdigit() else prefix
                done  = info['posted']
                total = info['total']
                is_ign = info['ignored']
                bar   = '█' * round(done / total * 8) + '░' * (8 - round(done / total * 8)) if total else '░' * 8
                label = f'Kap. {chap_num}: {info["name"]}' if info['name'] else f'Kapitel {chap_num}'
                if len(label) > 250:
                    label = label[:247] + '...'
                name_field = f'~~{label}~~ 🚫' if is_ign else label
                embed.add_field(
                    name=name_field,
                    value=f'`{bar}` {done}/{total}' + (' *(ignoriert)*' if is_ign else ''),
                    inline=False,
                )
            if len(sorted_chapters) > 25:
                embed.set_footer(text=f'… {len(sorted_chapters) - 25} weitere Kapitel nicht angezeigt')
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # --- Übersichtsliste aller Bücher ---
        total_per_book:  dict[str, int] = defaultdict(int)
        posted_per_book: dict[str, int] = defaultdict(int)
        for lid, _ in all_lines:
            book = lid.split(':')[0]
            total_per_book[book] += 1
            if lid in posted:
                posted_per_book[book] += 1

        if not total_per_book:
            await interaction.followup.send(
                '⚠️ Keine Bücher gefunden. Bitte .pgn-Dateien in den `books/`-Ordner legen.',
                ephemeral=True,
            )
            return

        embed = discord.Embed(title='📚 Puzzle-Bücher', color=0x7fa650)
        for i, book in enumerate(sorted(total_per_book), 1):
            name  = _clean_book_name(book)
            total = total_per_book[book]
            done  = posted_per_book[book]
            meta  = books_config.get(book, {})
            diff  = meta.get('difficulty', '')
            rat   = meta.get('rating', 0)
            stars = '★' * rat + '☆' * (10 - rat) if rat else ''
            info  = f'{done}/{total} gepostet'
            if diff:
                info += f'\n{diff}  {stars}' if stars else f'\n{diff}'
            if meta.get('random', True):
                info += '\n🎲 Im Zufalls-/Daily-Pool'
            if meta.get('blind'):
                info += '\n🙈 Blind-Modus verfügbar'
            embed.add_field(name=f'{i}: {name}', value=info, inline=False)

        total_all = sum(total_per_book.values())
        done_all  = sum(posted_per_book.values())
        embed.set_footer(text=f'Gesamt: {done_all}/{total_all} Linien gepostet')
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)


async def _cmd_train(interaction: discord.Interaction, buch: int = None):
    await interaction.response.defer(ephemeral=True)
    user_id = interaction.user.id

    if buch is None:
        # Status anzeigen
        training = _get_user_training(user_id)
        if not training:
            await interaction.followup.send(
                '📭 Kein Training aktiv. Wähle ein Buch mit `/train <nummer>` '
                '(Nummern aus `/kurs`).', ephemeral=True)
            return
        book_filename = training['book']
        pos = training['position']
        all_lines = load_all_lines()
        total = sum(1 for lid, _ in all_lines if lid.startswith(book_filename + ':'))
        name = _clean_book_name(book_filename)
        books = _list_pgn_files()
        kurs_nr = books.index(book_filename) + 1 if book_filename in books else 0
        books_config = _load_books_config()
        meta = books_config.get(book_filename, {})
        diff = meta.get('difficulty', '')
        rat = meta.get('rating', 0)
        stars = ('★' * rat + '☆' * (10 - rat)) if rat else ''
        pct = f' ({pos * 100 // total}%)' if total else ''

        embed = discord.Embed(title=f'📖 Training: {name} ({kurs_nr})', color=0x7fa650)
        embed.add_field(name='Fortschritt', value=f'{pos}/{total} Linien{pct}', inline=True)
        if diff:
            embed.add_field(name='Schwierigkeit',
                            value=f'{diff}  {stars}' if stars else diff, inline=True)
        embed.add_field(name='Nächster Schritt',
                        value='`/next` `/next 5` `/next 10`', inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    if buch == 0:
        _clear_user_training(user_id)
        await interaction.followup.send('🔓 Training beendet.', ephemeral=True)
        return

    # Buch validieren
    books = _list_pgn_files()
    if not books:
        await interaction.followup.send('⚠️ Kein books-Ordner.', ephemeral=True)
        return
    if buch < 1 or buch > len(books):
        await interaction.followup.send(
            f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die Liste.', ephemeral=True)
        return

    book_filename = books[buch - 1]
    # Aktuelle Position beibehalten falls selbes Buch
    training = _get_user_training(user_id)
    if training and training.get('book') == book_filename:
        pos = training['position']
    else:
        pos = 0

    _set_user_training(user_id, book_filename, pos)

    # Info anzeigen
    all_lines = load_all_lines()
    total = sum(1 for lid, _ in all_lines if lid.startswith(book_filename + ':'))
    name = _clean_book_name(book_filename)
    books_config = _load_books_config()
    meta = books_config.get(book_filename, {})
    diff = meta.get('difficulty', '')
    rat = meta.get('rating', 0)
    stars = ('★' * rat + '☆' * (10 - rat)) if rat else ''

    embed = discord.Embed(title=f'📖 Training: {name} ({buch})', color=0x7fa650)
    embed.add_field(name='Fortschritt', value=f'{pos}/{total} Linien', inline=True)
    if diff:
        embed.add_field(name='Schwierigkeit',
                        value=f'{diff}  {stars}' if stars else diff, inline=True)
    embed.add_field(name='Nächster Schritt',
                    value='`/next` `/next 5` `/next 10`', inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


async def _cmd_next(interaction: discord.Interaction, anzahl: int = 1):
    await interaction.response.defer(ephemeral=True)
    user_id = interaction.user.id
    anzahl = max(1, min(anzahl, 20))

    training = _get_user_training(user_id)
    if not training:
        await interaction.followup.send(
            '⚠️ Kein Trainingsbuch gewählt. Nutze `/train <buch>` zuerst.',
            ephemeral=True)
        return

    book_filename = training['book']
    position = training.get('position', 0)

    results = pick_sequential_lines(book_filename, position, anzahl)
    if not results:
        name = _clean_book_name(book_filename)
        # Position auf 0 zurücksetzen
        _set_user_training(user_id, book_filename, 0)
        await interaction.followup.send(
            f'✅ Alle Linien in **{name}** durchgearbeitet! '
            f'Nutze `/train` erneut zum Zurücksetzen oder wähle ein neues Buch.',
            ephemeral=True)
        return

    # Position updaten
    new_position = position + len(results)
    _set_user_training(user_id, book_filename, new_position)

    # Puzzles aufbereiten (wie in post_puzzle)
    books_config = _load_books_config()
    meta = books_config.get(book_filename, {})
    diff = meta.get('difficulty', '')
    rating = meta.get('rating', 0)

    puzzles = []
    for line_id, original_game in results:
        game = _trim_to_training_position(original_game)
        context = original_game if game is not original_game else None
        puzzles.append((game, context, diff, rating, line_id))

    # Upload (Studien-Reuse wie bei /puzzle)
    reuse_study_id = _get_user_study_id(user_id)
    base_count, base_total = _get_user_puzzle_count(user_id)

    upload_pairs = [(g, c) for g, c, _, _, _ in puzzles]
    urls = await _upload_puzzles_async(upload_pairs, reuse_study_id=reuse_study_id)

    # Studie-ID + Zähler speichern
    first_url = urls[0] if urls else None
    sid = _extract_study_id(first_url) if first_url else None
    if sid:
        _set_user_study_id(user_id, sid,
                           base_count + len(puzzles),
                           base_total + len(puzzles))

    # DM senden
    dm = await interaction.user.create_dm()
    all_book_lines = load_all_lines()
    total_in_book = sum(1 for lid, _ in all_book_lines
                        if lid.startswith(book_filename + ':'))

    puzzle_count = 0
    for i, (game, context, d, r, lid) in enumerate(puzzles):
        puzzle_url = urls[i] if i < len(urls) else None
        is_chapter = context is None  # kein [%tqu] → Kapitel

        if is_chapter:
            # Kapitel: Züge offen anzeigen, keine Puzzle-Buttons
            h = dict(game.headers)
            chapter_name = h.get('White', h.get('Event', 'Kapitel'))
            embed = discord.Embed(
                title=f'📖 Kapitel: {chapter_name}',
                color=0x7fa650)
            embed.set_footer(
                text=f'📖 Training: {position + i + 1}/{total_in_book} · ID: {lid}')
            pgn_moves = _solution_pgn(game)
            if pgn_moves:
                embed.add_field(name='Züge', value=f'`{pgn_moves}`', inline=False)
            msg = await dm.send(embed=embed)
            if puzzle_url:
                await dm.send(f'[Auf Lichess ansehen]({puzzle_url})')
        else:
            puzzle_count += 1
            puzzle_num = base_count + puzzle_count
            puzzle_total = base_total + puzzle_count
            try:
                board = game.board()
                turn = board.turn
                img = await asyncio.to_thread(_render_board, board)
            except Exception:
                turn, img = None, None

            embed = build_puzzle_embed(game, turn=turn,
                                       puzzle_num=puzzle_num,
                                       puzzle_total=puzzle_total,
                                       difficulty=d, rating=r,
                                       line_id=lid)
            embed.set_footer(
                text=f'📖 Training: {position + i + 1}/{total_in_book} · ID: {lid}')

            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                msg = await dm.send(file=file, embed=embed)
            else:
                msg = await dm.send(embed=embed)
            _register_puzzle_msg(msg.id, lid)
            await msg.edit(view=_fresh_button_view())

            # PGN-Lösung, Prelude, Lichess-Link
            await _send_puzzle_followups(dm, game, context, puzzle_url, lid)

    if puzzle_count:
        stats.inc(user_id, 'puzzles', puzzle_count)
    name = _clean_book_name(book_filename)
    await interaction.followup.send(
        f'✅ {len(results)} Linie(n) aus **{name}** per DM gesendet '
        f'({new_position}/{total_in_book}).',
        ephemeral=True)


async def _cmd_endless(bot, interaction: discord.Interaction, buch: int = 0):
    user_id = interaction.user.id
    log.info('/endless von %s: buch=%d', interaction.user, buch)

    # Toggle: wenn bereits aktiv → stoppen
    if is_endless(user_id):
        count = stop_endless(user_id)
        await interaction.response.send_message(
            f'⏹️ Endless-Modus beendet! **{count}** Puzzle(s) gelöst.',
            ephemeral=True)
        return

    # Buch validieren
    book_filename = None
    if buch > 0:
        books = _list_pgn_files()
        if books:
            if 1 <= buch <= len(books):
                book_filename = books[buch - 1]
            else:
                await interaction.response.send_message(
                    f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die verfügbaren Bücher.',
                    ephemeral=True)
                return

    start_endless(user_id, book_filename)
    await interaction.response.defer(ephemeral=True)

    try:
        await post_next_endless(bot, user_id)
        book_info = ''
        if book_filename:
            name = _clean_book_name(book_filename)
            book_info = f' (Buch: **{name}**)'
        await interaction.followup.send(
            f'♾️ Endless-Modus gestartet{book_info}! '
            f'Erstes Puzzle per DM gesendet.\n'
            f'Nach jeder ✅/❌ kommt sofort das nächste. '
            f'Nochmal `/endless` zum Stoppen.',
            ephemeral=True)
    except Exception as e:
        stop_endless(user_id)
        await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)


async def _cmd_ignore_kapitel(
    interaction: discord.Interaction,
    buch: int = 0,
    kapitel: int = 0,
    aktion: discord.app_commands.Choice[str] = None,
):
    await interaction.response.defer(ephemeral=True)

    # Ohne Parameter → Liste aller ignorierten Kapitel
    if buch == 0 and kapitel == 0:
        ignored = sorted(_load_chapter_ignore_list())
        if not ignored:
            await interaction.followup.send(
                'Keine Kapitel ignoriert.', ephemeral=True)
            return
        lines = ['**Ignorierte Kapitel:**']
        for entry in ignored:
            fname, _, prefix = entry.partition(':')
            name = _clean_book_name(fname)
            lines.append(f'• `{name}` — Kapitel {prefix}')
        await interaction.followup.send('\n'.join(lines), ephemeral=True)
        return

    if buch == 0 or kapitel == 0:
        await interaction.followup.send(
            '⚠️ Bitte sowohl `buch` als auch `kapitel` angeben.', ephemeral=True)
        return

    # Buch auflösen
    books = _list_pgn_files()
    if not books:
        await interaction.followup.send(
            f'⚠️ Books-Verzeichnis fehlt: `{BOOKS_DIR}`', ephemeral=True)
        return
    if not 1 <= buch <= len(books):
        await interaction.followup.send(
            f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die verfügbaren Bücher.',
            ephemeral=True)
        return
    book_filename = books[buch - 1]
    book_name = _clean_book_name(book_filename)

    # Chapter-Präfix im tatsächlichen Format finden
    prefix = _find_chapter_prefix(book_filename, kapitel)
    if prefix is None:
        chapters = _list_chapters(book_filename)
        sample = ', '.join(sorted(chapters)[:10])
        more = f' (von {len(chapters)})' if len(chapters) > 10 else ''
        await interaction.followup.send(
            f'⚠️ Kapitel {kapitel} in **{book_name}** nicht gefunden.\n'
            f'Verfügbare Kapitel{more}: `{sample}`',
            ephemeral=True)
        return

    action_value = aktion.value if aktion else 'ignore'
    chapter_count = _list_chapters(book_filename).get(prefix, 0)

    if action_value == 'unignore':
        unignore_chapter(book_filename, prefix)
        log.info('Kapitel reaktiviert: %s:%s', book_filename, prefix)
        await interaction.followup.send(
            f'♻️ Kapitel **{prefix}** in **{book_name}** wieder aktiviert '
            f'({chapter_count} Linien).',
            ephemeral=True)
    else:
        ignore_chapter(book_filename, prefix)
        log.info('Kapitel ignoriert: %s:%s', book_filename, prefix)
        await interaction.followup.send(
            f'🚮 Kapitel **{prefix}** in **{book_name}** ignoriert '
            f'({chapter_count} Linien werden nicht mehr gepostet).',
            ephemeral=True)


def setup(bot: discord.ext.commands.Bot):
    """Registriert alle Puzzle-Commands auf dem Bot."""
    tree = bot.tree

    @tree.command(name='puzzle', description='Puzzle(s) aus den Büchern posten')
    @discord.app_commands.describe(
        anzahl='Anzahl Puzzles (1–20, Standard: 1)',
        buch='Buchnummer aus /kurs (Standard: alle Bücher)',
        id='Puzzle-ID (z.B. datei.pgn:123) – zeigt genau dieses Puzzle',
        user='Puzzle an diesen User schicken (Standard: an dich selbst)',
    )
    async def cmd_puzzle(interaction: discord.Interaction, anzahl: int = 1, buch: int = 0,
                         id: str = '', user: discord.Member | None = None):
        await _cmd_puzzle(interaction, anzahl, buch, id, user)

    @tree.command(name='kurs', description='Puzzle-Bücher anzeigen; optional Details zu einem Buch')
    @discord.app_commands.describe(
        buch='Buchnummer aus /kurs für Detailansicht mit allen Kapiteln',
    )
    async def cmd_buecher(interaction: discord.Interaction, buch: int = 0):
        await _cmd_buecher(interaction, buch)

    @tree.command(name='train', description='Buch für sequentielles Training auswählen')
    @discord.app_commands.describe(
        buch='Buchnummer aus /kurs (0 = Training beenden, leer = Status anzeigen)',
    )
    async def cmd_train(interaction: discord.Interaction, buch: int = None):
        await _cmd_train(interaction, buch)

    @tree.command(name='next', description='Nächste Linie(n) aus dem Trainingsbuch')
    @discord.app_commands.describe(
        anzahl='Anzahl Linien (Standard: 1, max 20)',
    )
    async def cmd_next(interaction: discord.Interaction, anzahl: int = 1):
        await _cmd_next(interaction, anzahl)

    @tree.command(name='endless', description='Endlos-Puzzle-Modus starten/stoppen')
    @discord.app_commands.describe(
        buch='Buchnummer aus /kurs (Standard: alle Bücher)',
    )
    async def cmd_endless(interaction: discord.Interaction, buch: int = 0):
        await _cmd_endless(bot, interaction, buch)

    @tree.command(name='ignore_kapitel',
                  description='Ein ganzes Kapitel ignorieren oder Liste anzeigen (Admin)')
    @discord.app_commands.describe(
        buch='Buchnummer aus /kurs',
        kapitel='Kapitel-Nummer (z.B. 3)',
        aktion='ignore = ignorieren · unignore = wieder aktivieren · list = ohne Parameter zeigen',
    )
    @discord.app_commands.choices(aktion=[
        discord.app_commands.Choice(name='ignore', value='ignore'),
        discord.app_commands.Choice(name='unignore', value='unignore'),
    ])
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_ignore_kapitel(
        interaction: discord.Interaction,
        buch: int = 0,
        kapitel: int = 0,
        aktion: discord.app_commands.Choice[str] = None,
    ):
        await _cmd_ignore_kapitel(interaction, buch, kapitel, aktion)
