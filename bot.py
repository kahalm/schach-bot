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
import math
import discord
from discord.ext import tasks, commands
import json
import os
import signal
from datetime import datetime, timezone

# stats/discord_link/json_store nutzt bot.py selbst nicht mehr (Admin-Befehle, Begruessung);
# der Import bleibt hier, damit Reihenfolge und Zeitpunkt (vor load_dotenv) gleich bleiben.
from core import stats, dm_log, command_log, es_client  # noqa: F401
from core import discord_link  # noqa: F401
from core import command_sync
from core import config as _config
from core.json_store import atomic_read, atomic_update  # noqa: F401
from core.paths import CONFIG_DIR
from core.permissions import set_guild_id, set_moderator_role_id
from core.version import VERSION

from dotenv import load_dotenv
load_dotenv()

# Env-Parsing + Pruefung in core/config.py (ungueltige Zahlen → SystemExit wie bisher); das
# Token prueft erst main(). Die Modul-Namen bleiben fuer die Verdrahtung und die Tests.
CFG = _config.load()
DISCORD_TOKEN = CFG.discord_token
CHANNEL_ID = CFG.channel_id
DAILY_DEFAULT_LANG = CFG.daily_default_lang
DAILY_CHANNEL_IDS: list[int] = list(CFG.daily_channel_ids)
DAILY_CHANNEL_LANG: dict[int, str] = dict(CFG.daily_channel_lang)
TOURNAMENT_CHANNEL_ID = CFG.tournament_channel_id
GUILD_ID = CFG.guild_id
WOCHENPOST_CHANNEL_ID = CFG.wochenpost_channel_id
PUZZLE_HOUR, PUZZLE_MINUTE = CFG.puzzle_hour, CFG.puzzle_minute
WEBHOOK_BIND_HOST, WEBHOOK_PORT, WEBHOOK_SECRET = (
    CFG.webhook_bind_host, CFG.webhook_port, CFG.webhook_secret)

# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

from commands.motivation import activity_watch_needs_presences

# Privilegierte Intents nur, soweit genutzt (ein geleakter Token soll nicht mehr sehen als noetig):
# - message_content AUS: Nachrichteninhalt liest der Bot nur in DMs (on_message, commands/chat.py)
#   und in eigenen Posts – beides nimmt Discord vom Intent aus; Prefix-Befehle gibt es keine.
# - members AN: Mitglieder-Cache fuer Begruessung (on_member_join) und guild.get_member.
# - presences nur, solange der Activity-Watch von /motivation laufen kann (einziger Praesenz-Leser).
# Im Discord Developer Portal entsprechend abschalten, sonst bleibt der Token dort breiter.
intents = discord.Intents.default()
intents.message_content = False
intents.members = True
intents.presences = activity_watch_needs_presences()
# S4-004: /resourcen, /youtube und /wanted wiederholen Freitext oeffentlich. Global keine
# @everyone/@here- und Rollen-Pings; Nutzer-Erwaehnungen (Begruessung, Erinnerungen) bleiben.
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents,
                   allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True))
bot._task_loops = {}
tree = bot.tree

# Module laden
import puzzle
import library
from commands import reminder, resourcen, youtube, elo, release_notes, blind, test, wanted, schachrallye, weeklypost, chat, link, motivation, leaderboard
from commands import help as help_cmd
from commands import admin, welcome
from puzzle import daily_task

puzzle.setup(bot, channel_langs=DAILY_CHANNEL_LANG, home_guild_id=GUILD_ID)
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
weeklypost.setup(bot, wochenpost_channel_id=WOCHENPOST_CHANNEL_ID)
chat.setup(bot)
link.setup(bot)
motivation.setup(bot)
leaderboard.setup(bot, channel_id=CHANNEL_ID)
help_cmd.setup(bot, guild_id=GUILD_ID)
# Tagespuzzle-Loop (Post-Zeit aus der Config), Begruessung (on_message/on_member_join),
# Admin-/Info-Befehle (/version … /daily) – Reihenfolge wie frueher in bot.py.
puzzle_task = daily_task.configure(bot, DAILY_CHANNEL_IDS, DAILY_CHANNEL_LANG, DAILY_DEFAULT_LANG,
                                   PUZZLE_HOUR, PUZZLE_MINUTE)
