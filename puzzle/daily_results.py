"""Tagespuzzle-Ergebnisse auf Discord visualisieren.

Merkt sich den Daily-Post (Channel/Message/Puzzle-ID) und pollt RookHub
(``GET /api/book-puzzles/{id}/results``). Der Post wird dann aktualisiert:
ein Embed-Feld mit der Solver-Zeile (verknüpfte User als @mention, sonst
RookHub-Name; Fehlversuche nur als Zahl). Keine ✅-Reaction mehr — die Solver
stehen ohnehin im Embed-Feld (redundant).

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
# Wird auch von puzzle.embed.build_daily_embed verwendet (dort als
# DAILY_SOLVER_FIELD). Wenn der Name hier geaendert wird, dort mitziehen.
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
    """Aktueller (zuletzt gemerkter) Daily-Post.

    Es gibt jeweils genau einen aktuellen Daily-Post: ``remember()`` ueberschreibt
    die Datei beim Posten des naechsten Daily-Puzzles. Deshalb kein striktes
    Datums-Check mehr — sonst friert das Embed zwischen UTC-Mitternacht und dem
    naechsten /daily-Lauf ein (User, die in dem Zeitfenster loesen, wuerden im
    Embed nicht erscheinen).
    """
    data = atomic_read(DAILY_FILE, default=dict)
    if not data or not data.get('channel_id') or not data.get('message_id'):
        return None
    return data


def _fmt_time(seconds: int) -> str:
    """Formatiert Sekunden als m:ss (ab 60 s) oder Xs."""
    if seconds <= 0:
        return ''
    if seconds < 60:
        return f'{seconds}s'
    return f'{seconds // 60}:{seconds % 60:02d}'


def format_solver_line(results: dict, max_names: int = MAX_NAMES) -> str:
    """Baut die Solver-Zeile fürs Embed-Feld (rein, testbar). Eingeloggte Löser namentlich,
    anonyme Löser nur als Anzahl („+N anonym"). Gesamtzahl = eingeloggt + anonym."""
    solvers = results.get('solvers') or []
    named = results.get('solvedCount', len(solvers))
    anon = results.get('anonymousSolvedCount', 0)
    attempts = results.get('attemptCount', 0)
    total = named + anon
    if total <= 0:
        return f'Noch niemand gelöst · 🧩 {attempts} dran versucht'
    shown = []
    for s in solvers[:max_names]:
        did = s.get('discordId')
        name = f'<@{did}>' if did else (s.get('name') or '—')
        t = _fmt_time(s.get('timeSeconds', 0))
        # Mit Tipps gelöst (HintsUsed > 0 im wertungsrelevanten Erstversuch) → Glühbirne in Klammern.
        hint = ' (💡)' if s.get('hintsUsed', 0) > 0 else ''
        shown.append((f'{name} ({t})' if t else name) + hint)
    body = ''
    if shown:
        more = named - len(shown)
        body = ', '.join(shown) + (f' +{more} weitere' if more > 0 else '')
    if anon > 0:
        body = (body + ' · ' if body else '') + f'{anon} anonym'
    suffix = f' · 🧩 {attempts} dran versucht' if attempts > total else ''
    return f'✅ Gelöst ({total}): {body}{suffix}'


def _field_name(f):
    """Liefert den Feld-Namen von EmbedProxy (prod) oder dict (FakeEmbed-Tests)."""
    return f.get('name') if isinstance(f, dict) else getattr(f, 'name', None)


async def apply_solver_update(bot, cur: dict, results: dict) -> None:
    """Wendet einen Solver-Stand auf den gemerkten Daily-Post an (Embed editieren).
    Wird sowohl vom 5-Min-Polling (refresh) als auch vom RookHub-Webhook
    (webhook_server) aufgerufen.

    cur: Daten aus :func:`current` (channel_id, message_id, puzzle_id).
    results: ``GET /api/book-puzzles/{id}/results``-Payload bzw. das gleiche
    DTO, das RookHub im Webhook mitschickt.
    """
    import asyncio
    import discord
    from core import reinforcement

    # Neue Solver vor dem Embed-Update ermitteln (State-Check ist synchron).
    puzzle_id = cur.get('puzzle_id')
    new_solvers = reinforcement.new_puzzle_solvers(puzzle_id, results.get('solvers') or [])

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
        idx = next((i for i, f in enumerate(embed.fields) if _field_name(f) == SOLVER_FIELD), None)
        if idx is None:
            embed.add_field(name=SOLVER_FIELD, value=line, inline=False)
        else:
            embed.set_field_at(idx, name=SOLVER_FIELD, value=line, inline=False)
        # Anhang in Ruhe lassen (das Brett ist der einzige File-Anhang, NICHT
        # im Embed). embed.image leeren, damit Alt-Posts (vor v2.48.0) kein
        # zusaetzliches Bild rendern.
        if hasattr(embed, 'set_image'):
            try:
                embed.set_image(url=None)
            except Exception:
                pass
        await msg.edit(embed=embed)
    except Exception as e:
        log.warning('Daily-Post-Update fehlgeschlagen: %s', e)

    # Reinforcement-DMs asynchron feuern (fire-and-forget).
    for s in new_solvers:
        asyncio.create_task(
            reinforcement.notify_puzzle_solved(bot, s['discordId'], puzzle_id, s.get('timeSeconds', 0))
        )


async def refresh(bot) -> None:
    """Holt die aktuellen Ergebnisse von RookHub und aktualisiert den Daily-Post.

    Polling-Pfad — wird nicht mehr periodisch aus dem 5-Min-Loop aufgerufen
    (Webhook ersetzt das); bleibt als Fallback fuer manuelle Catch-up-Aufrufe
    (z. B. nach Bot-Restart).
    """
    import asyncio
    import puzzle.rookhub as rookhub

    cur = current()
    if not cur:
        return
    results = await asyncio.to_thread(rookhub.get_daily_results, cur['puzzle_id'], cur.get('since'))
    if results is None:
        return
    await apply_solver_update(bot, cur, results)
