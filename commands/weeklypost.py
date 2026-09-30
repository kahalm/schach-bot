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

from core.datetime_utils import fmt_mmss, parse_utc as _parse_utc
from core.discord_text import (
    EMBED_FIELD_VALUE_MAX, EMBED_TITLE_MAX, clip, escape_display_name, fit_list,
)
from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR
from core.version import EMBED_COLOR
from puzzle import rookhub

log = logging.getLogger('schach-bot')

WEEKLY_STATE_FILE = os.path.join(CONFIG_DIR, 'weekly_posts.json')
_CATCHUP_DAYS = 7        # nur Posts der letzten Woche nachholen (kein uralter Backlog)
_POLL_MINUTES = 30
_MAX_ATTEMPTS = 10       # Fehlversuche je Post (alle 30 min), danach aufgeben + einmal warnen

_bot = None
_channel_id = 0


def _state_default():
    # pending: {post_id: {thread_id, failures}} fuer angelegte, noch nicht fertig angekuendigte Posts
    return {"posted_ids": [], "last_poll": None, "seeded": False, "threads": {}, "pending": {}}


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
        (data.get('pending') or {}).pop(str(post_id), None)
        data['last_poll'] = datetime.now(timezone.utc).isoformat()
        return data
    atomic_update(WEEKLY_STATE_FILE, _u, _state_default)


def _pending(post_id) -> dict:
    data = atomic_read(WEEKLY_STATE_FILE, default=_state_default)
    if not isinstance(data, dict):
        return {}
    entry = (data.get('pending') or {}).get(str(post_id))
    return entry if isinstance(entry, dict) else {}


def _update_pending(post_id, thread_id=None, add_failure=False) -> dict:
    """Merkt den angelegten Thread bzw. zaehlt einen Fehlversuch; gibt den Zwischenstand zurueck."""
    result = {}

    def _u(data):
        if not isinstance(data, dict):
            data = _state_default()
        pending = data.get('pending')
        if not isinstance(pending, dict):
            pending = data['pending'] = {}
        entry = pending.get(str(post_id))
        if not isinstance(entry, dict):
            entry = pending[str(post_id)] = {}
        if thread_id:
            entry['thread_id'] = int(thread_id)
        if add_failure:
            entry['failures'] = int(entry.get('failures', 0) or 0) + 1
        result.update(entry)
        return data

    atomic_update(WEEKLY_STATE_FILE, _u, _state_default)
    return result


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


def _thread_name(post: dict) -> str:
    """Erstellt den Thread-Namen: dd.mm.yyyy [· Titel]."""
    scheduled = post.get('scheduledAt') or post.get('createdAt') or ''
    try:
        dt = _parse_utc(scheduled)
        date_prefix = dt.strftime('%d.%m.%Y')
    except Exception:
        date_prefix = ''
    title = (post.get('title') or '').strip()
    if date_prefix and title:
        return f'{date_prefix} · {title}'[:100]
    return (date_prefix or title or 'Wochenpost')[:100]


async def _existing_thread(channel, thread_id):
    """Der bei einem frueheren, gescheiterten Lauf angelegte Thread – oder None (geloescht)."""
    getter = getattr(channel, 'get_thread', None)
    thread = getter(thread_id) if callable(getter) else None
    if thread is None and _bot is not None:
        try:
            thread = await _bot.fetch_channel(thread_id)
        except Exception:
            thread = None
    return thread


async def _announcement_thread(channel, post: dict):
    """Thread fuer die Ankuendigung: den eines frueheren Fehlversuchs wiederverwenden, sonst neu
    anlegen und SOFORT vormerken – scheitert danach der Versand, legt der naechste Lauf keinen
    weiteren leeren Thread an."""
    pid = post.get('id')
    old_id = _pending(pid).get('thread_id')
    if old_id:
        thread = await _existing_thread(channel, old_id)
        if thread is not None:
            return thread
    thread = await channel.create_thread(name=_thread_name(post), type=discord.ChannelType.public_thread)
    _update_pending(pid, thread_id=getattr(thread, 'id', None))
    return thread


