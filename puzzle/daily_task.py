"""Tagespuzzle: Post in alle Daily-Channels + der taegliche Loop (frueher in bot.py).

- ``_post_daily_to_all``: dasselbe RookHub-Tagespuzzle in jeden Daily-Channel (auch andere
  Guilds), Vormonats-Endstand in denselben Thread, danach Loeser-Stand holen
- ``puzzle_task``: Loop zur Post-Zeit (PUZZLE_HOUR/PUZZLE_MINUTE, UTC), rotiert danach das
  Reaction-Log; ``configure`` legt ihn an (bot.py startet ihn in on_ready)
- Aufrufer: Loop, Catch-up beim Start (bot.py) und ``/daily`` (commands/admin.py)

Hinweis: Der 5-Min-Polling-Loop fuer Daily-Solver wurde entfernt — RookHub feuert seit
v0.75.0 einen Webhook nach jedem Buch-Puzzle-Attempt (siehe core/webhook_server.py +
puzzle/daily_results.apply_solver_update). Beim Bot-Start wird einmalig refresh() als
Catch-up fuer verpasste Events aufgerufen (siehe bot.on_ready).
"""

import asyncio
import logging
from datetime import time

from discord.ext import tasks

import puzzle

log = logging.getLogger('schach-bot')

# Von bot.py per configure() gesetzt (Tests setzen die Werte direkt).
_bot = None
DAILY_CHANNEL_IDS: list[int] = []
_channel_lang: dict[int, str] = {}
_default_lang = 'de'
puzzle_task = None


def configure(bot, daily_channel_ids: list[int], channel_lang: dict[int, str],
              default_lang: str, hour: int, minute: int):
    """Bot + Daily-Channels/-Sprachen merken und den Tages-Loop zur Post-Zeit anlegen."""
    global _bot, DAILY_CHANNEL_IDS, _channel_lang, _default_lang, puzzle_task
    _bot = bot
    DAILY_CHANNEL_IDS = daily_channel_ids
    _channel_lang = channel_lang
    _default_lang = default_lang
    puzzle_task = _make_loop(hour, minute)
    return puzzle_task


def _make_loop(hour: int, minute: int):
    @tasks.loop(time=time(hour=hour, minute=minute))
    async def puzzle_task():
        await run_daily_task()
    return puzzle_task


def _daily_lang(cid: int) -> str:
    return _channel_lang.get(cid, _default_lang)


async def _post_daily_to_all() -> list[tuple[int, bool]]:
    """Postet das Tagespuzzle in alle konfigurierten Daily-Channels (auch in anderen
    Guilds) und gibt ``(channel_id, erfolg)`` je Channel zurueck.

    Dasselbe Puzzle ueberall: RookHubs ``daily``-Pool ist pro Tag deterministisch, also
    liefert jeder Aufruf dieselbe Puzzle-ID. Das Solver-Tracking sammelt die Posts via
    ``daily_results.remember()`` (Upsert pro Channel unter einem Puzzle)."""
    # Am Monatsanfang: Vormonats-Endstand vorbereiten, um ihn in JEDEN Tagespuzzle-Thread
    # nachzulegen (statt eines eigenstaendigen Posts). Faellig in den ersten Tagen des Monats
    # (leaderboard.monthly_due → Nachhol-Fenster, falls der 1. ausfiel), aber genau einmal je
    # Monat: Dedupe via leaderboard-State, markiert erst nach erfolgreichem Post.
    from commands import leaderboard as _lb
    endstand_month = _lb.monthly_due()
    endstand_embed = None
    if endstand_month:
        try:
            endstand_embed = await _lb.build_endstand_embed(endstand_month)
        except Exception:
            log.exception('Monats-Endstand-Embed konnte nicht gebaut werden (%s)', endstand_month)
    endstand_posted = False

    results: list[tuple[int, bool]] = []
    for cid in DAILY_CHANNEL_IDS:
        channel = _bot.get_channel(cid)
        if channel is None:
            try:
                channel = await _bot.fetch_channel(cid)
            except Exception:
                channel = None
        if channel is None:
            log.warning('Daily-Channel %s nicht gefunden.', cid)
            results.append((cid, False))
            continue
        try:
            pid, target = await puzzle.post_rookhub_puzzle(
                channel, 'daily', with_board=True, lang=_daily_lang(cid), return_target=True)
            results.append((cid, pid is not None))
            # Endstand in DENSELBEN Thread wie das Tagespuzzle nachlegen.
            if endstand_embed is not None and target is not None:
                try:
                    await target.send(embed=endstand_embed)
                    endstand_posted = True
                except Exception:
                    log.exception('Monats-Endstand-Post in Channel %s fehlgeschlagen', cid)
        except Exception:
            log.exception('Daily-Post in Channel %s fehlgeschlagen', cid,
                          extra={'es_fields': {'tags': ['daily', 'puzzle']}})
            results.append((cid, False))

    # Monat erst als abgerechnet markieren, wenn der Endstand mindestens einmal gepostet wurde.
    if endstand_month and endstand_posted:
        _lb.mark_monthly_posted(endstand_month)
    # Loeser, die das Puzzle auf RookHub schon VOR dem Post geloest haben, sofort eintragen
    # (der Webhook kaeme erst beim naechsten Versuch).
    if any(ok for _, ok in results):
        try:
            from puzzle import daily_results
            await daily_results.refresh(_bot)
        except Exception:
            log.warning('Loeser-Stand nach dem Daily-Post nicht geholt',
                        extra={'es_fields': {'tags': ['daily', 'puzzle']}})
    return results


async def run_daily_task():
    """Ein Lauf des Tages-Loops: posten (Fehler nur loggen), danach Reaction-Log rotieren."""
    if not DAILY_CHANNEL_IDS:
        log.warning('Kein Daily-Channel konfiguriert (CHANNEL_ID/DAILY_EXTRA_CHANNEL_IDS).')
        return
    try:
        await _post_daily_to_all()
    except Exception:
        log.exception('puzzle_task fehlgeschlagen',
                      extra={'es_fields': {'tags': ['daily', 'puzzle']}})
    # Reaction-Log rotieren
    try:
        from core.event_log import rotate_log
        await asyncio.to_thread(rotate_log)
    except Exception as e:
        log.warning('Reaction-Log Rotation fehlgeschlagen: %s', e)
