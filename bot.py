import discord
from discord.ext import tasks, commands
import requests
import chess
import chess.pgn
import io
import os
import json
from datetime import time
from PIL import Image, ImageDraw, ImageFont

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
# Board-Bild (Pillow, keine externen Systemlibs nötig)
# ---------------------------------------------------------------------------

_SQ_SIZE  = 56
_LIGHT    = (240, 217, 181)
_DARK     = (181, 136, 99)
_W_PIECE  = (255, 255, 255)
_B_PIECE  = (20,  20,  20)
_OUTLINE  = (80,  80,  80)

_GLYPHS = {
    chess.PAWN:   ('P', 'p'),
    chess.KNIGHT: ('N', 'n'),
    chess.BISHOP: ('B', 'b'),
    chess.ROOK:   ('R', 'r'),
    chess.QUEEN:  ('Q', 'q'),
    chess.KING:   ('K', 'k'),
}

def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in [
        'C:/Windows/Fonts/arialbd.ttf',
        'C:/Windows/Fonts/arial.ttf',
        'C:/Windows/Fonts/DejaVuSans-Bold.ttf',
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def board_image(game: chess.pgn.Game) -> io.BytesIO:
    """PNG der Endstellung als einfaches Brett-Bild erzeugen."""
    board = game.end().board()
    s = _SQ_SIZE
    size = s * 8
    img  = Image.new('RGB', (size, size))
    draw = ImageDraw.Draw(img)
    font = _load_font(s - 8)

    for sq in chess.SQUARES:
        f = chess.square_file(sq)
        r = chess.square_rank(sq)
        x, y = f * s, (7 - r) * s
        fill = _LIGHT if (f + r) % 2 == 1 else _DARK
        draw.rectangle([x, y, x + s - 1, y + s - 1], fill=fill)

        piece = board.piece_at(sq)
        if piece:
            char = _GLYPHS[piece.piece_type][0 if piece.color == chess.WHITE else 1]
            color = _W_PIECE if piece.color == chess.WHITE else _B_PIECE
            bb = draw.textbbox((0, 0), char, font=font)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            tx, ty = x + (s - tw) // 2, y + (s - th) // 2
            # Outline für bessere Lesbarkeit
            for dx, dy in ((-1,-1),(1,-1),(-1,1),(1,1)):
                draw.text((tx + dx, ty + dy), char, font=font, fill=_OUTLINE)
            draw.text((tx, ty), char, font=font, fill=color)

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
