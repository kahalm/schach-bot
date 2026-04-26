import sys
# cairocffi wirft OSError wenn Cairo-DLL fehlt – vor svglib/reportlab blockieren,
# damit rlPyCairo auf pycairo zurückfällt (pycairo bündelt Cairo in seinem Wheel).
try:
    import cairocffi  # noqa: F401
except (OSError, ImportError):
    sys.modules['cairocffi'] = None  # type: ignore[assignment]

from core import log_setup
log = log_setup.setup()

import asyncio
import discord
from discord.ext import tasks, commands
import os
from datetime import datetime, time

from core import stats, dm_log
from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR
from core.version import VERSION, START_TIME, EMBED_COLOR

from dotenv import load_dotenv
load_dotenv()

DISCORD_TOKEN   = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    raise SystemExit('DISCORD_TOKEN fehlt in .env – siehe .env.example')
try:
    CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))
except ValueError:
    raise SystemExit(f"CHANNEL_ID ungültig: {os.getenv('CHANNEL_ID')!r} — muss eine Zahl sein")
try:
    TOURNAMENT_CHANNEL_ID = int(os.getenv('TOURNAMENT_CHANNEL_ID') or os.getenv('RALLYE_CHANNEL_ID', '0'))
except ValueError:
    raise SystemExit(f"TOURNAMENT_CHANNEL_ID ungültig: {os.getenv('TOURNAMENT_CHANNEL_ID')!r} — muss eine Zahl sein")
try:
    PUZZLE_HOUR = int(os.getenv('PUZZLE_HOUR', '9'))
    PUZZLE_MINUTE = int(os.getenv('PUZZLE_MINUTE', '0'))
except ValueError:
    raise SystemExit(
        f"PUZZLE_HOUR/PUZZLE_MINUTE ungültig: "
        f"{os.getenv('PUZZLE_HOUR')!r}/{os.getenv('PUZZLE_MINUTE')!r} — müssen Zahlen sein")
if not (0 <= PUZZLE_HOUR <= 23 and 0 <= PUZZLE_MINUTE <= 59):
    raise SystemExit(f'PUZZLE_HOUR/PUZZLE_MINUTE ungültig: {PUZZLE_HOUR}:{PUZZLE_MINUTE}')
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
    '🏆 `/turnier` — Turniere in Tirol anzeigen\n'
    '🔔 `/turnier_sub` — Bei neuen Turnieren gepingt werden\n'
    '🏇 `/schachrallye` — Schachrallye-Termine anzeigen\n'
    '💡 `/wanted` — Feature-Wünsche einreichen\n'
    '📊 `/stats` — Deine Statistiken\n\n'
    'Mit `/help` siehst du alle Befehle im Detail.'
)

# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
tree = bot.tree

# Module laden
import puzzle
import library
from commands import reminder, resourcen, youtube, elo, release_notes, blind, test, wanted, schachrallye

puzzle.setup(bot)
library.setup(bot)
reminder.setup(bot)
resourcen.setup(bot)
youtube.setup(bot)
elo.setup(bot)
release_notes.setup(bot)
blind.setup(bot)
test.setup(bot)
wanted.setup(bot)
schachrallye.setup(bot, tournament_channel_id=TOURNAMENT_CHANNEL_ID)


_ready_done = False

@bot.event
async def on_ready():
    global _ready_done
    if _ready_done:
        log.info('Reconnect als %s (on_ready übersprungen)', bot.user)
        return
    _ready_done = True
    # Persistente Button-View für Puzzle-Reaktionen registrieren
    bot.add_view(puzzle.PuzzleView())
    for attempt, delay in enumerate([0, 5, 15, 30], 1):
        try:
            if delay:
                await asyncio.sleep(delay)
            await tree.sync()
            break
        except Exception:
            log.warning('tree.sync() Versuch %d/4 fehlgeschlagen', attempt)
            if attempt == 4:
                log.error('tree.sync() endgültig fehlgeschlagen — Commands evtl. nicht verfügbar')
    log.info('Bot online als %s v%s', bot.user, VERSION)
    puzzle_task.start()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not isinstance(message.channel, discord.DMChannel):
        return

    # Erste DM → Bot stellt sich vor
    user_id = message.author.id
    should_greet = False

    def _check_and_greet(data):
        nonlocal should_greet
        greeted = data.get('greeted', [])
        if user_id in greeted:
            return data  # bereits begrüßt
        should_greet = True
        greeted.append(user_id)
        data['greeted'] = greeted
        return data

    await asyncio.to_thread(atomic_update, DM_STATE_FILE, _check_and_greet, dict)
    if should_greet:
        await message.channel.send(WELCOME_MESSAGE)

    await bot.process_commands(message)


@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    try:
        dm = await member.create_dm()
        await dm.send(WELCOME_MESSAGE)
        # In greeted-Liste eintragen, damit on_message kein Doppel-Willkommen schickt
        def _mark_greeted(data):
            greeted = data.get('greeted', [])
            if member.id not in greeted:
                greeted.append(member.id)
                data['greeted'] = greeted
            return data
        await asyncio.to_thread(atomic_update, DM_STATE_FILE, _mark_greeted, dict)
    except discord.Forbidden:
        log.warning('Kann DM an %s nicht senden (DMs deaktiviert).', member)
    except Exception as e:
        log.warning('Willkommens-DM fehlgeschlagen für %s: %s', member, e)


