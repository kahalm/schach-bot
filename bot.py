import sys
# cairocffi wirft OSError wenn Cairo-DLL fehlt – vor svglib/reportlab blockieren,
# damit rlPyCairo auf pycairo zurückfällt (pycairo bündelt Cairo in seinem Wheel).
try:
    import cairocffi  # noqa: F401
except (OSError, ImportError):
    sys.modules['cairocffi'] = None  # type: ignore[assignment]

from core import log_setup
log = log_setup.setup()

import discord
from discord.ext import tasks, commands
import json
import os
from datetime import time

from core import stats
from core.paths import CONFIG_DIR
from core.version import VERSION, START_TIME

from dotenv import load_dotenv
load_dotenv()

DISCORD_TOKEN   = os.getenv('DISCORD_TOKEN')
CHANNEL_ID      = int(os.getenv('CHANNEL_ID', '0'))
PUZZLE_HOUR     = int(os.getenv('PUZZLE_HOUR', '9'))
PUZZLE_MINUTE   = int(os.getenv('PUZZLE_MINUTE', '0'))
DM_STATE_FILE   = os.path.join(CONFIG_DIR, 'dm_state.json')

WELCOME_MESSAGE = (
    'Hallo! Ich bin der Schach-Bot eurer Servergruppe. ♟️\n\n'
    '**Was ich kann:**\n'
    '🧩 `/puzzle` — Zufällige Taktikrätsel per DM\n'
    '🙈 `/blind` — Stellung X Züge vor dem Puzzle (im Kopf rechnen)\n'
    '♾️ `/endless` — Endlos-Modus: nach jeder Antwort kommt das nächste Puzzle\n'
    '📖 `/train` + `/next` — Buch sequentiell durcharbeiten\n'
    '📚 `/kurs` — Alle Puzzle-Bücher mit Fortschritt\n'
    '📖 `/bibliothek` — Schachbuch-Bibliothek durchsuchen & downloaden\n'
    '🔗 `/resourcen` — Online-Lernressourcen anzeigen oder hinzufügen\n'
    '▶️ `/youtube` — YouTube-Kanäle/Videos anzeigen oder hinzufügen\n'
    '⏰ `/reminder` — Wiederkehrende Puzzle-DMs einstellen\n'
    '🏅 `/elo` — Eigene Schach-Elo angeben\n'
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
from commands import reminder, resourcen, youtube, elo, release_notes, blind

puzzle.setup(bot)
library.setup(bot)
reminder.setup(bot)
resourcen.setup(bot)
youtube.setup(bot)
elo.setup(bot)
release_notes.setup(bot)
blind.setup(bot)


@bot.event
async def on_ready():
    # Persistente Button-View für Puzzle-Reaktionen registrieren
    bot.add_view(puzzle.PuzzleView())
    await tree.sync()
    log.info('Bot online als %s', bot.user)
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
        name='/blind [moves] [anzahl] [buch]',
        value='Blind-Puzzle: Stellung X Halbzüge VOR dem eigentlichen Puzzle.\n'
              'Du musst die X Züge im Kopf spielen, dann das Puzzle lösen.\n'
              '`/blind` — 4 Züge im Voraus, zufälliges Blind-Buch\n'
              '`/blind moves:5 anzahl:2 buch:3` — 2 Puzzles aus Buch 3, je 5 Züge blind\n'
              'Nur Bücher mit `blind: true` in `books/books.json` sind nutzbar (siehe `/kurs`).',
        inline=False,
    )
    embed.add_field(
        name='/endless [buch]',
        value='Endlos-Puzzle-Modus: nach jeder ✅/❌ kommt sofort das nächste Puzzle per DM.\n'
              'Nochmal `/endless` zum Stoppen.',
        inline=False,
    )
    embed.add_field(
        name='/reminder [hours] [puzzle_count] [buch]',
        value='Wiederkehrende Puzzle-DMs einstellen.\n'
              '`/reminder hours:4 puzzle_count:3` — Alle 4h 3 Puzzles per DM\n'
              '`/reminder hours:0` — Reminder stoppen\n'
              '`/reminder` — Aktuellen Status anzeigen',
        inline=False,
    )
    embed.add_field(
        name='/resourcen [url] [beschreibung]',
        value='Online-Lernressourcen anzeigen oder hinzufügen.\n'
              '`/resourcen` — Alle Ressourcen auflisten\n'
              '`/resourcen url:… beschreibung:…` — Neue Ressource hinzufügen',
        inline=False,
    )
    embed.add_field(
        name='/youtube [url] [beschreibung]',
        value='YouTube-Kanäle/Videos anzeigen oder hinzufügen.\n'
              '`/youtube` — Alle Links auflisten\n'
              '`/youtube url:… beschreibung:…` — Neuen Link hinzufügen',
        inline=False,
    )
    embed.add_field(
        name='/ignore_kapitel [buch] [kapitel] [aktion]',
        value='**(Admin)** Ein ganzes Kapitel ignorieren.\n'
              '`/ignore_kapitel buch:2 kapitel:3` — ignoriert Kapitel 3 in Buch 2\n'
              '`/ignore_kapitel buch:2 kapitel:3 aktion:unignore` — wieder aktivieren\n'
              '`/ignore_kapitel` — alle ignorierten Kapitel anzeigen',
        inline=False,
    )
    embed.add_field(
        name='/elo [wert]',
        value='Eigene Schach-Elo angeben oder anzeigen.\n'
              '`/elo wert:1500` — Setzt deine aktuelle Elo (mit Zeitstempel)\n'
              '`/elo` — Zeigt deine aktuelle Elo + Historie',
        inline=False,
    )
    embed.add_field(
        name='/stats',
        value='Nutzungsstatistiken aller User anzeigen.',
        inline=False,
    )
    embed.add_field(
        name='/version',
        value='Aktuelle Bot-Version anzeigen.',
        inline=False,
    )
    embed.add_field(
        name='/release-notes [version] [anzahl]',
        value='Versionshistorie/Changelog des Bots anzeigen.\n'
              '`/release-notes` — Letzte 3 Versionen\n'
              '`/release-notes version:1.1.0` — Bestimmte Version',
        inline=False,
    )
    embed.set_footer(text=f'Schach-Bot v{VERSION}')
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name='version', description='Aktuelle Bot-Version und Uptime anzeigen')
async def cmd_version(interaction: discord.Interaction):
    ts = int(START_TIME.timestamp())
    await interaction.response.send_message(
        f'♟️ **Schach-Bot** v{VERSION}\n'
        f'🔄 Letzter Restart: <t:{ts}:f> (<t:{ts}:R>)',
        ephemeral=True)


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
        trashed = data.get('reaction_🚮', 0)
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
        if trashed:
            line += f' · 🚮 {trashed}'
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
