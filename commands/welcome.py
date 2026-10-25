"""Begruessung: Willkommens-DM bei Beitritt bzw. erster DM, Text mit RookHub-Registrier-Link.

- ``WELCOME_MESSAGE`` + ``welcome_message_for`` (auch fuer ``/announce``)
- ``on_message`` (erste DM eines Heim-Mitglieds) und ``on_member_join`` (nur Heim-Guild),
  von ``setup`` per ``bot.event`` registriert
- ``DM_STATE_FILE`` haelt die Liste der Begruessten (``/greeted`` liest sie)
"""

import asyncio
import logging
import os

import discord

from core import discord_link, dm_log
from core.json_store import atomic_update
from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

DM_STATE_FILE   = os.path.join(CONFIG_DIR, 'dm_state.json')

WELCOME_MESSAGE = (
    'Hallo! Ich bin der Schach-Bot eurer Servergruppe. ♟️\n\n'
    '**Was ich kann:**\n'
    '🧩 `/puzzle` — Zufällige Taktikrätsel per DM\n'
    '🙈 `/blindpuzzle` — Blind-Puzzle von RookHub (im Kopf rechnen)\n'
    '♾️ `/endless` — Endlos-Modus: nach jeder Antwort kommt das nächste Puzzle\n'
    '📚 `/kurs` — Alle Puzzle-Bücher mit Fortschritt\n'
    '📖 `/bibliothek` — Schachbuch-Bibliothek durchsuchen & downloaden\n'
    '🔗 `/resourcen` — Online-Lernressourcen anzeigen oder hinzufügen\n'
    '▶️ `/youtube` — YouTube-Kanäle/Videos anzeigen oder hinzufügen\n'
    '⏰ `/reminder` — Wiederkehrende Puzzle-DMs einstellen\n'
    '🏅 `/elo` — Eigene Schach-Elo angeben\n'
    '🔗 `/link` — RookHub-Konto mit Discord verknüpfen\n'
    '🏆 `/turnier` — Turniere in Tirol anzeigen\n'
    '🔔 `/turnier_sub` — Bei neuen Turnieren gepingt werden\n'
    '🏇 `/schachrallye` — Schachrallye-Termine anzeigen\n'
    '💡 `/wanted` — Feature-Wünsche einreichen\n'
    '🏆 `/bestenliste` — Tagespuzzle: Monats-Wertung + Hall of Fame\n\n'
    'Mit `/help` siehst du alle Befehle im Detail.'
)

# Von setup() gesetzt (Tests setzen die Werte direkt).
_bot = None
GUILD_ID = 0
ROOKHUB_WEB_URL = ''


def setup(bot, guild_id: int, rookhub_web_url: str):
    """Heim-Guild + Web-URL merken, ``on_message``/``on_member_join`` am Bot registrieren."""
    global _bot, GUILD_ID, ROOKHUB_WEB_URL
    _bot = bot
    GUILD_ID = guild_id
    ROOKHUB_WEB_URL = rookhub_web_url
    bot.event(on_message)
    bot.event(on_member_join)


def welcome_message_for(user) -> str:
    """WELCOME_MESSAGE + personalisierter RookHub-Registrierungs-CTA.

    Hängt (falls ``ROOKHUB_WEB_URL`` gesetzt) einen Link auf ``…/register`` an. Ist zusätzlich
    ``ROOKHUB_LINK_SECRET`` gesetzt, trägt der Link ein signiertes ``?dl=``-Token mit der
    Discord-ID des Users. Da die Begrüßung IMMER per DM (privat) geht, ist das Token sicher:
    klickt der User und registriert sich, wird sein Discord-Konto automatisch verknüpft.
    """
    if not ROOKHUB_WEB_URL:
        return WELCOME_MESSAGE
    username = getattr(user, 'name', None) or getattr(user, 'display_name', None)
    url = discord_link.append_dl(f'{ROOKHUB_WEB_URL}/register', user.id, username) \
        or f'{ROOKHUB_WEB_URL}/register'
    return (
        WELCOME_MESSAGE
        + '\n\n— — —\n'
        + '🌐 **RookHub** ist das Portal zum Bot: Puzzle-Statistiken & Elo-Verlauf, Kurse, '
          'Turnierdaten u. v. m.\n'
        + f'👉 Registriere dich für alle Features: {url}\n'
        + '_Über diesen persönlichen Link wird dein Discord-Konto nach der Registrierung '
          'automatisch verknüpft._'
    )


async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not isinstance(message.channel, discord.DMChannel):
        return

    # Eingehende DM loggen
    await asyncio.to_thread(dm_log.log_incoming, message.author.id, message.content or '[kein Text]')

    # Erste DM → Bot stellt sich vor (nur Mitgliedern der Heim-Guild; nicht als begrüßt
    # markieren, sonst fehlte die Begrüßung, wenn sie später beitreten)
    if not _is_home_member(message.author):
        return
    user_id = message.author.id
    should_greet = False

    def _check_and_greet(data):
        nonlocal should_greet
        greeted = data.get('greeted', [])
        if user_id in set(greeted):
            return data  # bereits begrüßt
        should_greet = True
        greeted.append(user_id)
        # Deduplizieren (bereinigt historisch gewachsene Listen)
        data['greeted'] = list(dict.fromkeys(greeted))
        return data

    await asyncio.to_thread(atomic_update, DM_STATE_FILE, _check_and_greet, dict)
    if should_greet:
        await message.channel.send(welcome_message_for(message.author))


def _is_home_member(user) -> bool:
    """Begrüßungs-DMs nur für die Heim-Guild (GUILD_ID): Die Willkommens-DM ist deutsch und
    bewirbt Befehle, die es in Zusatz-Guilds (nur /puzzle) nicht gibt. Ohne GUILD_ID: alle."""
    if not GUILD_ID:
        return True
    guild = _bot.get_guild(GUILD_ID)
    return guild is not None and guild.get_member(user.id) is not None


async def on_member_join(member: discord.Member):
    if member.bot:
        return
    if GUILD_ID and getattr(member.guild, 'id', None) != GUILD_ID:
        return  # Zusatz-Guild (gespiegeltes Daily): keine unaufgeforderte DM
    try:
        dm = await member.create_dm()
        await dm.send(welcome_message_for(member))
        # In greeted-Liste eintragen, damit on_message kein Doppel-Willkommen schickt
        def _mark_greeted(data):
            greeted = data.get('greeted', [])
            if member.id not in set(greeted):
                greeted.append(member.id)
                data['greeted'] = greeted
            return data
        await asyncio.to_thread(atomic_update, DM_STATE_FILE, _mark_greeted, dict)
    except discord.Forbidden:
        log.warning('Kann DM an %s nicht senden (DMs deaktiviert).', member)
    except Exception as e:
        log.warning('Willkommens-DM fehlgeschlagen für %s: %s', member, e)
