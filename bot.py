import sys
# cairocffi wirft OSError wenn Cairo-DLL fehlt – vor svglib/reportlab blockieren,
# damit rlPyCairo auf pycairo zurückfällt (pycairo bündelt Cairo in seinem Wheel).
try:
    import cairocffi  # noqa: F401
except (OSError, ImportError):
    sys.modules['cairocffi'] = None  # type: ignore[assignment]

import logging
import sys
from logging.handlers import RotatingFileHandler

# python-chess schreibt Parsing-Warnungen direkt auf stdout/stderr –
# nicht über das logging-Modul. Beide Streams filtern.
class _SuppressEmptyFen:
    _SUPPRESS = ('empty fen while parsing', 'illegal san:', 'no matching legal move', 'ambiguous san:')
    def __init__(self, stream): self._s = stream
    def write(self, s):
        if not any(p in s for p in self._SUPPRESS):
            try:
                self._s.write(s)
            except (UnicodeEncodeError, UnicodeDecodeError):
                self._s.write(s.encode('ascii', 'replace').decode('ascii'))
    def flush(self): self._s.flush()
    def __getattr__(self, n): return getattr(self._s, n)

sys.stdout = _SuppressEmptyFen(sys.stdout)
sys.stderr = _SuppressEmptyFen(sys.stderr)

# ---------------------------------------------------------------------------
# Rolling Log  (bot.log, max 1 MB, 5 Backups)
# ---------------------------------------------------------------------------

_log_fmt = logging.Formatter('%(asctime)s [%(levelname)-8s] %(message)s',
                              datefmt='%Y-%m-%d %H:%M:%S')

_file_handler = RotatingFileHandler(
    'bot.log', maxBytes=1_000_000, backupCount=5, encoding='utf-8'
)
_file_handler.setFormatter(_log_fmt)
_file_handler.setLevel(logging.DEBUG)

# Terminal: nur WARNING+ (z.B. Book-Lesefehler)
_term_handler = logging.StreamHandler(sys.stderr)
_term_handler.setFormatter(_log_fmt)
_term_handler.setLevel(logging.WARNING)

log = logging.getLogger('schach-bot')
log.setLevel(logging.DEBUG)
log.addHandler(_file_handler)
log.addHandler(_term_handler)
log.propagate = False

import discord
from discord.ext import tasks, commands
import requests
import chess
import chess.pgn
import io
import os
import json
import random
import re
import tempfile
from collections import defaultdict
from datetime import time, date as _date
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM

from dotenv import load_dotenv
load_dotenv()

DISCORD_TOKEN   = os.getenv('DISCORD_TOKEN')
STUDY_ID        = os.getenv('LICHESS_STUDY_ID', 'ndPgby4a')
CHANNEL_ID      = int(os.getenv('CHANNEL_ID', '0'))
POST_HOUR       = int(os.getenv('POST_HOUR', '8'))
POST_MINUTE     = int(os.getenv('POST_MINUTE', '0'))

LICHESS_TOKEN     = os.getenv('LICHESS_TOKEN', '')
BOOKS_DIR         = os.getenv('BOOKS_DIR', 'books')
PUZZLE_STUDY_ID   = os.getenv('PUZZLE_STUDY_ID', '')
PUZZLE_HOUR       = int(os.getenv('PUZZLE_HOUR', '9'))
PUZZLE_MINUTE     = int(os.getenv('PUZZLE_MINUTE', '0'))
PUZZLE_STATE_FILE = 'puzzle_state.json'
DM_STATE_FILE     = 'dm_state.json'

STATE_FILE = 'state.json'

# ---------------------------------------------------------------------------
# State  (welches Kapitel wurde zuletzt gepostet)
# ---------------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'chapter_index': 0}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# ---------------------------------------------------------------------------
# Lichess API
# ---------------------------------------------------------------------------

def fetch_all_chapters(study_id: str) -> str:
    """Alle Kapitel einer Lichess-Studie als PGN-Text holen."""
    url = f'https://lichess.org/api/study/{study_id}.pgn'
    resp = requests.get(url, params={'comments': 'true', 'variations': 'true', 'clocks': 'false'})
    resp.raise_for_status()
    return resp.text

