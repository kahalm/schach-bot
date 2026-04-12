"""Puzzle-Funktionen: Board-Rendering, Lichess-Upload, PGN-Laden, Slash-Commands."""

import asyncio
import io
import json
import stats
import logging
import os
import random
import re
import tempfile
import time as _time_mod
from collections import defaultdict
from datetime import time, date as _date, datetime as _datetime

import chess
import chess.pgn
import discord
import requests
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM

log = logging.getLogger('schach-bot')

# Puzzle-Nachrichten-IDs für Reaction-Tracking (in-memory, reicht da Reactions
# typischerweise kurz nach dem Posten kommen)
_puzzle_msg_ids: dict[int, str] = {}   # msg_id → line_id
_PUZZLE_REACTIONS = {'✅', '❌', '👍', '👎', '🚮'}
IGNORE_FILE = 'puzzle_ignore.json'

# Endless-Modus: aktive Sessions (in-memory)
_endless_sessions: dict[int, dict] = {}   # user_id → {'book': str|None, 'count': int}

def _register_puzzle_msg(msg_id: int, line_id: str):
    _puzzle_msg_ids[msg_id] = line_id

def is_puzzle_message(msg_id: int) -> bool:
    return msg_id in _puzzle_msg_ids

def get_puzzle_line_id(msg_id: int) -> str | None:
    return _puzzle_msg_ids.get(msg_id)