welcome.setup(bot, guild_id=GUILD_ID, rookhub_web_url=CFG.rookhub_web_url)
admin.setup(bot)


_ready_done = False

HEALTH_FILE = os.path.join(CONFIG_DIR, 'health.json')


def _write_health():
    """Schreibt config/health.json mit aktuellem Status."""
    data = {
        'status': 'ok',
        'version': VERSION,
        'ts': datetime.now(timezone.utc).isoformat(),
        'latency_ms': round(bot.latency * 1000) if bot.latency and math.isfinite(bot.latency) else None,
        'guilds': len(bot.guilds),
    }
    os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
    tmp = HEALTH_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    os.replace(tmp, HEALTH_FILE)


async def _sync_commands():
    """Slash-Commands syncen (Haupt-Guild alle, global nur /puzzle): core/command_sync.py."""
    await command_sync.sync_commands(tree, GUILD_ID)


@bot.event
async def on_ready():
    global _ready_done
    if _ready_done:
        log.info('Reconnect als %s (on_ready übersprungen)', bot.user)
        return
    _ready_done = True
    # Persistente Button-Views registrieren
    bot.add_view(puzzle.PuzzleView())
    from commands.turnier_buttons import TurnierReviewView
    bot.add_view(TurnierReviewView())
    for attempt, delay in enumerate([0, 5, 15, 30], 1):
        try:
            if delay:
                await asyncio.sleep(delay)
            await _sync_commands()
            break
        except Exception:
            log.warning('tree.sync() Versuch %d/4 fehlgeschlagen', attempt)
            if attempt == 4:
                log.error('tree.sync() endgültig fehlgeschlagen — Commands evtl. nicht verfügbar')
    log.info('Bot online als %s v%s', bot.user, VERSION)
    try:
        await asyncio.to_thread(_write_health)
    except Exception:
        log.warning('health.json schreiben fehlgeschlagen (on_ready)')
    puzzle_task.start()
    # Startzeitpunkt merken: davon haengt ab, ob der Loop heute noch selbst postet
    # (discord.py plant einen nach der Post-Zeit gestarteten time-Loop auf morgen).
    puzzle_loop_started = datetime.now(timezone.utc)
    _health_loop.start()
    bot._task_loops['puzzle_task'] = puzzle_task
    bot._task_loops['health_loop'] = _health_loop
    # Webhook-Server fuer RookHub-Solver-Events (ersetzt das 5-Min-Polling).
    try:
        from core import webhook_server
        bot._webhook_runner = await webhook_server.start(
            bot, WEBHOOK_BIND_HOST, WEBHOOK_PORT, WEBHOOK_SECRET,
            daily_channels=[(c, daily_task._daily_lang(c)) for c in DAILY_CHANNEL_IDS])
    except Exception as e:
        log.exception('Webhook-Server konnte nicht starten: %s', e)
    # Verpasste Solver-Updates direkt nach Start einmal nachholen (Bot war evtl.
    # zwischenzeitlich offline und hat Webhooks verpasst).
    try:
        from puzzle import daily_results
        await daily_results.refresh(bot)
    except Exception:
        log.warning('Initialer daily_results.refresh fehlgeschlagen')
    # ...und den Tagespuzzle-POST selbst nachholen, wenn er heute ausgefallen ist (Bot war
    # zur Loop-Zeit offline). Ohne das gaebe es an dem Tag gar kein Daily — und faellt der
    # 1. aus, verzoegert sich der Vormonats-Endstand (haengt am Daily-Post).
    # `puzzle_loop_started` entscheidet ueber Doppel-Post vs. Catch-up (siehe catchup_due).
    try:
        from puzzle import daily_results
        if DAILY_CHANNEL_IDS and daily_results.catchup_due(
                daily_results.current(), datetime.now(timezone.utc), PUZZLE_HOUR, PUZZLE_MINUTE,
                loop_started=puzzle_loop_started):
            log.warning('Tagespuzzle von heute fehlt (Bot war zur Post-Zeit offline?) — wird nachgeholt.',
                        extra={'es_fields': {'tags': ['daily', 'puzzle']}})
            await daily_task._post_daily_to_all()
    except Exception:
        log.exception('Daily-Catch-up beim Start fehlgeschlagen',
                      extra={'es_fields': {'tags': ['daily', 'puzzle']}})
    # Linien-Cache im Hintergrund vorwaermen, damit der erste /puzzle-Aufruf
    # nach einem Neustart nicht auf das PGN-Parsing warten muss.
    try:
        await asyncio.to_thread(puzzle.load_all_lines)
    except Exception:
        log.warning('Linien-Cache-Vorwaermen fehlgeschlagen')


