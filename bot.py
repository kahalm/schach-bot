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
import json
import os
import stats
from datetime import time

from dotenv import load_dotenv
load_dotenv()

DISCORD_TOKEN   = os.getenv('DISCORD_TOKEN')
CHANNEL_ID      = int(os.getenv('CHANNEL_ID', '0'))
PUZZLE_HOUR     = int(os.getenv('PUZZLE_HOUR', '9'))
PUZZLE_MINUTE   = int(os.getenv('PUZZLE_MINUTE', '0'))
DM_STATE_FILE   = 'dm_state.json'

WELCOME_MESSAGE = (
    'Hallo! Ich bin der Schach-Bot eurer Servergruppe. ♟️\n\n'
    '**Was ich kann:**\n'
    '🧩 `/puzzle` — Zufällige Taktikrätsel per DM\n'
    '♾️ `/endless` — Endlos-Modus: nach jeder Antwort kommt das nächste Puzzle\n'
    '📖 `/train` + `/next` — Buch sequentiell durcharbeiten\n'
    '📚 `/kurs` — Alle Puzzle-Bücher mit Fortschritt\n'
    '📖 `/bibliothek` — Schachbuch-Bibliothek durchsuchen & downloaden\n'
    '📊 `/stats` — Deine Statistiken\n\n'
    'Mit `/help` siehst du alle Befehle im Detail.'
)

# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

# Module laden
import puzzle
import library

puzzle.setup(bot)
library.setup(bot)


@bot.event
async def on_ready():
    await tree.sync()
    log.info('Bot online als %s', bot.user)
    puzzle_task.start()


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    emoji = str(payload.emoji)
    if emoji not in puzzle._PUZZLE_REACTIONS:
        return
    if not puzzle.is_puzzle_message(payload.message_id):
        return
    if emoji == '🚮':
        line_id = puzzle.get_puzzle_line_id(payload.message_id)
        if line_id:
            puzzle.ignore_puzzle(line_id)
            try:
                user = await bot.fetch_user(payload.user_id)
                dm = await user.create_dm()
                await dm.send(f'🚮 Puzzle ignoriert und wird nicht mehr erscheinen:\n`{line_id}`')
            except Exception as e:
                log.warning('Ignore-DM fehlgeschlagen: %s', e)
        # Thread (daily): Entschuldigung + Ersatz-Puzzle posten
        channel = bot.get_channel(payload.channel_id)
        if channel and isinstance(channel, discord.Thread):
            await channel.send('🚮 Sorry für das schlechte Puzzle! Hier kommt ein neues:')
            try:
                await puzzle.post_puzzle(channel)
            except Exception as e:
                log.warning('Ersatz-Puzzle im Thread fehlgeschlagen: %s', e)
        # Endless: nach 🚮 auch nächstes Puzzle senden
        if puzzle.is_endless(payload.user_id):
            await puzzle.post_next_endless(bot, payload.user_id)
    else:
        stats.inc(payload.user_id, f'reaction_{emoji}')
        # Endless: nach ✅/❌ nächstes Puzzle senden
        if emoji in ('✅', '❌') and puzzle.is_endless(payload.user_id):
            await puzzle.post_next_endless(bot, payload.user_id)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    emoji = str(payload.emoji)
    if emoji not in puzzle._PUZZLE_REACTIONS:
        return
    if not puzzle.is_puzzle_message(payload.message_id):
        return
    if emoji == '🚮':
        line_id = puzzle.get_puzzle_line_id(payload.message_id)
        if line_id:
            puzzle.unignore_puzzle(line_id)
            try:
                user = await bot.fetch_user(payload.user_id)
                dm = await user.create_dm()
                await dm.send(f'♻️ Puzzle wieder aktiviert:\n`{line_id}`')
            except Exception as e:
                log.warning('Unignore-DM fehlgeschlagen: %s', e)
    else:
        stats.inc(payload.user_id, f'reaction_{emoji}', -1)


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
        await message.channel.send(WELCOME_MESSAGE)

    await bot.process_commands(message)


@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    try:
        dm = await member.create_dm()
        await dm.send(WELCOME_MESSAGE)
    except discord.Forbidden:
        log.warning('Kann DM an %s nicht senden (DMs deaktiviert).', member)
    except Exception as e:
        log.warning('Willkommens-DM fehlgeschlagen für %s: %s', member, e)


# --- Slash-Commands ---

