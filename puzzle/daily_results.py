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

from core import i18n
from core.json_store import atomic_read, atomic_write
from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

DAILY_FILE = os.path.join(CONFIG_DIR, 'daily_post.json')
# Deutscher Default-Name des Solver-Felds (Rueckwaerts-Kompat). Der tatsaechlich
# verwendete Feldname ist sprachabhaengig — siehe i18n 'daily.solver_field' bzw.
# puzzle.embed.DAILY_SOLVER_FIELD.
SOLVER_FIELD = i18n.t('daily.solver_field', 'de')
MAX_NAMES = 15


def _today() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _posts_of(data: dict) -> list[dict]:
    """Normalisiert auf eine Liste ``[{channel_id, message_id}, …]``.

    Migriert dabei das alte Einzel-Post-Format (top-level ``channel_id``/
    ``message_id`` ohne ``posts``) transparent — keine Datei-Migration noetig.
    """
    posts = data.get('posts')
    if isinstance(posts, list) and posts:
        return [{'channel_id': int(p['channel_id']), 'message_id': int(p['message_id']),
                 'lang': i18n.norm(p.get('lang'))}
                for p in posts if p.get('channel_id') and p.get('message_id')]
    cid, mid = data.get('channel_id'), data.get('message_id')
    if cid and mid:
        return [{'channel_id': int(cid), 'message_id': int(mid), 'lang': i18n.norm(data.get('lang'))}]
    return []


def remember(channel_id, message_id, puzzle_id, lang: str = 'de') -> None:
    """Merkt einen Daily-Post fuer die spaetere Ergebnis-Aktualisierung.

    Mehrkanal-faehig: wird fuer *dasselbe* Tagespuzzle nacheinander pro Channel
    aufgerufen (Haupt-Guild + gespiegelte 2. Guild), sammeln sich die Posts unter
    EINEM Puzzle in der ``posts``-Liste. Ein neues Puzzle (andere ``puzzle_id``)
    oder ein neuer Tag setzt die Liste zurueck. Idempotent pro Channel: ein
    Re-Post desselben Channels ersetzt nur dessen ``message_id`` (Reihenfolge/
    Primaer-Post bleiben stabil).

    Der erste Post (i. d. R. der Haupt-Channel) wird zusaetzlich top-level
    gespiegelt (``channel_id``/``message_id``) — Rueckwaerts-Kompat fuer aelteren
    Code, der den Einzel-Post liest.
    """
    if not channel_id or not message_id or not puzzle_id:
        return
    channel_id, message_id = int(channel_id), int(message_id)
    lang = i18n.norm(lang)
    today = _today()
    data = atomic_read(DAILY_FILE, default=dict) or {}
    same = data.get('date') == today and data.get('puzzle_id') == puzzle_id
    posts = _posts_of(data) if same else []
    for p in posts:  # Upsert in-place (Primaer bleibt stabil)
        if p['channel_id'] == channel_id:
            p['message_id'] = message_id
            p['lang'] = lang
            break
    else:
        posts.append({'channel_id': channel_id, 'message_id': message_id, 'lang': lang})
    primary = posts[0]
    atomic_write(DAILY_FILE, {
        'date': today,
        'puzzle_id': puzzle_id,
        # `since` bleibt der Zeitpunkt des ersten Posts dieses Puzzles (korrektes
        # Poll-Fenster fuer get_daily_results), nicht der jeder Spiegelung.
        'since': data.get('since') if same else datetime.now(timezone.utc).isoformat(),
        'posts': posts,
        'channel_id': primary['channel_id'],
        'message_id': primary['message_id'],
    })


def current() -> dict | None:
    """Aktueller (zuletzt gemerkter) Daily-Post inkl. aller gespiegelten Channels.

    Es gibt jeweils genau ein aktuelles Tagespuzzle; ``remember()`` ueberschreibt
    die Datei beim Posten des naechsten. Deshalb kein striktes Datums-Check —
    sonst friert das Embed zwischen UTC-Mitternacht und dem naechsten /daily-Lauf
    ein. Das Ergebnis enthaelt immer eine normalisierte ``posts``-Liste (auch fuer
    migriertes Alt-Format).
    """
    data = atomic_read(DAILY_FILE, default=dict)
    if not data:
        return None
    posts = _posts_of(data)
    if not posts:
        return None
    data = dict(data)
    data['posts'] = posts
    data.setdefault('channel_id', posts[0]['channel_id'])
    data.setdefault('message_id', posts[0]['message_id'])
    return data


def _fmt_time(seconds: int) -> str:
    """Formatiert Sekunden als m:ss (ab 60 s) oder Xs."""
    if seconds <= 0:
        return ''
    if seconds < 60:
        return f'{seconds}s'
    return f'{seconds // 60}:{seconds % 60:02d}'