async def _post_announcement(channel, post: dict):
    title = (post.get('title') or 'Wochenpost').strip() or 'Wochenpost'
    url = rookhub.weekly_web_url(post.get('id'))
    thread = await _announcement_thread(channel, post)
    # RookHub erlaubt Titel bis 300 Zeichen, Discord im Embed-Titel nur 256 (sonst HTTP 400).
    embed = discord.Embed(title=clip(title, EMBED_TITLE_MAX), color=EMBED_COLOR)
    base_line = '\U0001f4ec Neuer Wochenpost zum Durchspielen auf RookHub'
    # Optionale, vom Admin gesetzte Kurzbeschreibung (RookHub-Feld) voranstellen, falls vorhanden.
    desc = (post.get('description') or '').strip()
    embed.description = f'{desc}\n\n{base_line}' if desc else base_line
    # Fortschritt sofort befüllen, falls schon Versuche existieren (z.B. Admin-Vorschau vor dem Termin,
    # Bot-Downtime): der Webhook feuert nur beim ERSTEN Versuch je Puzzle und ginge sonst ins Leere, weil
    # zum Zeitpunkt des Versuchs noch kein Ankündigungs-Thread existierte. Pull beim Ankündigen schließt
    # die Lücke und ist selbstheilend.
    results = await asyncio.to_thread(rookhub.get_weekly_results, post.get('id'))
    if results and (results.get('players') or []):
        embed.add_field(name=_WEEKLY_FIELD, value=format_weekly_results(results), inline=False)
    # URL als content → Discord unfurlt sie; im Embed-Text wäre keine Vorschau möglich.
    msg = await thread.send(content=url or None, embed=embed)
    # Embed-Message merken → später per Webhook mit dem Fortschritt aktualisieren.
    remember_weekly(post.get('id'), getattr(thread, 'id', None), getattr(msg, 'id', None))


# ---------------------------------------------------------------------------
# Fortschritts-Anzeige im Thread (per RookHub-Webhook aktualisiert)
# ---------------------------------------------------------------------------

_WEEKLY_FIELD = '\U0001f3c6 Fortschritt'   # 🏆 Fortschritt
_WEEKLY_MAX_NAMES = 15


def remember_weekly(weekly_id, thread_id, message_id) -> None:
    """Merkt sich die Embed-Message des Ankündigungs-Threads (für spätere Fortschritts-Updates)."""
    if weekly_id is None or not thread_id or not message_id:
        return

    def _u(data):
        if not isinstance(data, dict):
            data = _state_default()
        threads = data.setdefault('threads', {})
        threads[str(weekly_id)] = {'channel_id': int(thread_id), 'message_id': int(message_id)}
        return data

    atomic_update(WEEKLY_STATE_FILE, _u, _state_default)


def _thread_for(weekly_id):
    data = atomic_read(WEEKLY_STATE_FILE, default=_state_default)
    if not isinstance(data, dict):
        return None
    return (data.get('threads') or {}).get(str(weekly_id))


def _field_name(f):
    """Feld-Name von EmbedProxy (prod) oder dict (FakeEmbed-Tests)."""
    return f.get('name') if isinstance(f, dict) else getattr(f, 'name', None)


def _fmt_secs(s) -> str:
    """Gesamtzeit als m:ss bzw. h:mm:ss; 0/fehlend → '0:00'."""
    return fmt_mmss(s, hours=True) or '0:00'