# --- Health + Heartbeat ---

@tasks.loop(seconds=60)
async def _health_loop():
    if bot.is_ready():
        try:
            await asyncio.to_thread(_write_health)
        except Exception as e:
            log.warning('Health-Write fehlgeschlagen: %s', e)
        # Lebenszeichen an RookHub (→ rookhub-logs in ES), damit der log-watcher einen toten
        # Bot an ausbleibenden Heartbeats erkennt. Fire-and-forget, blockiert den Loop nicht.
        try:
            from puzzle import rookhub
            await asyncio.to_thread(rookhub.send_heartbeat)
        except Exception as e:
            log.debug('RookHub-Heartbeat fehlgeschlagen: %s', e)

# --- Befehls-Protokoll: jeder Slash-Befehl landet in ES (Tag "command") ---

@bot.listen('on_app_command_completion')
async def _log_app_command(interaction: discord.Interaction, command):
    command_log.log_command(interaction, command)

# --- Cooldown-Error-Handler ---

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    command_log.log_command(interaction, outcome=command_log.outcome_for(error), error=error)
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f'⏳ Bitte warte {error.retry_after:.0f}s.', ephemeral=True)
    else:
        log.exception('Unbehandelter Command-Fehler: %s', error)
        try:
            msg = '⚠️ Ein Fehler ist aufgetreten.'
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        except Exception:
            pass

# ---------------------------------------------------------------------------

def _install_sigterm_close(loop) -> bool:
    """SIGTERM (``docker stop``, Watchtower-Neustart) → ``bot.close()`` im Event-Loop.

    Ohne Handler schliesst der Bot die Gateway-Sitzung nie selbst, und ``docker stop`` endet
    nach 10 s mit SIGKILL. True, wenn der Handler sitzt."""
    tasks_held = []   # Referenz halten, sonst darf der GC den close-Task mitten im Lauf einsammeln

    def _on_sigterm():
        log.info('SIGTERM empfangen – Bot wird beendet.')
        tasks_held.append(loop.create_task(bot.close()))
    try:
        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
    except (NotImplementedError, RuntimeError):   # Windows bzw. nicht im Hauptthread
        return False
    return True


async def _setup_hook():
    _install_sigterm_close(asyncio.get_running_loop())


def main():
    """Startet den Bot – nur beim direkten Aufruf (``python bot.py``). ``import bot`` (Tests)
    registriert Befehle und Events, braucht aber kein Token und verbindet nicht."""
    if not DISCORD_TOKEN:
        raise SystemExit(_config.TOKEN_MISSING)
    dm_log.install()
    set_guild_id(GUILD_ID)
    set_moderator_role_id(CFG.moderator_role_id)
    bot.setup_hook = _setup_hook   # der SIGTERM-Handler braucht den laufenden Loop
    try:
        bot.run(DISCORD_TOKEN)
    finally:
        es_client.shutdown()   # Warteschlange kurz nachsenden, Verluste ins Log


if __name__ == '__main__':
    main()
