import sys
# cairocffi wirft OSError wenn Cairo-DLL fehlt – vor svglib/reportlab blockieren,
# damit rlPyCairo auf pycairo zurückfällt (pycairo bündelt Cairo in seinem Wheel).
try:
    import cairocffi  # noqa: F401
except (OSError, ImportError):
    sys.modules['cairocffi'] = None  # type: ignore[assignment]

import discord
from discord.ext import tasks, commands
import requests
import chess
import chess.pgn
import io
import os
import json
import tempfile
from datetime import time
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
        print(f'[Figuren] {code} geladen')
    return _piece_cache[code]

def _label_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in ['C:/Windows/Fonts/arialbd.ttf', 'C:/Windows/Fonts/arial.ttf']:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

def board_image(game: chess.pgn.Game) -> io.BytesIO:
    """PNG der Endstellung mit Lichess-Figuren (cburnett) und Koordinaten."""
    board  = game.end().board()
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
        print(f'[Warnung] Kein Board-Bild: {e}')
        await channel.send(embed=embed)

# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

@bot.event
async def on_ready():
    await tree.sync()
    print(f'✅ Bot online als {bot.user}')
    daily_task.start()

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

# --- Täglicher Task ---

@tasks.loop(time=time(hour=POST_HOUR, minute=POST_MINUTE))
async def daily_task():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f'[Warnung] Channel {CHANNEL_ID} nicht gefunden.')
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
        print(f'[Fehler] daily_task: {e}')

# ---------------------------------------------------------------------------

bot.run(DISCORD_TOKEN)
