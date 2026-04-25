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

from core import stats, dm_log
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
from commands import reminder, resourcen, youtube, elo, release_notes, blind, test

puzzle.setup(bot)
library.setup(bot)
reminder.setup(bot)
resourcen.setup(bot)
youtube.setup(bot)
elo.setup(bot)
release_notes.setup(bot)
blind.setup(bot)
test.setup(bot)


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

def _is_admin(interaction: discord.Interaction) -> bool:
    """True wenn der User Server-Admin ist (oder im DM-Kontext)."""
    member = interaction.user
    return (
        isinstance(member, discord.Member)
        and member.guild_permissions.administrator
    )


def _help_fields(bereich: str, is_admin: bool) -> tuple[str, list[tuple[str, str]]]:
    """Gibt (Titel, [(name, value), ...]) für den gewünschten Bereich zurück."""
    if bereich == 'puzzle':
        return '🧩 Puzzles', [
            ('/puzzle [anzahl] [buch]',
             'Zufälliges Puzzle per DM senden.\n'
             '`anzahl` — 1–20 Puzzles (Standard: 1)\n'
             '`buch` — Nur aus diesem Buch (Nummer aus `/kurs`, Standard: alle)'),
            ('/kurs',
             'Alle verfügbaren Puzzle-Bücher mit Fortschritt anzeigen.'),
            ('/train [buch]',
             'Buch für sequentielles Training wählen (Nummer aus `/kurs`).\n'
             '`/train` — Status anzeigen · `/train 0` — Training beenden'),
            ('/next [anzahl]',
             'Nächste Linie(n) aus dem Trainingsbuch per DM senden.\n'
             '`/next` — 1 Linie · `/next 5` — 5 Linien'),
            ('/blind [moves] [anzahl] [buch]',
             'Blind-Puzzle: Stellung X Halbzüge VOR dem eigentlichen Puzzle.\n'
             '`/blind` — 4 Züge blind, zufälliges Buch\n'
             '`/blind moves:5 anzahl:2 buch:3` — 2 Puzzles aus Buch 3, je 5 Züge blind\n'
             'Nur Bücher mit `blind: true` nutzbar (siehe `/kurs`).'),
            ('/endless [buch]',
             'Endlos-Modus: nach jeder ✅/❌ kommt sofort das nächste Puzzle per DM.\n'
             'Nochmal `/endless` zum Stoppen.'),
            ('/reminder [hours] [puzzle_count] [buch]',
             'Wiederkehrende Puzzle-DMs einstellen.\n'
             '`/reminder hours:4 puzzle_count:3` — Alle 4h 3 Puzzles\n'
             '`/reminder hours:0` — Stoppen · `/reminder` — Status anzeigen'),
        ]
    if bereich == 'bibliothek':
        return '📚 Bibliothek', [
            ('/bibliothek <suche>',
             'Schachbuch-Bibliothek durchsuchen (Titel, Autor, Tags).\nDownload mit Formatauswahl (PDF/DJVU/EPUB).'),
            ('/autor <autor>',
             'Alle Bücher eines Autors anzeigen.'),
            ('/tag <tag>',
             'Bücher nach Tag filtern (z.B. Taktik, Französisch, Endspiel).'),
        ]
    if bereich == 'community':
        return '🌐 Community', [
            ('/resourcen [url] [beschreibung]',
             'Online-Lernressourcen anzeigen oder hinzufügen.\n'
             '`/resourcen` — Auflisten · `/resourcen url:… beschreibung:…` — Hinzufügen'),
            ('/youtube [url] [beschreibung]',
             'YouTube-Kanäle/Videos anzeigen oder hinzufügen.\n'
             '`/youtube` — Auflisten · `/youtube url:… beschreibung:…` — Hinzufügen'),
            ('/elo [wert]',
             'Eigene Schach-Elo angeben oder anzeigen.\n'
             '`/elo wert:1500` — Setzen · `/elo` — Anzeigen mit Historie'),
        ]
    if bereich == 'info':
        return 'ℹ️ Info', [
            ('/version', 'Aktuelle Bot-Version und Uptime anzeigen.'),
            ('/release-notes [version] [anzahl]',
             'Versionshistorie/Changelog anzeigen.\n'
             '`/release-notes` — Letzte 3 Versionen\n'
             '`/release-notes version:1.1.0` — Bestimmte Version'),
            ('/help [bereich]',
             'Hilfe anzeigen. Bereiche: `puzzle` · `bibliothek` · `community` · `info`'
             + (' · `admin`' if is_admin else '')),
        ]
    if bereich == 'admin' and is_admin:
        return '🔧 Admin', [
            ('/daily', 'Tägliches Puzzle manuell auslösen.'),
            ('/stats', 'Nutzungsstatistiken aller User anzeigen.'),
            ('/announce <user>', 'Begrüßungsnachricht per DM an einen User senden.'),
            ('/ignore_kapitel [buch] [kapitel] [aktion]',
             'Ein ganzes Kapitel ignorieren.\n'
             '`/ignore_kapitel buch:2 kapitel:3` — ignorieren\n'
             '`/ignore_kapitel buch:2 kapitel:3 aktion:unignore` — reaktivieren\n'
             '`/ignore_kapitel` — alle ignorierten Kapitel anzeigen'),
            ('/test', 'Snapshot-Regressionstests ausführen.'),
        ]
    return '', []


