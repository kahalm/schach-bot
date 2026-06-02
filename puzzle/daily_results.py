"""Tagespuzzle-Ergebnisse auf Discord visualisieren.

Merkt sich den Daily-Post (Channel/Message/Puzzle-ID) und pollt RookHub
(``GET /api/book-puzzles/{id}/results``). Der Post wird dann aktualisiert:
✅-Reaction + ein Embed-Feld mit der Solver-Zeile (verknüpfte User als @mention,
sonst RookHub-Name; Fehlversuche nur als Zahl).

Top-Level bewusst ohne discord-/puzzle-Paket-Importe (nur stdlib + core), damit die
reine Formatierungslogik eigenständig testbar ist; schwere Importe liegen in refresh().
"""

import logging
import os
from datetime import datetime, timezone

from core.json_store import atomic_read, atomic_write
from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

DAILY_FILE = os.path.join(CONFIG_DIR, 'daily_post.json')
SOLVER_FIELD = '🏆 Tagespuzzle'
MAX_NAMES = 15


def _today() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def remember(channel_id, message_id, puzzle_id) -> None:
    """Speichert den heutigen Daily-Post für die spätere Ergebnis-Aktualisierung."""
    if not channel_id or not message_id or not puzzle_id:
        return
    atomic_write(DAILY_FILE, {
        'date': _today(),
        'channel_id': int(channel_id),
        'message_id': int(message_id),
        'puzzle_id': puzzle_id,
        'since': datetime.now(timezone.utc).isoformat(),
    })


def current() -> dict | None:
    """Daily-Post von HEUTE (oder None)."""
    data = atomic_read(DAILY_FILE, default=dict)
    if not data or data.get('date') != _today():
        return None
    return data


def format_solver_line(results: dict, max_names: int = MAX_NAMES) -> str:
    """Baut die Solver-Zeile fürs Embed-Feld (rein, testbar)."""
    solvers = results.get('solvers') or []
    solved = results.get('solvedCount', len(solvers))
    attempts = results.get('attemptCount', 0)
    if solved <= 0:
        return f'Noch niemand gelöst · 🧩 {attempts} dran versucht'
    shown = []
    for s in solvers[:max_names]:
        did = s.get('discordId')
        shown.append(f'<@{did}>' if did else (s.get('name') or '—'))
    more = solved - len(shown)
    tail = f' +{more} weitere' if more > 0 else ''
    return f'✅ Gelöst ({solved}): ' + ', '.join(shown) + tail + f' · 🧩 {attempts} dran versucht'


async def refresh(bot) -> None:
    """Holt die aktuellen Ergebnisse und aktualisiert den heutigen Daily-Post."""
    import asyncio
    import discord
    import puzzle.rookhub as rookhub

    cur = current()
    if not cur:
        return
    results = await asyncio.to_thread(rookhub.get_daily_results, cur['puzzle_id'], cur.get('since'))
    if results is None:
        return

    channel = bot.get_channel(cur['channel_id'])
    if channel is None:
        try:
            channel = await bot.fetch_channel(cur['channel_id'])
        except Exception:
            return
    try:
        msg = await channel.fetch_message(cur['message_id'])
    except Exception as e:
        log.debug('Daily-Message %s nicht gefunden: %s', cur.get('message_id'), e)
        return

    line = format_solver_line(results)
    try:
        embed = msg.embeds[0] if msg.embeds else discord.Embed()
        idx = next((i for i, f in enumerate(embed.fields) if f.name == SOLVER_FIELD), None)
        if idx is None:
            embed.add_field(name=SOLVER_FIELD, value=line, inline=False)
        else:
            embed.set_field_at(idx, name=SOLVER_FIELD, value=line, inline=False)
        await msg.edit(embed=embed)
        if results.get('solvedCount', 0) > 0:
            try:
                await msg.add_reaction('✅')
            except Exception:
                pass
    except Exception as e:
        log.warning('Daily-Post-Update fehlgeschlagen: %s', e)