def parse_games(pgn_text: str) -> list:
    """Mehrere PGN-Spiele aus einem Text lesen."""
    games = []
    stream = io.StringIO(pgn_text)
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        games.append(game)
    return games

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

def board_image(game: chess.pgn.Game) -> io.BytesIO:
    """PNG der Endstellung mit Lichess-Figuren (cburnett) und Koordinaten."""
    return _render_board(game.end().board())

# ---------------------------------------------------------------------------
# Discord-Embed formatieren
# ---------------------------------------------------------------------------

def build_embed(game: chess.pgn.Game) -> discord.Embed:
    h = dict(game.headers)

    chapter_name = h.get('ChapterName', h.get('Event', 'Partie'))
    # ChapterName kann sehr lang sein – kürzen
    if len(chapter_name) > 80:
        chapter_name = chapter_name[:77] + '...'

    study_name  = h.get('StudyName', '')
    chapter_url = h.get('ChapterURL', '')
    annotator   = h.get('Annotator', '')
    result      = h.get('Result', '*')

    # Intro-Kommentar des Kapitels
    comment = (game.comment or '').strip()
    if len(comment) > 450:
        comment = comment[:447] + '...'

    embed = discord.Embed(
        title=f'♟️ {chapter_name}',
        description=comment or None,
        color=0x4e9e4e,
        url=chapter_url or None,
    )

    if study_name:
        embed.add_field(name='📚 Studie', value=study_name, inline=False)

    embed.add_field(name='Ergebnis', value=result, inline=True)

    if annotator:
        embed.add_field(name='Annotator', value=annotator, inline=True)

    if chapter_url:
        embed.add_field(name='🔗 Lichess', value=f'[Kapitel öffnen]({chapter_url})', inline=False)

    embed.set_footer(text='♟️ Tägliche Schachpartie')
    return embed

# ---------------------------------------------------------------------------
# Posten
# ---------------------------------------------------------------------------

async def post_chapter(channel: discord.TextChannel, game: chess.pgn.Game):
    embed = build_embed(game)
    try:
        img  = board_image(game)
        file = discord.File(img, filename='board.png')
        embed.set_image(url='attachment://board.png')
        await channel.send(file=file, embed=embed)
    except Exception as e:
        log.warning('Kein Board-Bild: %s', e)
        await channel.send(embed=embed)

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
    if book_filename:
        all_lines = [(lid, g) for lid, g in all_lines
                     if lid.startswith(book_filename + ':')]
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

