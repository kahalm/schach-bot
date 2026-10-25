"""Hintergrund-Ablaeufe der Turniere/Schachrallye: Termin-Import, Freigabe-Post, Erinnerung.

- ``_fetch_termine``: tirol.chess.at/termine/ abrufen (3 Versuche) → ``termine.parse_termine``
- ``parse_and_store``: neue Termine als pending in turnier.json, Review-DMs an die Reviewer
  (``/turnier_parse`` und der Auto-Parse-Loop rufen dieselbe Funktion)
- ``_post_approved_event``: freigegebenes Event im Turnier-Channel (von ``turnier_buttons``)
- ``remind_due``: ein Lauf des Rallye-Reminders (``/test`` nutzt ``termine.due_reminders`` +
  ``_reminder_embed`` + ``_reminder_channel`` als Dry-Run, keine zweite Kopie)
- ``install_loops``: Reminder alle 6 h + Auto-Parse taeglich 18:00 UTC, Start bei on_ready

Laufzeitkontext (Bot, Turnier-Channel) setzt ``configure`` aus ``schachrallye.setup``.
"""

import asyncio
import logging
from datetime import date, time

import discord
import requests
from discord.ext import tasks

from commands import termine, turnier_store
from core.datetime_utils import noon_utc_ts as _noon_utc_ts
from core.version import EMBED_COLOR

log = logging.getLogger('schach-bot')

RALLYE_URL = 'https://tirol.chess.at/termine/'

_bot = None
_tournament_channel_id = 0


def configure(bot, tournament_channel_id: int = 0):
    """Bot + Turnier-Channel fuer Posts, Reminder und Review-DMs merken."""
    global _bot, _tournament_channel_id
    _bot = bot
    _tournament_channel_id = tournament_channel_id


def _fetch_termine() -> list[dict]:
    """Fetcht tirol.chess.at/termine/ und gibt Termine mit Tags zurueck.

    Returns: Liste von Event-Dicts mit keys: datum, datum_text, name, ort, link, tags.
    """
    import time as _time_mod

    from core.version import VERSION
    headers = {'User-Agent': f'schach-bot/{VERSION}'}
    resp = None
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(RALLYE_URL, timeout=15, headers=headers)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            last_exc = e
            log.warning('Termine-Fetch Versuch %d/3 fehlgeschlagen: %s', attempt + 1, e)
            if attempt < 2:
                _time_mod.sleep(2 ** attempt)  # 1s, 2s Backoff (laeuft im Thread)
    if resp is None:
        raise last_exc if last_exc else RuntimeError('Termine-Fetch fehlgeschlagen')
    return termine.parse_termine(resp.text)


# ---------------------------------------------------------------------------
# Post-Logik (importiert von turnier_buttons.py)
# ---------------------------------------------------------------------------

async def _post_approved_event(event: dict, extra_mention_ids: set | None = None):
    """Postet ein freigegebenes Event im Tournament-Channel mit Mentions."""
    if not _tournament_channel_id:
        return
    channel = _bot.get_channel(_tournament_channel_id)
    if not channel:
        return

    subs_data = turnier_store.read().get('subscribers', {})
    dt = event.get('datum_text', event.get('datum', ''))
    ort = termine._shorten_ort(event.get('ort', ''))
    link = event.get('link', '')
    tags = event.get('tags', [])
    desc = f"\U0001f4c5 `{dt}`"
    if ort:
        desc += f" \u00b7 {ort}"
    if tags:
        desc += '\n' + ' '.join(f'`{t}`' for t in tags)
    # Subscriber-Mentions sammeln
    mention_ids = set()
    for t in tags:
        mention_ids.update(subs_data.get(t, []))
    if extra_mention_ids:
        mention_ids.update(extra_mention_ids)
    mention_text = (' '.join(f'<@{uid}>' for uid in mention_ids)
                    if mention_ids else '')
    embed = discord.Embed(
        title=event.get('name', ''),
        description=desc,
        color=EMBED_COLOR,
    )
    if link and termine._is_valid_url(link):
        embed.url = link
    embed.set_footer(text='tirol.chess.at/termine/')
    try:
        await channel.send(content=mention_text or None, embed=embed)
    except Exception:
        log.exception('Turnier-Post fehlgeschlagen fuer %s', event.get('name', ''))



# ---------------------------------------------------------------------------
# Rallye-Erinnerung: der Reminder-Loop und /test (Dry-Run) rufen dieselben
# Funktionen auf – keine zweite Kopie der Regeln (termine.due_reminders).
# ---------------------------------------------------------------------------

def _reminder_embed(event: dict) -> discord.Embed:
    """Das Embed der Rallye-Erinnerung fuer ``event`` (Channel-Post des Reminder-Loops)."""
    ts = _noon_utc_ts(termine._parse_stored(event['datum']))
    name = event.get('name', '')
    ort = termine._shorten_ort(event.get('ort', ''))
    desc_text = f'**Termin #{event["id"]}**'
    if name:
        desc_text += f' \u2014 **{name}**'
    desc_text += f' am <t:{ts}:D>'
    if ort:
        desc_text += f' \u00b7 {ort}'
    return discord.Embed(
        title='\U0001f3c7 Schachrallye \u2014 Erinnerung',
        description=desc_text,
        color=EMBED_COLOR,
    )


def _reminder_channel():
    """Der Turnier-Channel des Reminders oder None (ohne TOURNAMENT_CHANNEL_ID / unbekannt)."""
    if not _tournament_channel_id or _bot is None:
        return None
    return _bot.get_channel(_tournament_channel_id)


# ---------------------------------------------------------------------------
# Parse-Logik (shared zwischen /turnier_parse und Auto-Loop)
# ---------------------------------------------------------------------------