@tree.command(name='help', description='Alle verfügbaren Befehle anzeigen')
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(title='♟️ Bot-Befehle', color=0x4e9e4e)
    embed.add_field(
        name='/puzzle [anzahl] [buch]',
        value='Zufälliges Puzzle per DM senden.\n'
              '`anzahl` — 1–20 Puzzles in einer Studie (Standard: 1)\n'
              '`buch` — Nur aus diesem Buch (Nummer aus `/kurs`, Standard: alle)',
        inline=False,
    )
    embed.add_field(
        name='/kurs',
        value='Alle verfügbaren Puzzle-Bücher mit Fortschritt anzeigen.',
        inline=False,
    )
    embed.add_field(
        name='/train [buch]',
        value='Buch für sequentielles Training wählen (Nummer aus `/kurs`).\n'
              '`/train` zeigt den aktuellen Status · `/train 0` beendet das Training.',
        inline=False,
    )
    embed.add_field(
        name='/next [anzahl]',
        value='Nächste Linie(n) aus dem Trainingsbuch per DM senden.\n'
              '`/next` — 1 Linie · `/next 5` — 5 Linien · `/next 10` — 10 Linien',
        inline=False,
    )
    embed.add_field(
        name='/bibliothek <suche>',
        value='Schachbuch-Bibliothek durchsuchen (Titel, Autor, Tags, Dateinamen).\nDownload mit Formatauswahl (PDF/DJVU/EPUB).',
        inline=False,
    )
    embed.add_field(
        name='/autor <autor>',
        value='Alle Bücher eines Autors anzeigen.',
        inline=False,
    )
    embed.add_field(
        name='/tag <tag>',
        value='Bücher nach Tag filtern (z.B. Taktik, Französisch, Endspiel).',
        inline=False,
    )
    embed.add_field(
        name='/endless [buch]',
        value='Endlos-Puzzle-Modus: nach jeder ✅/❌ kommt sofort das nächste Puzzle per DM.\n'
              'Nochmal `/endless` zum Stoppen.',
        inline=False,
    )
    embed.add_field(
        name='/stats',
        value='Nutzungsstatistiken aller User anzeigen.',
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name='announce', description='Begrüßungsnachricht an einen User senden (Admin)')
@discord.app_commands.describe(user='Der User, der die Nachricht erhalten soll')
@discord.app_commands.default_permissions(administrator=True)
async def cmd_announce(interaction: discord.Interaction, user: discord.User):
    try:
        dm = await user.create_dm()
        await dm.send(WELCOME_MESSAGE)
        await interaction.response.send_message(
            f'✅ Begrüßungsnachricht an **{user.display_name}** gesendet.',
            ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            f'❌ Kann keine DM an **{user.display_name}** senden (DMs deaktiviert).',
            ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f'❌ Fehler: {e}', ephemeral=True)


@tree.command(name='stats', description='Nutzungsstatistiken aller User anzeigen')
async def cmd_stats(interaction: discord.Interaction):
    all_stats = stats.get_all()
    if not all_stats:
        await interaction.response.send_message('Noch keine Statistiken vorhanden.', ephemeral=True)
        return

    embed = discord.Embed(title='📊 Statistiken', color=0x4e9e4e)
    lines = []
    for uid, data in all_stats.items():
        puzzles = data.get('puzzles', 0)
        downloads = data.get('downloads', 0)
        solved = data.get('reaction_✅', 0)
        failed = data.get('reaction_❌', 0)
        liked = data.get('reaction_👍', 0)
        disliked = data.get('reaction_👎', 0)
        try:
            user = await bot.fetch_user(int(uid))
            name = user.display_name
        except Exception:
            name = f'User {uid}'
        line = f'**{name}** — 🧩 {puzzles} · 📥 {downloads}'
        if solved or failed:
            line += f' · ✅ {solved} · ❌ {failed}'
        if liked or disliked:
            line += f' · 👍 {liked} · 👎 {disliked}'
        lines.append(line)

    embed.description = '\n'.join(lines)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- Tägliche Tasks ---

@tasks.loop(time=time(hour=PUZZLE_HOUR, minute=PUZZLE_MINUTE))
async def puzzle_task():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        log.warning('Channel %s nicht gefunden.', CHANNEL_ID)
        return
    try:
        await puzzle.post_puzzle(channel)
    except Exception as e:
        log.error('puzzle_task: %s', e)

# ---------------------------------------------------------------------------

bot.run(DISCORD_TOKEN)