def _count(value) -> int:
    """Zaehlwert aus der Webhook-Payload robust nach int (fehlend/None/Muell → 0)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _mode_suffix(p: dict) -> str:
    """Kurz-Markierung des Spielmodus je Spieler.

    RookHub kennt zwei Modi: „training" (Brett eingefroren, Standard/Altbestand) und „easy"
    (Figuren ziehbar). Markiert wird nur die Abweichung vom Standard — reines Training bekommt
    nichts, damit die Bestenliste kurz und scannbar bleibt. Fehlen die Felder (aeltere
    RookHub-Version), ist die Ausgabe identisch zu vorher.
    """
    easy = _count(p.get('easyCount'))
    if easy <= 0:
        return ''
    return f' · {easy}× einfach'


def format_weekly_results(results: dict) -> str:
    """Baut den Embed-Feld-Text: wer erledigt + gelöst/total + Gesamtzeit je User (rein, testbar)."""
    players = results.get('players') or []
    total = results.get('total', 0)
    completed = results.get('completedCount', 0)
    if not players:
        return 'Noch niemand dabei.'
    lines = []
    for p in players[:_WEEKLY_MAX_NAMES]:
        did = p.get('discordId')
        name = f'<@{did}>' if did else (escape_display_name(p.get('name')) or '—')
        mark = '✅ ' if p.get('completed') else ''   # ✅ bei erledigt
        hint = ' (💡)' if p.get('hintsUsed', 0) > 0 else ''   # 💡 wenn (bei mind. 1 Puzzle) mit Tipps gelöst
        mode = _mode_suffix(p)   # z.B. „· 2× einfach" (Figuren ziehbar); reines Training bleibt leer
        lines.append(f"{mark}{name} — {p.get('solvedCount', 0)}/{total} · {_fmt_secs(p.get('totalSeconds', 0))}{hint}{mode}")
    head = f'{completed} erledigt' if completed else 'noch keiner fertig'

    def _render(shown):
        body = '\n'.join(shown)
        more = len(players) - len(shown)
        if more > 0:
            body += f'\n+{more} weitere'
        return f'{body}\n_({head})_'

    # Discord lehnt Feldwerte > 1024 Zeichen ab: dann fallen hinten Zeilen weg („+N weitere").
    return fit_list(lines, _render, EMBED_FIELD_VALUE_MAX)


async def apply_weekly_update(bot, weekly_id, results: dict) -> None:
    """Aktualisiert das Embed-Feld des gemerkten Wochenpost-Threads mit dem Fortschritt."""
    import discord
    from core import reinforcement

    # Neue Abschließer vor dem Embed-Update ermitteln.
    new_completions = reinforcement.new_weekly_completions(weekly_id, results.get('players') or [])

    t = _thread_for(weekly_id)
    if not t:
        log.debug('Weekly-Update: kein gemerkter Thread fuer %s', weekly_id)
        return
    channel = bot.get_channel(t['channel_id'])
    if channel is None:
        try:
            channel = await bot.fetch_channel(t['channel_id'])
        except Exception:
            return
    try:
        msg = await channel.fetch_message(t['message_id'])
    except Exception as e:
        log.debug('Weekly-Message %s nicht gefunden: %s', t.get('message_id'), e)
        return
    value = format_weekly_results(results)
    try:
        embed = msg.embeds[0] if msg.embeds else discord.Embed()
        idx = next((i for i, f in enumerate(embed.fields) if _field_name(f) == _WEEKLY_FIELD), None)
        if idx is None:
            embed.add_field(name=_WEEKLY_FIELD, value=value, inline=False)
        else:
            embed.set_field_at(idx, name=_WEEKLY_FIELD, value=value, inline=False)
        await msg.edit(embed=embed)
    except Exception as e:
        log.warning('Weekly-Post-Update fehlgeschlagen: %s', e)

    # Reinforcement-DMs asynchron feuern (fire-and-forget) — gedrosselt + GC-sicher.
    for p in new_completions:
        reinforcement.spawn_dm(
            reinforcement.notify_weekly_completed(bot, p['discordId'], weekly_id)
        )


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
            log.info('Wochenpost #%s angekündigt.', p.get('id'),
                     extra={'es_fields': {'tags': ['weekly']}})
        except Exception:
            log.exception('Wochenpost-Ankündigung #%s fehlgeschlagen', p.get('id'),
                          extra={'es_fields': {'tags': ['weekly']}})
            state = _update_pending(p.get('id'), add_failure=True)
            if state.get('failures', 0) >= _MAX_ATTEMPTS:
                # Dauerfehler (z. B. fehlendes Recht im Thread): nicht eine Woche lang alle 30 min.
                _mark_posted(p.get('id'))
                log.warning('Wochenpost #%s nach %d Fehlversuchen aufgegeben (Thread %s) – '
                            'bitte von Hand ankündigen.', p.get('id'), state.get('failures'),
                            state.get('thread_id') or '-', extra={'es_fields': {'tags': ['weekly']}})


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
