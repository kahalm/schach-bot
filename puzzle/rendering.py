"""Board-Rendering: Lichess cburnett-Figuren via SVG → PNG."""

import io
import os
import tempfile
import logging

import chess
import requests

_session = requests.Session()
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM

log = logging.getLogger('schach-bot')

_PIECE_DOWNLOAD_TIMEOUT = 15  # Sekunden für cburnett-SVG-Downloads

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
    if drawing is None:
        raise ValueError('svg2rlg konnte SVG nicht parsen')
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

_PIECES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'assets', 'pieces')


def _get_piece(code: str, size: int) -> Image.Image:
    if code not in _piece_cache:
        # 1. Lokal gebundelte SVGs (kein Netzwerk noetig)
        local_path = os.path.join(_PIECES_DIR, f'{code}.svg')
        if os.path.isfile(local_path):
            try:
                with open(local_path, 'rb') as f:
                    _piece_cache[code] = _svg_to_pil(f.read(), size)
                log.debug('Figur lokal geladen: %s', code)
                return _piece_cache[code]
            except Exception as e:
                log.warning('Lokale Figur %s fehlgeschlagen, Netzwerk-Fallback: %s', code, e)
        # 2. Netzwerk-Fallback (Lichess)
        url = f'https://lichess1.org/assets/piece/cburnett/{code}.svg'
        for attempt in range(2):
            try:
                resp = _session.get(url, timeout=_PIECE_DOWNLOAD_TIMEOUT)
                resp.raise_for_status()
                _piece_cache[code] = _svg_to_pil(resp.content, size)
                log.info('Figur aus Netzwerk geladen: %s', code)
                break
            except (requests.RequestException, ValueError) as e:
                if attempt == 1:
                    raise
                log.warning('Figur %s laden fehlgeschlagen (Retry): %s', code, e)
    return _piece_cache[code]

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
_font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _label_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if size in _font_cache:
        return _font_cache[size]
    for p in _FONT_PATHS:
        try:
            font = ImageFont.truetype(p, size)
            _font_cache[size] = font
            return font
        except Exception:
            pass
    font = ImageFont.load_default()
    _font_cache[size] = font
    return font

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