def format_solver_line(results: dict, max_names: int = MAX_NAMES, lang: str = 'de') -> str:
    """Baut die Solver-Zeile fürs Embed-Feld (rein, testbar) in Sprache ``lang`` (de/en).
    Eingeloggte Löser namentlich, anonyme Löser nur als Anzahl. Gesamt = eingeloggt + anonym."""
    solvers = results.get('solvers') or []
    named = results.get('solvedCount', len(solvers))
    anon = results.get('anonymousSolvedCount', 0)
    attempts = results.get('attemptCount', 0)
    total = named + anon
    if total <= 0:
        return i18n.t('daily.none_solved_attempts', lang, n=attempts)
    shown = []
    for s in solvers[:max_names]:
        did = s.get('discordId')
        name = f'<@{did}>' if did else (s.get('name') or '—')
        tm = _fmt_time(s.get('timeSeconds', 0))
        # Mit Tipps gelöst (HintsUsed > 0 im wertungsrelevanten Erstversuch) → Glühbirne in Klammern.
        hint = ' (💡)' if s.get('hintsUsed', 0) > 0 else ''
        shown.append((f'{name} ({tm})' if tm else name) + hint)
    body = ''
    if shown:
        more = named - len(shown)
        body = ', '.join(shown) + (f' {i18n.t("daily.more", lang, n=more)}' if more > 0 else '')
    if anon > 0:
        body = (body + ' · ' if body else '') + i18n.t('daily.anon', lang, n=anon)
    suffix = i18n.t('daily.attempts_suffix', lang, n=attempts) if attempts > total else ''
    return i18n.t('daily.solved', lang, n=total, body=body) + suffix


def _field_name(f):
    """Liefert den Feld-Namen von EmbedProxy (prod) oder dict (FakeEmbed-Tests)."""
    return f.get('name') if isinstance(f, dict) else getattr(f, 'name', None)


async def _edit_post_embed(bot, channel_id: int, message_id: int, line: str, lang: str = 'de') -> None:
    """Editiert das Solver-Feld EINES gemerkten Daily-Posts (in dessen Sprache ``lang``).
    Fehler bleiben pro Channel isoliert (eine offline/unerreichbare Guild blockiert die
    andere nicht)."""
    import discord

    solver_field = i18n.t('daily.solver_field', lang)
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            return
    try:
        msg = await channel.fetch_message(message_id)
    except Exception as e:
        log.debug('Daily-Message %s nicht gefunden: %s', message_id, e)
        return
    try:
        embed = msg.embeds[0] if msg.embeds else discord.Embed()
        idx = next((i for i, f in enumerate(embed.fields) if _field_name(f) == solver_field), None)
        if idx is None:
            embed.add_field(name=solver_field, value=line, inline=False)
        else:
            embed.set_field_at(idx, name=solver_field, value=line, inline=False)
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
        log.warning('Daily-Post-Update fehlgeschlagen (Channel %s): %s', channel_id, e,
                    extra={'es_fields': {'tags': ['daily', 'puzzle']}})


async def apply_solver_update(bot, cur: dict, results: dict) -> None:
    """Wendet einen Solver-Stand auf ALLE gemerkten Daily-Posts an (Embed editieren).
    Wird sowohl vom Polling (refresh) als auch vom RookHub-Webhook (webhook_server)
    aufgerufen.

    cur: Daten aus :func:`current` (``puzzle_id`` + ``posts``-Liste, ggf. migriertes
    Einzel-Format). results: ``GET /api/book-puzzles/{id}/results``-Payload bzw. das
    gleiche DTO, das RookHub im Webhook mitschickt.

    Die Solver-Daten sind global (pro Puzzle), also fuer alle gespiegelten Channels
    identisch. Neue Solver werden EINMAL ermittelt → Reinforcement-DMs feuern genau
    einmal pro Loeser, unabhaengig von der Channel-Anzahl.
    """
    import asyncio
    from core import reinforcement

    # Neue Solver vor dem Embed-Update ermitteln (State-Check ist synchron).
    puzzle_id = cur.get('puzzle_id')
    new_solvers = reinforcement.new_puzzle_solvers(puzzle_id, results.get('solvers') or [])

    # Solver-Zeile pro Post in dessen Sprache rendern (Channels koennen de/en mischen).
    for post in _posts_of(cur):
        lang = post.get('lang', i18n.DEFAULT_LANG)
        line = format_solver_line(results, lang=lang)
        await _edit_post_embed(bot, post['channel_id'], post['message_id'], line, lang)

    # Reinforcement-DMs asynchron feuern (fire-and-forget) — genau einmal pro Loeser.
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
