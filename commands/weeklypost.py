"""Wochenpost-Ankündigung: RookHub ist Source of Truth, der Bot kündigt fällige Wochenposts nur noch an.

Pull-basiert: ein Loop pollt `GET /api/weekly-posts` und postet jeden fälligen, noch nicht angekündigten
Post als Discord-Thread mit Link auf `…/weekly/{id}`. Bereits gepostete IDs liegen in
`config/weekly_posts.json` (kein Doppelposten; Catch-up bei Bot-Downtime). Beim ERSTEN Lauf werden alle
bereits existierenden Posts als „gepostet" markiert (Hochwassermarke), damit der Backlog nicht nachträglich
in Discord landet — danach werden nur neue, fällige Posts angekündigt.

Das frühere Bot-seitige Anlegen/Posten (commands/wochenpost.py) ist entfallen; verwaltet wird auf RookHub.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

from core.datetime_utils import parse_utc as _parse_utc
from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR
from core.version import EMBED_COLOR
from puzzle import rookhub

log = logging.getLogger('schach-bot')

WEEKLY_STATE_FILE = os.path.join(CONFIG_DIR, 'weekly_posts.json')
_CATCHUP_DAYS = 7        # nur Posts der letzten Woche nachholen (kein uralter Backlog)
_POLL_MINUTES = 30

_bot = None
_channel_id = 0


def _state_default():
    return {"posted_ids": [], "last_poll": None, "seeded": False}


def _posted_ids() -> set:
    data = atomic_read(WEEKLY_STATE_FILE, default=_state_default)
    if not isinstance(data, dict):
        return set()
    return set(data.get('posted_ids', []))


def _mark_posted(post_id):
    def _u(data):
        if not isinstance(data, dict):
            data = _state_default()
        ids = data.setdefault('posted_ids', [])
        if post_id not in ids:
            ids.append(post_id)
        data['last_poll'] = datetime.now(timezone.utc).isoformat()
        return data
    atomic_update(WEEKLY_STATE_FILE, _u, _state_default)


def _seed_if_first_run(all_ids) -> bool:
    """Markiert beim ersten Lauf alle vorhandenen Post-IDs als 'gepostet' (Hochwassermarke).

    Idempotent über das 'seeded'-Flag. Gibt True zurück, wenn in DIESEM Aufruf geseedet wurde
    (dann soll der Aufrufer nichts posten).
    """
    result = {'seeded': False}

    def _u(data):
        if not isinstance(data, dict):
            data = _state_default()
        if not data.get('seeded'):
            ids = set(data.get('posted_ids', []))
            ids.update(i for i in all_ids if i is not None)
            data['posted_ids'] = sorted(ids)
            data['seeded'] = True
            result['seeded'] = True
        return data

    atomic_update(WEEKLY_STATE_FILE, _u, _state_default)
    return result['seeded']


async def _post_announcement(channel, post: dict):
    title = (post.get('title') or 'Wochenpost').strip() or 'Wochenpost'
    url = rookhub.weekly_web_url(post.get('id'))
    thread = await channel.create_thread(name=title[:100], type=discord.ChannelType.public_thread)
    embed = discord.Embed(title=title, color=EMBED_COLOR)
    if url:
        embed.description = f'\U0001f4ec Neuer Wochenpost zum Durchspielen auf RookHub:\n{url}'
    await thread.send(embed=embed)
    if url:
        await thread.send(url)   # zusätzlicher Plaintext-Link (klickbar + Vorschau)


async def run_weekly_announcements():
    """Pollt RookHub und kündigt fällige, noch nicht gepostete Wochenposts an."""
    if not _channel_id or _bot is None:
        return
    channel = _bot.get_channel(_channel_id)
    if not channel:
        log.warning('Weekly-Channel %s nicht gefunden.', _channel_id)
        return

    posts = await asyncio.to_thread(rookhub.get_weekly_posts)
    if not posts:
        return

    all_ids = [p.get('id') for p in posts if isinstance(p, dict)]
    if _seed_if_first_run(all_ids):
        log.info('Weekly-Announcer: %d bestehende Posts als Hochwassermarke geseedet.', len(all_ids))
        return

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_CATCHUP_DAYS)
    posted = _posted_ids()

    due = []
    for p in posts:
        if not isinstance(p, dict):
            continue
        pid, sched = p.get('id'), p.get('scheduledAt')
        if pid is None or pid in posted or not sched:
            continue
        try:
            when = _parse_utc(sched)   # scheduledAt ist Wall-Clock; als UTC behandelt reicht fürs Fenster
        except Exception:
            continue
        if cutoff <= when <= now:
            due.append((when, p))
    due.sort(key=lambda t: t[0])   # älteste zuerst

    for _, p in due:
        try:
            await _post_announcement(channel, p)
            _mark_posted(p.get('id'))
            log.info('Wochenpost #%s angekündigt.', p.get('id'))
        except Exception:
            log.exception('Wochenpost-Ankündigung #%s fehlgeschlagen', p.get('id'))


def setup(bot, wochenpost_channel_id: int = 0):
    global _bot, _channel_id
    _bot = bot
    _channel_id = wochenpost_channel_id

    @tasks.loop(minutes=_POLL_MINUTES)
    async def _weekly_loop():
        try:
            await run_weekly_announcements()
        except Exception:
            log.exception('Weekly-Announcer-Loop fehlgeschlagen')

    @bot.listen('on_ready')
    async def _start_weekly_loop():
        if not _weekly_loop.is_running():
            _weekly_loop.start()

    if hasattr(bot, '_task_loops'):
        bot._task_loops['weeklypost'] = _weekly_loop