def upload_to_lichess(game: chess.pgn.Game,
                      context_game: chess.pgn.Game | None = None) -> str | None:
    """Neue Lichess-Studie anlegen, PGN importieren und Kapitel-URL zurückgeben.

    game         – gekürztes Spiel ab Trainingsposition (Gamebook-Kapitel 1)
    context_game – vollständiges Originalspiel als Kapitel 2 (optional,
                   nur sinnvoll wenn Trainingsposition nicht am Anfang liegt)
    """
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
            if PUZZLE_STUDY_ID:
                study_id = PUZZLE_STUDY_ID
                default_chapter_id = ''
            else:
                r = requests.post(
                    'https://lichess.org/api/study',
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
                pgn_resp = requests.get(
                    f'https://lichess.org/api/study/{study_id}.pgn',
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
                r2 = requests.post(
                    f'https://lichess.org/api/study/{study_id}/import-pgn',
                    data={'pgn': pgn_text, 'name': line_name, 'mode': 'gamebook'},
                    headers=auth_headers,
                    timeout=15,
                )
                r2.raise_for_status()
                chapters = r2.json().get('chapters', [])
                chapter_id = chapters[-1].get('id', '') if chapters else ''

                # Kapitel 2: vollständiges Originalspiel (nur wenn vorhanden)
                if context_pgn:
                    r3 = requests.post(
                        f'https://lichess.org/api/study/{study_id}/import-pgn',
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
                    rd = requests.delete(
                        f'https://lichess.org/api/study/{study_id}/{default_chapter_id}',
                        headers=auth_headers,
                        timeout=10,
                    )
                    log.info('Auto-Kapitel geloescht: HTTP %s', rd.status_code)

                if chapter_id:
                    return f'https://lichess.org/study/{study_id}/{chapter_id}'
                return f'https://lichess.org/study/{study_id}'
        except Exception as e:
            log.error('Lichess-Study-Upload fehlgeschlagen: %s', e)
            # Fallback auf standalone Import

    # Fallback: einfacher Spielimport ohne Account
    try:
        resp = requests.post(
            'https://lichess.org/api/import',
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
) -> str | None:
    """Mehrere Puzzles als Gamebook-Kapitel in eine gemeinsame Lichess-Studie laden."""
    if not puzzles:
        return None
    if len(puzzles) == 1:
        return upload_to_lichess(puzzles[0][0], context_game=puzzles[0][1])
    if not LICHESS_TOKEN:
        return upload_to_lichess(puzzles[0][0], context_game=puzzles[0][1])

    auth_headers = {'Authorization': f'Bearer {LICHESS_TOKEN}'}
    today      = _date.today().strftime('%d.%m.%Y')
    study_name = f'Puzzles – {today}'

    try:
        r = requests.post(
            'https://lichess.org/api/study',
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
        pgn_resp = requests.get(
            f'https://lichess.org/api/study/{study_id}.pgn',
            headers=auth_headers, timeout=10,
        )
        default_chapter_id = ''
        if pgn_resp.status_code == 200:
            dg = chess.pgn.read_game(io.StringIO(pgn_resp.text))
            if dg:
                default_chapter_id = dg.headers.get('ChapterURL', '').rstrip('/').split('/')[-1]

        # Kapitel importieren
        for game, context in puzzles:
            try:
                exp  = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
                pgn  = _clean_pgn_for_lichess(game.accept(exp))
                h    = dict(game.headers)
                name = h.get('White', h.get('Event', 'Puzzle'))[:70]
                requests.post(
                    f'https://lichess.org/api/study/{study_id}/import-pgn',
                    data={'pgn': pgn, 'name': name, 'mode': 'gamebook'},
                    headers=auth_headers, timeout=15,
                ).raise_for_status()
                if context is not None:
                    ctx_exp = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
                    ctx_pgn = _clean_pgn_for_lichess(context.accept(ctx_exp))
                    ch      = dict(context.headers)
                    ctx_name = f'Partie: {ch.get("White", "Partie")[:64]}'
                    requests.post(
                        f'https://lichess.org/api/study/{study_id}/import-pgn',
                        data={'pgn': ctx_pgn, 'name': ctx_name, 'mode': 'normal'},
                        headers=auth_headers, timeout=15,
                    )
            except Exception as e:
                log.warning('Kapitel-Import übersprungen: %s', e)

        # Auto-Kapitel löschen
        if default_chapter_id:
            requests.delete(
                f'https://lichess.org/api/study/{study_id}/{default_chapter_id}',
                headers=auth_headers, timeout=10,
            )

        return f'https://lichess.org/study/{study_id}'
    except Exception as e:
        log.error('Multi-Upload fehlgeschlagen: %s', e)
        return None


def build_puzzle_embed(game: chess.pgn.Game, url: str | None, turn: chess.Color | None = None) -> discord.Embed:
    h = dict(game.headers)
    line_name  = h.get('White', h.get('Event', 'Linie'))
    event_name = h.get('Event', '')
    black_name = h.get('Black', '')

    if len(line_name) > 80:
        line_name = line_name[:77] + '...'

    embed = discord.Embed(
        title=f'🧩 {line_name}',
        color=0x7fa650,
        url=url or None,
    )

    book_info = black_name or event_name
    if book_info:
        embed.add_field(name='📖 Kapitel', value=book_info, inline=False)

    if turn is not None:
        turn_str = '⬜ Weiß am Zug' if turn == chess.WHITE else '⬛ Schwarz am Zug'
        embed.add_field(name='Am Zug', value=turn_str, inline=True)

    if url:
        embed.add_field(name='🔗 Lichess', value=f'[Linie öffnen]({url})', inline=False)

    embed.set_footer(text='🧩 Tägliches Puzzle')
    return embed

async def post_puzzle(channel, count: int = 1, book_idx: int = 0):
    """Puzzles auswählen, auf Lichess hochladen und posten.

    count    – Anzahl Puzzles (1–20).
    book_idx – 1-basierte Buchnummer aus /books (0 = alle Bücher).
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
                    f'⚠️ Buch {book_idx} nicht gefunden. `/books` zeigt die verfügbaren Bücher.'
                )
                return

    results = pick_random_lines(count, book_filename)
    if not results:
        await channel.send('⚠️ Keine Puzzle-Linien gefunden. Bitte .pgn-Dateien in den `books/`-Ordner legen.')
        return

    # Trimmen
    puzzles: list[tuple[chess.pgn.Game, chess.pgn.Game | None]] = []
    for _, original_game in results:
        game    = _trim_to_training_position(original_game)
        context = original_game if game is not original_game else None
        puzzles.append((game, context))

    # Upload (eine Studie für alle Puzzles)
    if len(puzzles) == 1:
        url = upload_to_lichess(puzzles[0][0], context_game=puzzles[0][1])
    else:
        url = upload_many_to_lichess(puzzles)

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
    for game, _ in puzzles:
        try:
            board = game.board()
            turn  = board.turn
            img   = _render_board(board)
        except Exception as e:
            log.warning('Board-Render fehlgeschlagen: %s', e)
            turn = None
            img  = None

        embed = build_puzzle_embed(game, url, turn=turn)
        if img:
            file = discord.File(img, filename='board.png')
            embed.set_image(url='attachment://board.png')
            await target.send(file=file, embed=embed)
        else:
            await target.send(embed=embed)

# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

@bot.event
async def on_ready():
    await tree.sync()
    log.info('Bot online als %s', bot.user)
    daily_task.start()
    puzzle_task.start()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not isinstance(message.channel, discord.DMChannel):
        return

    # Erste DM → Bot stellt sich vor
    try:
        with open(DM_STATE_FILE) as f:
            greeted: list = json.load(f).get('greeted', [])
    except (FileNotFoundError, json.JSONDecodeError):
        greeted = []

    user_id = message.author.id
    if user_id not in greeted:
        greeted.append(user_id)
        with open(DM_STATE_FILE, 'w') as f:
            json.dump({'greeted': greeted}, f)
        await message.channel.send(
            'Hallo! Ich bin der Schach-Bot eurer Servergruppe. ♟️\n'
            'Ich poste täglich eine Partie und ein Taktikrätsel.\n\n'
            'Mit `/help` siehst du alle verfügbaren Befehle.'
        )

    await bot.process_commands(message)

# --- Slash-Commands ---

@tree.command(name='partie', description='Nächste Partie aus der Lichess-Studie posten')
async def cmd_partie(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        state = load_state()
        games = parse_games(fetch_all_chapters(STUDY_ID))

        if not games:
            await interaction.followup.send('⚠️ Keine Kapitel in der Studie gefunden.')
            return

        idx  = state.get('chapter_index', 0) % len(games)
        game = games[idx]
        state['chapter_index'] = idx + 1
        save_state(state)

        await post_chapter(interaction.channel, game)
        await interaction.followup.send(
            f'✅ Kapitel {idx + 1}/{len(games)} gepostet.', ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)


@tree.command(name='studie', description='Info zur aktuell konfigurierten Lichess-Studie')
async def cmd_studie(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        games = parse_games(fetch_all_chapters(STUDY_ID))
        state = load_state()
        idx   = state.get('chapter_index', 0) % len(games) if games else 0

        embed = discord.Embed(
            title='📚 Lichess-Studie',
            color=0x4e9e4e,
            url=f'https://lichess.org/study/{STUDY_ID}'
        )
        embed.add_field(name='Study-ID',      value=STUDY_ID,       inline=True)
        embed.add_field(name='Kapitel gesamt', value=str(len(games)), inline=True)
        embed.add_field(name='Nächstes',       value=f'#{idx + 1}',  inline=True)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)


@tree.command(name='reset', description='Kapitel-Zähler zurücksetzen (Admin)')
@discord.app_commands.default_permissions(administrator=True)
async def cmd_reset(interaction: discord.Interaction):
    save_state({'chapter_index': 0})
    await interaction.response.send_message('🔄 Zähler zurückgesetzt – startet wieder bei Kapitel 1.', ephemeral=True)


@tree.command(name='puzzle', description='Puzzle(s) aus den Büchern posten')
@discord.app_commands.describe(
    anzahl='Anzahl Puzzles (1–20, Standard: 1)',
    buch='Buchnummer aus /books (Standard: alle Bücher)',
)
async def cmd_puzzle(interaction: discord.Interaction, anzahl: int = 1, buch: int = 0):
    await interaction.response.defer()
    try:
        await post_puzzle(interaction.channel, count=anzahl, book_idx=buch)
        await interaction.followup.send(f'✅ {anzahl} Puzzle(s) gepostet.', ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)


@tree.command(name='books', description='Alle verfügbaren Puzzle-Bücher anzeigen')
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

        embed = discord.Embed(title='📚 Puzzle-Bücher', color=0x7fa650)
        for i, book in enumerate(sorted(total_per_book), 1):
            name  = book.removesuffix('_firstkey.pgn').removesuffix('.pgn')
            total = total_per_book[book]
            done  = posted_per_book[book]
            embed.add_field(name=f'{i}: {name}', value=f'{done}/{total} gepostet', inline=False)

        total_all = sum(total_per_book.values())
        done_all  = sum(posted_per_book.values())
        embed.set_footer(text=f'Gesamt: {done_all}/{total_all} Linien gepostet')
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)

@tree.command(name='help', description='Alle verfügbaren Befehle anzeigen')
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(title='♟️ Bot-Befehle', color=0x4e9e4e)
    embed.add_field(
        name='/partie',
        value='Nächste Partie aus der Lichess-Studie sofort posten.',
        inline=False,
    )
    embed.add_field(
        name='/studie',
        value='Info zur Lichess-Studie: Kapitelanzahl und nächstes Kapitel.',
        inline=False,
    )
    embed.add_field(
        name='/puzzle [anzahl] [buch]',
        value='Zufälliges Puzzle posten.\n'
              '`anzahl` — 1–20 Puzzles in einer Studie (Standard: 1)\n'
              '`buch` — Nur aus diesem Buch (Nummer aus `/books`, Standard: alle)',
        inline=False,
    )
    embed.add_field(
        name='/books',
        value='Alle verfügbaren Puzzle-Bücher mit Fortschritt anzeigen.',
        inline=False,
    )
    embed.add_field(
        name='/reset',
        value='Kapitel-Zähler zurücksetzen (nur Admins).',
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- Tägliche Tasks ---

@tasks.loop(time=time(hour=POST_HOUR, minute=POST_MINUTE))
async def daily_task():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        log.warning('Channel %s nicht gefunden.', CHANNEL_ID)
        return
    try:
        state = load_state()
        games = parse_games(fetch_all_chapters(STUDY_ID))
        if not games:
            return
        idx  = state.get('chapter_index', 0) % len(games)
        game = games[idx]
        state['chapter_index'] = idx + 1
        save_state(state)
        await post_chapter(channel, game)
    except Exception as e:
        log.error('daily_task: %s', e)


@tasks.loop(time=time(hour=PUZZLE_HOUR, minute=PUZZLE_MINUTE))
async def puzzle_task():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        log.warning('Channel %s nicht gefunden.', CHANNEL_ID)
        return
    try:
        await post_puzzle(channel)
    except Exception as e:
        log.error('puzzle_task: %s', e)

# ---------------------------------------------------------------------------

bot.run(DISCORD_TOKEN)