def _load_ignore_list() -> set[str]:
    try:
        with open(IGNORE_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def _save_ignore_list(ignored: set[str]):
    with open(IGNORE_FILE, 'w') as f:
        json.dump(sorted(ignored), f, indent=2)

def ignore_puzzle(line_id: str):
    ignored = _load_ignore_list()
    ignored.add(line_id)
    _save_ignore_list(ignored)

def unignore_puzzle(line_id: str):
    ignored = _load_ignore_list()
    ignored.discard(line_id)
    _save_ignore_list(ignored)


# --- Endless-Modus ---

def start_endless(user_id: int, book_filename: str | None = None):
    _endless_sessions[user_id] = {'book': book_filename, 'count': 0}

def stop_endless(user_id: int) -> int:
    """Session beenden, gibt Anzahl gelöster Puzzles zurück."""
    session = _endless_sessions.pop(user_id, None)
    return session['count'] if session else 0

def is_endless(user_id: int) -> bool:
    return user_id in _endless_sessions


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
            log.warning('Endless-Ende-DM fehlgeschlagen: %s', e)
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
    loop = asyncio.get_running_loop()
    puzzle_url = await loop.run_in_executor(
        None, lambda: upload_to_lichess(game, context_game=context,
                                         reuse_study_id=reuse_study_id))

    # Studie-ID speichern
    if puzzle_url:
        parts = puzzle_url.rstrip('/').split('/')
        if 'study' in parts:
            sidx = parts.index('study')
            sid = parts[sidx + 1] if sidx + 1 < len(parts) else ''
            if sid:
                base_count, base_total = _get_user_puzzle_count(user_id)
                _set_user_study_id(user_id, sid, base_count + 1, base_total + 1)

    session['count'] += 1

    # DM senden
    try:
        user = await bot.fetch_user(user_id)
        dm = await user.create_dm()
    except Exception as e:
        log.warning('Endless-DM fehlgeschlagen: %s', e)
        return

    try:
        board = game.board()
        turn = board.turn
        img = _render_board(board)
    except Exception:
        turn, img = None, None

    embed = build_puzzle_embed(game, turn=turn, difficulty=diff, rating=rating)
    embed.set_footer(text=f'♾️ Endless-Modus · Puzzle #{session["count"]}')

    if img:
        file = discord.File(img, filename='board.png')
        embed.set_image(url='attachment://board.png')
        msg = await dm.send(file=file, embed=embed)
    else:
        msg = await dm.send(embed=embed)

    _register_puzzle_msg(msg.id, line_id)
    for emoji in ('✅', '❌', '👍', '👎'):
        await msg.add_reaction(emoji)

    # Lösung als Spoiler
    exporter = chess.pgn.StringExporter(headers=False, variations=True, comments=False)
    pgn_moves = game.accept(exporter).strip()
    if pgn_moves:
        await dm.send(f'Lösung: ||`{pgn_moves}`||')
    if context:
        prelude = _prelude_pgn(context, game)
        if prelude:
            await dm.send(f'Ganze Partie: ||`{prelude}`||')
    if puzzle_url:
        await dm.send(f'[Klickbares Rätsel]({puzzle_url})')

    stats.inc(user_id, 'puzzles', 1)


# --- Config (aus Umgebung) ---

LICHESS_TOKEN     = os.getenv('LICHESS_TOKEN', '')
BOOKS_DIR         = os.getenv('BOOKS_DIR', 'books')
PUZZLE_STUDY_ID   = os.getenv('PUZZLE_STUDY_ID', '')
PUZZLE_HOUR       = int(os.getenv('PUZZLE_HOUR', '9'))
PUZZLE_MINUTE     = int(os.getenv('PUZZLE_MINUTE', '0'))
PUZZLE_STATE_FILE = 'puzzle_state.json'
USER_STUDIES_FILE = 'user_studies.json'
LICHESS_COOLDOWN_FILE = 'lichess_cooldown.json'
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
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        _piece_cache[code] = _svg_to_pil(resp.content, size)
        log.info('Figur geladen: %s', code)
    return _piece_cache[code]

def _label_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in ['C:/Windows/Fonts/arialbd.ttf', 'C:/Windows/Fonts/arial.ttf']:
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
    if os.path.exists(PUZZLE_STATE_FILE):
        with open(PUZZLE_STATE_FILE) as f:
            return json.load(f)
    return {'posted': []}


def save_puzzle_state(state: dict):
    with open(PUZZLE_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def _load_user_studies() -> dict:
    try:
        with open(USER_STUDIES_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_user_studies(data: dict):
    with open(USER_STUDIES_FILE, 'w') as f:
        json.dump(data, f, indent=2)

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

def _load_books_config() -> dict:
    """Lädt books.json mit Metadaten (z.B. difficulty) pro PGN-Datei."""
    p = os.path.join(BOOKS_DIR, 'books.json')
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

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
    book_lines = [(lid, g) for lid, g in all_lines
                  if lid.startswith(book_filename + ':') and lid not in ignored]
    end = min(start + count, len(book_lines))
    return book_lines[start:end]

def load_all_lines() -> list[tuple[str, chess.pgn.Game]]:
    """Alle Linien aus .pgn-Dateien in BOOKS_DIR laden."""
    lines = []
    if not os.path.isdir(BOOKS_DIR):
        log.error('Books-Verzeichnis nicht gefunden: %s', BOOKS_DIR)
        return lines
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
            # Überspringen wenn keine Züge vorhanden (z.B. Einleitungskapitel)
            if not game.variations:
                continue
            round_header = game.headers.get('Round', '')
            line_id = f"{filename}:{round_header}"
            lines.append((line_id, game))
    return lines

def pick_random_lines(count: int = 1,
                      book_filename: str | None = None,
                      ) -> list[tuple[str, chess.pgn.Game]]:
    """Bis zu `count` zufällige noch nicht gepostete Linien wählen.

    book_filename – nur Linien aus dieser Datei (None = alle Bücher).
    """
    all_lines = load_all_lines()
    ignored = _load_ignore_list()
    if book_filename:
        all_lines = [(lid, g) for lid, g in all_lines
                     if lid.startswith(book_filename + ':')]
    all_lines = [(lid, g) for lid, g in all_lines if lid not in ignored]
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

def _prelude_pgn(context: chess.pgn.Game, puzzle: chess.pgn.Game) -> str:
    """Züge aus context VOR der Puzzle-Startstellung exportieren (ohne Lösung)."""
    # Nur Brettposition vergleichen (ohne Halbzug-/Zugzähler)
    target_board = puzzle.board().board_fen() + (' w ' if puzzle.board().turn == chess.WHITE else ' b ')
    prelude = chess.pgn.Game()
    prelude.headers.clear()
    node_src = context
    node_dst = prelude
    while node_src.variations:
        child = node_src.variations[0]
        cb = child.board()
        child_key = cb.board_fen() + (' w ' if cb.turn == chess.WHITE else ' b ')
        if child_key == target_board:
            break
        node_dst = node_dst.add_variation(child.move)
        node_src = child
    exporter = chess.pgn.StringExporter(
        headers=False, variations=False, comments=False)
    return prelude.accept(exporter).strip()

def _trim_to_training_position(game: chess.pgn.Game) -> chess.pgn.Game:
    """Spiel auf erste [%tqu]-Stellung kürzen.
    Ohne [%tqu]-Annotation → Original unverändert zurückgeben."""
    node = game
    while True:
        if '[%tqu' in (node.comment or ''):
            break
        if not node.variations:
            return game  # kein Trainingskommentar → Original
        node = node.variations[0]

    if node is game:
        return game  # [%tqu] schon im Root-Kommentar → keine Kürzung nötig

    tqu_board = node.board()
    new_game = chess.pgn.Game()
    new_game.setup(tqu_board)
    # Metadaten übernehmen – FEN und SetUp NICHT überschreiben (setup() hat sie korrekt gesetzt)
    for key, val in game.headers.items():
        if key not in ('FEN', 'SetUp'):
            new_game.headers[key] = val
    # [%tqu]-Kommentar nicht weitergeben – wird beim Export sowieso entfernt
    new_game.comment = ''

    def _copy(src: chess.pgn.GameNode, dst: chess.pgn.GameNode,
              board: chess.Board):
        """Baum ab src nach dst kopieren; board ist die Stellung bei dst."""
        for var in src.variations:
            if var.move not in board.legal_moves:
                continue  # illegale Varianten (Parsing-Fehler) überspringen
            child = dst.add_variation(
                var.move,
                comment=var.comment,
                starting_comment=var.starting_comment,
                nags=list(var.nags),
            )
            next_board = board.copy()
            next_board.push(var.move)
            _copy(var, child, next_board)

    _copy(node, new_game, tqu_board)
    return new_game

def _clean_pgn_for_lichess(pgn_text: str) -> str:
    """ChessBase-spezifische Annotationen entfernen, die Lichess nicht versteht."""
    # [%tqu ...] entfernen
    pgn_text = re.sub(r'\[%tqu\b[^\]]*\]', '', pgn_text)
    # leere Kommentare {} entfernen
    pgn_text = re.sub(r'\{\s*\}', '', pgn_text)
    return pgn_text

_LICHESS_COOLDOWN_SECS = 3600  # 1 Stunde


class LichessRateLimitError(Exception):
    pass


def _lichess_cooldown_until() -> float:
    """Liest den gespeicherten Cooldown-Zeitstempel (Unix-Zeit). 0 = kein Cooldown."""
    try:
        with open(LICHESS_COOLDOWN_FILE) as f:
            return float(json.load(f).get('until', 0))
    except (FileNotFoundError, ValueError, KeyError):
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
    with open(LICHESS_COOLDOWN_FILE, 'w') as f:
        json.dump({'until': until}, f)
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
                      reuse_study_id: str | None = None) -> str | None:
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
        exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
        pgn_text = game.accept(exporter)
    except Exception as e:
        log.error('PGN-Export fehlgeschlagen: %s', e)
        return None
    pgn_text = _clean_pgn_for_lichess(pgn_text)

    h = dict(game.headers)
    line_name  = h.get('White', h.get('Event', 'Puzzle'))
    event_name = h.get('Event', 'Puzzle')
    today      = _date.today().strftime('%d.%m.%Y')
    study_name = f'{event_name} – {today}'
    if len(study_name) > 100:
        study_name = study_name[:97] + '...'

    # Kontext-PGN vorbereiten (2. Kapitel: vollständiges Originalspiel)
    context_pgn = None
    context_name = None
    if context_game is not None:
        try:
            ctx_exp = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
            context_pgn = context_game.accept(ctx_exp)
            context_pgn = _clean_pgn_for_lichess(context_pgn)
            ch = dict(context_game.headers)
            ctx_title = ch.get('White', ch.get('Event', 'Partie'))
            if len(ctx_title) > 70:
                ctx_title = ctx_title[:67] + '...'
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
                    timeout=15,
                )
                r.raise_for_status()
                study_id = r.json().get('id', '')
                # Leeres Auto-Kapitel merken – ID aus ChapterURL extrahieren
                pgn_resp = _lichess_request(
                    'GET', f'https://lichess.org/api/study/{study_id}.pgn',
                    headers=auth_headers,
                    timeout=10,
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
                    data={'pgn': pgn_text, 'name': line_name, 'mode': 'gamebook'},
                    headers=auth_headers,
                    timeout=15,
                )
                r2.raise_for_status()
                chapters = r2.json().get('chapters', [])
                chapter_id = chapters[-1].get('id', '') if chapters else ''
                log.info('Gamebook-Kapitel importiert: %s (chapter_id=%s)', line_name, chapter_id)

                # Studie voll → neue anlegen und nochmal versuchen
                if not chapter_id and reuse_study_id:
                    log.info('Studie %s voll – lege neue an.', reuse_study_id)
                    return upload_to_lichess(game, context_game=context_game, reuse_study_id=None)

                # Kapitel 2: vollständiges Originalspiel (nur wenn vorhanden)
                if context_pgn:
                    r3 = _lichess_request(
                        'POST', f'https://lichess.org/api/study/{study_id}/import-pgn',
                        data={'pgn': context_pgn, 'name': context_name, 'mode': 'normal'},
                        headers=auth_headers,
                        timeout=15,
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
                        timeout=10,
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
            timeout=15,
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
                headers=auth_headers, timeout=15,
            )
            r.raise_for_status()
            study_id = r.json().get('id', '')
            if not study_id:
                return None

            # Leeres Auto-Kapitel merken
            pgn_resp = _lichess_request(
                'GET', f'https://lichess.org/api/study/{study_id}.pgn',
                headers=auth_headers, timeout=10,
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
                exp  = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
                pgn  = _clean_pgn_for_lichess(game.accept(exp))
                h    = dict(game.headers)
                name = h.get('White', h.get('Event', 'Puzzle'))[:70]
                r_ch = _lichess_request(
                    'POST', f'https://lichess.org/api/study/{study_id}/import-pgn',
                    data={'pgn': pgn, 'name': name, 'mode': 'gamebook'},
                    headers=auth_headers, timeout=15,
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
                    ctx_exp = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
                    ctx_pgn = _clean_pgn_for_lichess(context.accept(ctx_exp))
                    ch      = dict(context.headers)
                    ctx_name = f'Partie: {ch.get("White", "Partie")[:64]}'
                    _lichess_request(
                        'POST', f'https://lichess.org/api/study/{study_id}/import-pgn',
                        data={'pgn': ctx_pgn, 'name': ctx_name, 'mode': 'normal'},
                        headers=auth_headers, timeout=15,
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
                headers=auth_headers, timeout=10,
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
                       rating: int = 0) -> discord.Embed:
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

    embed.set_footer(text='🧩 Tägliches Puzzle')
    return embed

async def post_puzzle(channel, count: int = 1, book_idx: int = 0, user_id: int | None = None):
    """Puzzles auswählen, auf Lichess hochladen und posten.

    count    – Anzahl Puzzles (1–20).
    book_idx – 1-basierte Buchnummer aus /kurs (0 = alle Bücher).
    user_id  – Discord-User-ID; wenn gesetzt, wird die Tages-Studie wiederverwendet.
    """
    count = max(1, min(count, 20))

    # Buch bestimmen
    book_filename = None
    if book_idx > 0:
        if os.path.isdir(BOOKS_DIR):
            books = sorted(f for f in os.listdir(BOOKS_DIR) if f.endswith('.pgn'))
            if 1 <= book_idx <= len(books):
                book_filename = books[book_idx - 1]
            else:
                await channel.send(
                    f'⚠️ Buch {book_idx} nicht gefunden. `/kurs` zeigt die verfügbaren Bücher.'
                )
                return

    results = pick_random_lines(count, book_filename)
    if not results:
        await channel.send('⚠️ Keine Puzzle-Linien gefunden. Bitte .pgn-Dateien in den `books/`-Ordner legen.')
        return

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
    loop = asyncio.get_running_loop()
    if len(upload_pairs) == 1:
        u = await loop.run_in_executor(
            None, lambda: upload_to_lichess(upload_pairs[0][0], context_game=upload_pairs[0][1],
                                            reuse_study_id=reuse_study_id)
        )
        urls = [u] if u else []
    else:
        urls = await loop.run_in_executor(
            None, lambda: upload_many_to_lichess(upload_pairs, reuse_study_id=reuse_study_id)
        )

    # Studie-ID für diesen User+Tag speichern
    first_url = urls[0] if urls else None
    if first_url and user_id:
        parts = first_url.rstrip('/').split('/')
        if 'study' in parts:
            sidx = parts.index('study')
            sid  = parts[sidx + 1] if sidx + 1 < len(parts) else ''
            if sid:
                _set_user_study_id(user_id, sid, base_count + len(puzzles), base_total + len(puzzles))

    # Thread-Name vom ersten Puzzle
    h = dict(puzzles[0][0].headers)
    event = h.get('Event', 'Puzzle')
    today = _date.today().strftime('%d.%m.%Y')
    thread_name = f'{event} – {today}'
    if len(thread_name) > 100:
        thread_name = thread_name[:97] + '...'

    # Ziel: Thread (Server) oder direkt (DM)
    is_dm = isinstance(channel, discord.DMChannel)
    if is_dm:
        target = channel
    else:
        target = await channel.create_thread(
            name=thread_name,
            type=discord.ChannelType.public_thread,
            auto_archive_duration=1440,
        )

    # Alle Puzzles als einzelne Bilder posten
    for i, (game, context, diff, rating, lid) in enumerate(puzzles):
        puzzle_url = urls[i] if i < len(urls) else None
        puzzle_num   = (base_count + i + 1) if user_id else 0
        puzzle_total = (base_total + i + 1) if user_id else 0
        try:
            board = game.board()
            turn  = board.turn
            img   = _render_board(board)
        except Exception as e:
            log.warning('Board-Render fehlgeschlagen: %s', e)
            turn = None
            img  = None

        embed = build_puzzle_embed(game, turn=turn, puzzle_num=puzzle_num, puzzle_total=puzzle_total, difficulty=diff, rating=rating)
        if img:
            file = discord.File(img, filename='board.png')
            embed.set_image(url='attachment://board.png')
            msg = await target.send(file=file, embed=embed)
        else:
            msg = await target.send(embed=embed)
        _register_puzzle_msg(msg.id, lid)
        for emoji in ('✅', '❌', '👍', '👎'):
            await msg.add_reaction(emoji)

        # PGN-Lösung als Spoiler posten
        exporter = chess.pgn.StringExporter(
            headers=False, variations=True, comments=False)
        pgn_moves = game.accept(exporter).strip()
        if pgn_moves:
            await target.send(f'Lösung: ||`{pgn_moves}`||')
        if context:
            prelude = _prelude_pgn(context, game)
            if prelude:
                await target.send(f'Ganze Partie: ||`{prelude}`||')
        if puzzle_url:
            await target.send(f'[Klickbares Rätsel]({puzzle_url})')

    if user_id:
        stats.inc(user_id, 'puzzles', len(puzzles))


# ---------------------------------------------------------------------------
# Slash-Commands registrieren
# ---------------------------------------------------------------------------

def setup(bot: discord.ext.commands.Bot):
    """Registriert alle Puzzle-Commands auf dem Bot."""
    tree = bot.tree

    @tree.command(name='puzzle', description='Puzzle(s) aus den Büchern posten')
    @discord.app_commands.describe(
        anzahl='Anzahl Puzzles (1–20, Standard: 1)',
        buch='Buchnummer aus /kurs (Standard: alle Bücher)',
    )
    async def cmd_puzzle(interaction: discord.Interaction, anzahl: int = 1, buch: int = 0):
        log.info('/puzzle von %s: anzahl=%d buch=%d', interaction.user, anzahl, buch)
        await interaction.response.defer(ephemeral=True)
        try:
            dm = await interaction.user.create_dm()
            await post_puzzle(dm, count=anzahl, book_idx=buch, user_id=interaction.user.id)
            await interaction.followup.send(f'✅ {anzahl} Puzzle(s) wurde(n) dir per DM gesendet.', ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)


    @tree.command(name='kurs', description='Alle verfügbaren Puzzle-Bücher anzeigen')
    async def cmd_buecher(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            all_lines = load_all_lines()
            posted    = set(load_puzzle_state().get('posted', []))

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

            books_config = _load_books_config()
            embed = discord.Embed(title='📚 Puzzle-Bücher', color=0x7fa650)
            for i, book in enumerate(sorted(total_per_book), 1):
                name  = book.removesuffix('_firstkey.pgn').removesuffix('.pgn')
                total = total_per_book[book]
                done  = posted_per_book[book]
                meta  = books_config.get(book, {})
                diff  = meta.get('difficulty', '')
                rat   = meta.get('rating', 0)
                stars = '★' * rat + '☆' * (10 - rat) if rat else ''
                info  = f'{done}/{total} gepostet'
                if diff:
                    info += f'\n{diff}  {stars}' if stars else f'\n{diff}'
                embed.add_field(name=f'{i}: {name}', value=info, inline=False)

            total_all = sum(total_per_book.values())
            done_all  = sum(posted_per_book.values())
            embed.set_footer(text=f'Gesamt: {done_all}/{total_all} Linien gepostet')
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)

    @tree.command(name='train', description='Buch für sequentielles Training auswählen')
    @discord.app_commands.describe(
        buch='Buchnummer aus /kurs (0 = Training beenden, leer = Status anzeigen)',
    )
    async def cmd_train(interaction: discord.Interaction, buch: int = None):
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
            name = book_filename.removesuffix('_firstkey.pgn').removesuffix('.pgn')
            books_config = _load_books_config()
            meta = books_config.get(book_filename, {})
            diff = meta.get('difficulty', '')
            rat = meta.get('rating', 0)
            stars = ('★' * rat + '☆' * (10 - rat)) if rat else ''
            pct = f' ({pos * 100 // total}%)' if total else ''

            embed = discord.Embed(title=f'📖 Training: {name}', color=0x7fa650)
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
        if not os.path.isdir(BOOKS_DIR):
            await interaction.followup.send('⚠️ Kein books-Ordner.', ephemeral=True)
            return
        books = sorted(f for f in os.listdir(BOOKS_DIR) if f.endswith('.pgn'))
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
        name = book_filename.removesuffix('_firstkey.pgn').removesuffix('.pgn')
        books_config = _load_books_config()
        meta = books_config.get(book_filename, {})
        diff = meta.get('difficulty', '')
        rat = meta.get('rating', 0)
        stars = ('★' * rat + '☆' * (10 - rat)) if rat else ''

        embed = discord.Embed(title=f'📖 Training: {name}', color=0x7fa650)
        embed.add_field(name='Fortschritt', value=f'{pos}/{total} Linien', inline=True)
        if diff:
            embed.add_field(name='Schwierigkeit',
                            value=f'{diff}  {stars}' if stars else diff, inline=True)
        embed.add_field(name='Nächster Schritt',
                        value='`/next` `/next 5` `/next 10`', inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name='next', description='Nächste Linie(n) aus dem Trainingsbuch')
    @discord.app_commands.describe(
        anzahl='Anzahl Linien (Standard: 1, max 20)',
    )
    async def cmd_next(interaction: discord.Interaction, anzahl: int = 1):
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
            name = book_filename.removesuffix('_firstkey.pgn').removesuffix('.pgn')
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
        loop = asyncio.get_running_loop()
        if len(upload_pairs) == 1:
            u = await loop.run_in_executor(
                None, lambda: upload_to_lichess(
                    upload_pairs[0][0], context_game=upload_pairs[0][1],
                    reuse_study_id=reuse_study_id))
            urls = [u] if u else []
        else:
            urls = await loop.run_in_executor(
                None, lambda: upload_many_to_lichess(
                    upload_pairs, reuse_study_id=reuse_study_id))

        # Studie-ID + Zähler speichern
        first_url = urls[0] if urls else None
        if first_url:
            parts = first_url.rstrip('/').split('/')
            if 'study' in parts:
                sidx = parts.index('study')
                sid = parts[sidx + 1] if sidx + 1 < len(parts) else ''
                if sid:
                    _set_user_study_id(user_id, sid,
                                       base_count + len(puzzles),
                                       base_total + len(puzzles))

        # DM senden
        dm = await interaction.user.create_dm()
        all_book_lines = load_all_lines()
        total_in_book = sum(1 for lid, _ in all_book_lines
                            if lid.startswith(book_filename + ':'))

        for i, (game, context, d, r, lid) in enumerate(puzzles):
            puzzle_url = urls[i] if i < len(urls) else None
            puzzle_num = base_count + i + 1
            puzzle_total = base_total + i + 1
            try:
                board = game.board()
                turn = board.turn  # Lichess spielt den 1. Zug als Setup
                img = _render_board(board)
            except Exception:
                turn, img = None, None

            embed = build_puzzle_embed(game, turn=turn,
                                       puzzle_num=puzzle_num,
                                       puzzle_total=puzzle_total,
                                       difficulty=d, rating=r)
            # Fortschrittsanzeige im Footer
            embed.set_footer(
                text=f'📖 Training: {position + i + 1}/{total_in_book}')

            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                msg = await dm.send(file=file, embed=embed)
            else:
                msg = await dm.send(embed=embed)
            _register_puzzle_msg(msg.id, lid)
            for emoji in ('✅', '❌', '👍', '👎'):
                await msg.add_reaction(emoji)

            # PGN-Lösung als Spoiler
            exporter = chess.pgn.StringExporter(
                headers=False, variations=True, comments=False)
            pgn_moves = game.accept(exporter).strip()
            if pgn_moves:
                await dm.send(f'Lösung: ||`{pgn_moves}`||')
            if context:
                prelude = _prelude_pgn(context, game)
                if prelude:
                    await dm.send(f'Ganze Partie: ||`{prelude}`||')
            if puzzle_url:
                await dm.send(f'[Klickbares Rätsel]({puzzle_url})')

        stats.inc(user_id, 'puzzles', len(puzzles))
        name = book_filename.removesuffix('_firstkey.pgn').removesuffix('.pgn')
        await interaction.followup.send(
            f'✅ {len(results)} Linie(n) aus **{name}** per DM gesendet '
            f'({new_position}/{total_in_book}).',
            ephemeral=True)

    @tree.command(name='endless', description='Endlos-Puzzle-Modus starten/stoppen')
    @discord.app_commands.describe(
        buch='Buchnummer aus /kurs (Standard: alle Bücher)',
    )
    async def cmd_endless(interaction: discord.Interaction, buch: int = 0):
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
            if os.path.isdir(BOOKS_DIR):
                books = sorted(f for f in os.listdir(BOOKS_DIR) if f.endswith('.pgn'))
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
                name = book_filename.removesuffix('_firstkey.pgn').removesuffix('.pgn')
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