def _build_pending_embed(event: dict) -> discord.Embed:
    """Baut ein Embed fuer ein pending Event (Review-DMs + /turnier_pending)."""
    dt = event.get('datum_text', event.get('datum', ''))
    ort = termine._shorten_ort(event.get('ort', ''))
    tags = event.get('tags', [])
    desc = f"\U0001f4c5 `{dt}`"
    if ort:
        desc += f" \u00b7 {ort}"
    if tags:
        desc += '\n' + ' '.join(f'`{t}`' for t in tags)

    embed = discord.Embed(
        title=event.get('name', 'Neues Turnier'),
        description=desc,
        color=0xf39c12,  # Orange fuer Pending
    )
    embed.set_footer(text=f'Event #{event["id"]}')
    return embed


async def _notify_reviewers(added_events: list[dict]):
    """Sendet Review-DMs an alle Reviewer fuer neue Events."""
    from commands.turnier_buttons import TurnierReviewView

    data = turnier_store.read()
    reviewers = data.get('reviewers', [])
    if not reviewers:
        return

    # Event-IDs aus der JSON holen (added_events enthaelt die Roh-Daten,
    # wir brauchen die gespeicherten mit ID)
    all_events = data.get('events', [])
    # Neue Events matchen ueber (datum, name)
    added_keys = {(a['datum'], a['name']) for a in added_events}
    pending = [e for e in all_events
               if (e['datum'], e.get('name', '')) in added_keys
               and e.get('approved') is False]

    for event in pending:
        embed = _build_pending_embed(event)

        for uid in reviewers:
            try:
                user = _bot.get_user(uid) or await _bot.fetch_user(uid)
                dm = await user.create_dm()
                view = TurnierReviewView()
                await dm.send(embed=embed, view=view)
            except Exception:
                log.warning('Review-DM an %s fehlgeschlagen (Event #%d)',
                            uid, event['id'])


async def parse_and_store() -> list[dict]:
    """Fetcht Termine, merged in JSON, ggf. Review oder direkt posten.

    Returns: Liste der neu hinzugefuegten Events.
    """
    new_events = await asyncio.to_thread(_fetch_termine)

    added: list[dict] = []
    merge_result = {}

    def _merge(data):
        if not isinstance(data, dict) or 'events' not in data:
            data = turnier_store._fresh_default()
        merge_result['reviewers'] = data.get('reviewers', [])
        existing = {(e['datum'], e.get('name', '')) for e in data['events']}
        for t in new_events:
            if (t['datum'], t['name']) in existing:
                continue
            new_id = data.get('next_id', 1)
            entry = {
                'id': new_id,
                'datum': t['datum'],
                'datum_text': t.get('datum_text', ''),
                'name': t['name'],
                'ort': t['ort'],
                'link': t.get('link', ''),
                'tags': t.get('tags', []),
                'approved': False,
            }
            if 'schachrallye' in t.get('tags', []):
                entry['reminded'] = False
            data['events'].append(entry)
            data['next_id'] = new_id + 1
            added.append(t)
        return data

    turnier_store.update(_merge)
    reviewers = merge_result.get('reviewers', [])

    if added:
        if reviewers:
            await _notify_reviewers(added)
        else:
            log.warning('Neue Turniere warten auf Freigabe, aber keine Reviewer konfiguriert. '
                        'Nutze /turnier_review zum Subscriben.')

    return added


# ---------------------------------------------------------------------------
# Loops
# ---------------------------------------------------------------------------

async def remind_due():
    channel = _reminder_channel()
    if not channel:
        return

    data = turnier_store.read()
    due, subs = termine.due_reminders(data, date.today())
    remind_ids = []

    for event in due:
        mentions = ' '.join(f'<@{uid}>' for uid in subs)
        embed = _reminder_embed(event)
        try:
            await channel.send(content=mentions, embed=embed)
            # Erst bei erfolgreichem Versand als erinnert markieren — sonst ginge
            # die Erinnerung bei einem Sendefehler verloren (naechster Lauf retryt).
            remind_ids.append(event['id'])
        except Exception:
            log.exception('Rallye-Erinnerung fehlgeschlagen fuer Event #%d', event['id'])

    if remind_ids:
        def _mark_reminded(data):
            if not isinstance(data, dict):
                return data
            for event in data.get('events', []):
                if event['id'] in remind_ids:
                    event['reminded'] = True
            return data
        turnier_store.update(_mark_reminded)


async def auto_parse_once():
    """Ein Lauf des Auto-Parse-Loops: importieren, danach alte Events entfernen."""
    added = await parse_and_store()
    if added:
        log.info('Auto-Parse: %d neue Turniere importiert.', len(added))
    await asyncio.to_thread(turnier_store._prune_old_events)


def install_loops(bot):
    """Reminder-Loop (6 h) + Auto-Parse-Loop (18:00 UTC) anlegen, bei on_ready starten,
    in ``bot._task_loops`` (``/test status``) eintragen."""

    @tasks.loop(hours=6)
    async def _rallye_reminder():
        try:
            await remind_due()
        except Exception:
            log.exception('Rallye-Reminder-Loop fehlgeschlagen')

    @tasks.loop(time=time(hour=18, minute=0))
    async def _auto_parse():
        try:
            await auto_parse_once()
        except Exception:
            log.exception('Auto-Parse fehlgeschlagen')

    @bot.listen('on_ready')
    async def _start_loops():
        if not _rallye_reminder.is_running():
            _rallye_reminder.start()
        if not _auto_parse.is_running():
            _auto_parse.start()

    if hasattr(bot, '_task_loops'):
        bot._task_loops['rallye_reminder'] = _rallye_reminder
        bot._task_loops['auto_parse'] = _auto_parse