# --- Helpers ---

async def _display_name(uid, guild=None):
    """Server-Nick wenn moeglich, sonst globaler Name."""
    if guild:
        try:
            member = guild.get_member(int(uid)) or await guild.fetch_member(int(uid))
            return member.display_name
        except Exception:
            pass
    try:
        u = await bot.fetch_user(int(uid))
        return u.display_name
    except Exception:
        return f'User {uid}'


def _paginate_lines(header: str, lines: list[str],
                    max_len: int = 4096) -> list[discord.Embed]:
    """Teilt Zeilen auf mehrere Embeds auf, wenn >max_len Zeichen."""
    embeds: list[discord.Embed] = []
    buf = header
    for line in lines:
        candidate = buf + line + '\n'
        if len(candidate) > max_len:
            embeds.append(discord.Embed(description=buf.rstrip(), color=EMBED_COLOR))
            buf = line + '\n'
        else:
            buf = candidate
    if buf.strip():
        embeds.append(discord.Embed(description=buf.rstrip(), color=EMBED_COLOR))
    return embeds or [discord.Embed(description=header.rstrip(), color=EMBED_COLOR)]


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
            ('/wanted [beschreibung]',
             'Feature-Wunsch einreichen oder Liste anzeigen.\n'
             '`/wanted` — Auflisten · `/wanted beschreibung:…` — Einreichen'),
            ('/wanted_list', 'Alle Feature-Wünsche anzeigen (nach Stimmen sortiert).'),
            ('/wanted_vote <id>', 'Für einen Feature-Wunsch stimmen (Toggle +1/−1).'),
            ('/schachrallye', 'Alle Schachrallye-Termine anzeigen.'),
            ('/schachrallye_sub [user]',
             'Für Rallye-Erinnerungen subscriben.\n'
             '`/schachrallye_sub` — Selbst · `/schachrallye_sub user:@X` — Admin subscribed anderen'),
            ('/schachrallye_unsub [user]', 'Rallye-Erinnerungen abbestellen.'),
            ('/turnier', 'Alle zukünftigen Turniere anzeigen (tirol.chess.at).'),
            ('/turnier_sub <tag> [user]',
             'Für Turnier-Tag subscriben (Ping bei neuen Turnieren).\n'
             'Tags z.B.: `schnellschach`, `blitz`, `960`, `schachrallye`'),
            ('/turnier_unsub <tag> [user]', 'Turnier-Tag-Abo abbestellen.'),
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
            ('/greeted', 'Alle User anzeigen, die die Begrüßungs-DM erhalten haben.'),
            ('/ignore_kapitel [buch] [kapitel] [aktion]',
             'Ein ganzes Kapitel ignorieren.\n'
             '`/ignore_kapitel buch:2 kapitel:3` — ignorieren\n'
             '`/ignore_kapitel buch:2 kapitel:3 aktion:unignore` — reaktivieren\n'
             '`/ignore_kapitel` — alle ignorierten Kapitel anzeigen'),
            ('/dm-log [user]', 'DM-Log anzeigen (alle oder ein bestimmter User).'),
            ('/test', 'Snapshot-Regressionstests ausführen.'),
            ('/wanted_delete <id>', 'Feature-Wunsch löschen.'),
            ('/schachrallye_add <datum> <ort>', 'Rallye-Termin anlegen (TT.MM.JJJJ).'),
            ('/schachrallye_del <id>', 'Rallye-Termin löschen.'),
            ('/turnier_parse', 'Termine von tirol.chess.at importieren.'),
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
        embed = discord.Embed(title=title, color=EMBED_COLOR)
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)
    else:
        # Übersicht aller Bereiche
        embed = discord.Embed(title='♟️ Schach-Bot — Hilfe', color=EMBED_COLOR,
                              description='Nutze `/help bereich:…` für Details.')
        embed.add_field(name='🧩 puzzle',
                        value='`/puzzle` `/kurs` `/train` `/next` `/blind` `/endless` `/reminder`',
                        inline=False)
        embed.add_field(name='📚 bibliothek',
                        value='`/bibliothek` `/autor` `/tag`',
                        inline=False)
        embed.add_field(name='🌐 community',
                        value='`/resourcen` `/youtube` `/elo` `/wanted` `/schachrallye` `/turnier`',
                        inline=False)
        embed.add_field(name='ℹ️ info',
                        value='`/version` `/release-notes` `/help`',
                        inline=False)
        if is_admin:
            embed.add_field(name='🔧 admin',
                            value='`/daily` `/stats` `/announce` `/dm-log` `/ignore_kapitel` `/test` `/wanted_delete` `/schachrallye_add` `/schachrallye_del`',
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


@tree.command(name='greeted', description='Zeigt alle User, die die Begrüßungs-DM erhalten haben (Admin)')
@discord.app_commands.default_permissions(administrator=True)
async def cmd_greeted(interaction: discord.Interaction):
    data = await asyncio.to_thread(atomic_read, DM_STATE_FILE, dict)
    greeted = data.get('greeted', [])
    if not greeted:
        await interaction.response.send_message('Noch niemand begrüßt.', ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    async def _fetch(uid):
        name = await _display_name(uid, interaction.guild)
        return f'• **{name}** (`{uid}`)'

    results = await asyncio.gather(*[_fetch(uid) for uid in greeted], return_exceptions=True)
    lines = [r for r in results if isinstance(r, str)]
    header = f'**Begrüßte User ({len(greeted)}):**\n'
    embeds = _paginate_lines(header, lines)
    await interaction.followup.send(embeds=embeds, ephemeral=True)


@tree.command(name='dm-log', description='DM-Log anzeigen (Admin)')
@discord.app_commands.describe(user='Nur DMs dieses Users anzeigen')
@discord.app_commands.default_permissions(administrator=True)
async def cmd_dm_log(interaction: discord.Interaction, user: discord.User = None):
    await interaction.response.defer(ephemeral=True)
    data = await asyncio.to_thread(atomic_read, dm_log.DM_LOG_FILE, dict)

    if user:
        subset = {str(user.id): data.get(str(user.id), [])}
        subset = {k: v for k, v in subset.items() if v}
    else:
        subset = {k: v for k, v in data.items() if v}

    if not subset:
        await interaction.followup.send('Noch keine DMs protokolliert.', ephemeral=True)
        return

    # User-Namen parallel fetchen
    uids = list(subset.keys())

    async def _fetch_name(uid):
        return uid, await _display_name(uid, interaction.guild)

    results = await asyncio.gather(*[_fetch_name(uid) for uid in uids],
                                   return_exceptions=True)
    names = dict(r for r in results if isinstance(r, tuple))

    lines = []
    for uid, entries in subset.items():
        name = names.get(uid, f'User {uid}')
        if user:
            # Detailansicht: letzte 10 DMs mit Inhalt
            lines.append(f'**{name}** ({len(entries)} DMs):')
            for entry in entries[-10:]:
                ts = entry.get('ts', '')
                text = entry.get('text', '')
                try:
                    dt = datetime.fromisoformat(ts)
                    unix = int(dt.timestamp())
                    lines.append(f'  <t:{unix}:f> {text}')
                except (ValueError, TypeError):
                    lines.append(f'  {ts} {text}')
        else:
            # Uebersicht: eine Zeile pro User
            last = entries[-1]
            try:
                dt = datetime.fromisoformat(last.get('ts', ''))
                unix = int(dt.timestamp())
                ts_fmt = f'<t:{unix}:f>'
            except (ValueError, TypeError):
                ts_fmt = last.get('ts', '?')
            lines.append(f'**{name}** — {len(entries)} DMs · Letzte: {ts_fmt}')

    embeds = _paginate_lines('', lines)
    await interaction.followup.send(embeds=embeds, ephemeral=True)


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
        log.exception('cmd_announce fehlgeschlagen für %s', user)
        await interaction.response.send_message('❌ Ein Fehler ist aufgetreten.', ephemeral=True)


@tree.command(name='stats', description='Nutzungsstatistiken aller User anzeigen (Admin)')
@discord.app_commands.default_permissions(administrator=True)
async def cmd_stats(interaction: discord.Interaction):
    all_stats = await asyncio.to_thread(stats.get_all)
    if not all_stats:
        await interaction.response.send_message('Noch keine Statistiken vorhanden.', ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    # User-Infos parallel fetchen statt sequentiell
    uids = list(all_stats.keys())

    async def _fetch_name(uid):
        return uid, await _display_name(uid, interaction.guild)

    results = await asyncio.gather(*[_fetch_name(uid) for uid in uids], return_exceptions=True)
    names = dict(r for r in results if isinstance(r, tuple))

    lines = []
    for uid, data in all_stats.items():
        puzzles = data.get('puzzles', 0)
        downloads = data.get('downloads', 0)
        solved = data.get('reaction_✅', 0)
        failed = data.get('reaction_❌', 0)
        liked = data.get('reaction_👍', 0)
        disliked = data.get('reaction_👎', 0)
        trashed = data.get('reaction_🚮', 0)
        name = names.get(uid, f'User {uid}')
        line = f'**{name}** — 🧩 {puzzles} · 📥 {downloads}'
        if solved or failed:
            line += f' · ✅ {solved} · ❌ {failed}'
        if liked or disliked:
            line += f' · 👍 {liked} · 👎 {disliked}'
        if trashed:
            line += f' · 🚮 {trashed}'
        lines.append(line)

    embeds = _paginate_lines('📊 **Statistiken**\n', lines)
    await interaction.followup.send(embeds=embeds, ephemeral=True)


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
        log.exception('Fehler bei /daily')
        await interaction.followup.send('Fehler beim Posten des Daily Puzzles.', ephemeral=True)


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
        log.exception('puzzle_task fehlgeschlagen')

# ---------------------------------------------------------------------------

dm_log.install()
bot.run(DISCORD_TOKEN)