@tree.command(name='help', description='Verfügbare Befehle anzeigen')
@discord.app_commands.describe(bereich='Bereich: puzzle, bibliothek, community, info, admin')
async def cmd_help(interaction: discord.Interaction, bereich: str = ''):
    is_admin = _is_admin(interaction)
    bereich = bereich.lower().strip()

    if bereich:
        title, fields = _help_fields(bereich, is_admin)
        if not fields:
            await interaction.response.send_message(
                f'Unbekannter Bereich `{bereich}`. '
                'Verfügbar: `puzzle` · `bibliothek` · `community` · `info`'
                + (' · `admin`' if is_admin else ''),
                ephemeral=True,
            )
            return
        embed = discord.Embed(title=title, color=0x4e9e4e)
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)
    else:
        # Übersicht aller Bereiche
        embed = discord.Embed(title='♟️ Schach-Bot — Hilfe', color=0x4e9e4e,
                              description='Nutze `/help bereich:…` für Details.')
        embed.add_field(name='🧩 puzzle',
                        value='`/puzzle` `/kurs` `/train` `/next` `/blind` `/endless` `/reminder`',
                        inline=False)
        embed.add_field(name='📚 bibliothek',
                        value='`/bibliothek` `/autor` `/tag`',
                        inline=False)
        embed.add_field(name='🌐 community',
                        value='`/resourcen` `/youtube` `/elo`',
                        inline=False)
        embed.add_field(name='ℹ️ info',
                        value='`/version` `/release-notes` `/help`',
                        inline=False)
        if is_admin:
            embed.add_field(name='🔧 admin',
                            value='`/daily` `/stats` `/announce` `/ignore_kapitel` `/test`',
                            inline=False)

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


@tree.command(name='stats', description='Nutzungsstatistiken aller User anzeigen (Admin)')
@discord.app_commands.default_permissions(administrator=True)
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


# --- Admin-Befehle ---

@tree.command(name='daily', description='Tägliches Puzzle manuell auslösen (Admin)')
@discord.app_commands.default_permissions(administrator=True)
async def cmd_daily(interaction: discord.Interaction):
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        await interaction.response.send_message('Puzzle-Channel nicht gefunden.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        await puzzle.post_puzzle(channel)
        await interaction.followup.send(f'Daily Puzzle in <#{CHANNEL_ID}> gepostet.', ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f'Fehler: {e}', ephemeral=True)


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

dm_log.install()
bot.run(DISCORD_TOKEN)
