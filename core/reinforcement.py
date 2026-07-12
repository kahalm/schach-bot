"""Positives Reinforcement: sofortige Glückwunsch-DM bei Schlüsselmomenten.

Ausgelöst wenn ein Spieler:
- das heutige Tagespuzzle löst  (via Webhook-Pfad in puzzle/daily_results.py)
- einen Wochenpost fertigstellt (via Webhook-Pfad in commands/weeklypost.py)
- alle Tagesziele erfüllt       (via 10-min-Loop in commands/motivation.py)

Zustand in config/reinforcement.json:
  {
    "puzzle":  {"<puzzle_id>":  ["discord_id1", ...]},
    "weekly":  {"<weekly_id>":  ["discord_id1", ...]},
    "goals":   {"<YYYY-MM-DD>": ["discord_id1", ...]}
  }
Jede Kategorie merkt sich, welche Discord-IDs schon eine DM erhalten haben, damit
kein Spieler bei mehreren Webhook-Feuern doppelt beglückwünscht wird.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

REINFORCE_FILE = os.path.join(CONFIG_DIR, 'reinforcement.json')
_MOTIVATION_SUB_FILE = os.path.join(CONFIG_DIR, 'motivation_sub.json')

# --- Drosselung & GC-Schutz fuer fire-and-forget Reinforcement-DMs ---------
# Jeder Daily-Solve-/Weekly-Webhook kann eine ganze Welle neuer Loeser liefern.
# Ohne Begrenzung wuerde pro Loeser sofort ein asyncio.create_task() entstehen
# (Discord-429 + parallele Claude-Aufrufe). Wir
#   1) halten eine Referenz auf jeden Task (sonst kann der GC ihn mittendrin
#      einsammeln — siehe asyncio.create_task-Doku), und
#   2) drosseln die gleichzeitig laufenden DMs ueber ein Semaphore.
_MAX_CONCURRENT_DMS = 3
_dm_semaphore: 'asyncio.Semaphore | None' = None
_pending_tasks: set = set()


def _get_semaphore() -> asyncio.Semaphore:
    global _dm_semaphore
    if _dm_semaphore is None:
        _dm_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_DMS)
    return _dm_semaphore


def spawn_dm(coro) -> 'asyncio.Task':
    """Startet eine Reinforcement-DM-Coroutine gedrosselt + GC-sicher.

    - Die laufende DM wird durch ``_dm_semaphore`` auf ``_MAX_CONCURRENT_DMS``
      gleichzeitig begrenzt (verhindert Discord-429 / Claude-Limit-Bursts).
    - Der erzeugte Task wird in ``_pending_tasks`` gehalten, bis er fertig ist,
      damit der Garbage-Collector ihn nicht vorzeitig verwirft.

    Gibt den Task zurueck (v. a. fuer Tests).
    """
    async def _runner():
        async with _get_semaphore():
            await coro

    task = asyncio.create_task(_runner())
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
    return task


def _default():
    return {'puzzle': {}, 'weekly': {}, 'goals': {}}


def _today() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _motivation_subscriber_ids() -> set[str]:
    """Gibt die Discord-IDs aller aktiven Motivation-Abonnenten zurück."""
    data = atomic_read(_MOTIVATION_SUB_FILE, default=dict)
    if not isinstance(data, dict):
        return set()
    return set((data.get('subscribers') or {}).keys())


# ---------------------------------------------------------------------------
# Zustandsverwaltung
# ---------------------------------------------------------------------------

def _already_notified(category: str, key: str, discord_id: str) -> bool:
    data = atomic_read(REINFORCE_FILE, default=_default)
    if not isinstance(data, dict):
        return False
    return discord_id in (data.get(category) or {}).get(str(key), [])


def _mark_notified(category: str, key: str, discord_id: str) -> None:
    def _u(data):
        if not isinstance(data, dict):
            data = _default()
        cat = data.setdefault(category, {})
        ids = cat.setdefault(str(key), [])
        if discord_id not in ids:
            ids.append(discord_id)
        return data
    atomic_update(REINFORCE_FILE, _u, _default)


# ---------------------------------------------------------------------------
# Neue Empfänger ermitteln (Claim-Semantik)
# ---------------------------------------------------------------------------
# WICHTIG: Ermitteln + Markieren muss EIN atomarer Schritt sein. Wuerde erst
# der DM-Task am Ende markieren (fetch_user + Claude-Call, bis zu ~30s),
# koennte ein ueberlappender Webhook denselben Loeser erneut als "neu" sehen
# und eine Duplikat-DM ausloesen.

def _claim_new(category: str, key: str, candidates: list[dict]) -> list[dict]:
    """Markiert candidates atomar als benachrichtigt; gibt die vorher unmarkierten zurück."""
    fresh: list[dict] = []
    def _u(data):
        fresh.clear()  # atomic_update koennte _u erneut aufrufen → nicht doppelt sammeln
        if not isinstance(data, dict):
            data = _default()
        cat = data.setdefault(category, {})
        ids = cat.setdefault(str(key), [])
        for c in candidates:
            did = c['discordId']
            if did not in ids:
                ids.append(did)
                fresh.append(c)
        return data
    atomic_update(REINFORCE_FILE, _u, _default)
    return fresh


def new_puzzle_solvers(puzzle_id, solvers: list) -> list[dict]:
    """Solver (Motivation-Abonnenten) ohne bisherige Puzzle-DM — werden dabei
    atomar als benachrichtigt markiert (Claim), damit überlappende Webhooks
    keine Duplikat-DMs auslösen."""
    subs = _motivation_subscriber_ids()
    candidates = [s for s in solvers if s.get('discordId') and s['discordId'] in subs]
    return _claim_new('puzzle', str(puzzle_id), candidates)


def new_weekly_completions(weekly_id, players: list) -> list[dict]:
    """Players (Motivation-Abonnenten) mit `completed=True` ohne bisherige
    Weekly-DM — werden dabei atomar als benachrichtigt markiert (Claim)."""
    subs = _motivation_subscriber_ids()
    candidates = [p for p in players
                  if p.get('discordId') and p['discordId'] in subs and p.get('completed')]
    return _claim_new('weekly', str(weekly_id), candidates)


def goals_not_yet_notified_today(discord_id: str) -> bool:
    """True, wenn für diesen User heute noch keine Ziele-DM gesendet wurde."""
    return not _already_notified('goals', _today(), discord_id)


# ---------------------------------------------------------------------------
# DM-Texte via Claude (mit Fallback)
# ---------------------------------------------------------------------------

_PUZZLE_SYSTEM = (
    'Du bist ein warmherziger, leicht verspielter Schach-Buddy. Schreibe auf Deutsch, '
    'kurz (1-2 Sätze), mit einem Augenzwinkern und sparsamen Emojis. '
    'Lobe den Spieler herzlich dafür, dass er das heutige Tagespuzzle gelöst hat.'
)
_WEEKLY_SYSTEM = (
    'Du bist ein warmherziger, leicht verspielter Schach-Buddy. Schreibe auf Deutsch, '
    'kurz (1-2 Sätze), mit einem Augenzwinkern und sparsamen Emojis. '
    'Lobe den Spieler herzlich dafür, dass er den kompletten Wochenpost fertig durchgespielt hat.'
)
_GOALS_SYSTEM = (
    'Du bist ein warmherziger, leicht verspielter Schach-Buddy. Schreibe auf Deutsch, '
    'kurz (2 Sätze), mit einem Augenzwinkern und sparsamen Emojis. '
    'Lobe den Spieler herzlich und whimsisch dafür, dass er heute alle Trainingsziele erfüllt hat. '
    'KEINE Aufforderung mehr, noch etwas zu tun — genieß den Moment mit ihm.'
)


_CLAUDE_TIMEOUT = 30.0  # s — Reinforcement laeuft im Loop; haengender Call darf nicht blockieren


async def _via_claude(system: str, prompt: str) -> str | None:
    try:
        from commands.chat import _client, _MODEL
        if _client is None:
            return None
        resp = await asyncio.wait_for(
            _client.messages.create(
                model=_MODEL,
                max_tokens=200,
                system=system,
                messages=[{'role': 'user', 'content': prompt}],
            ),
            timeout=_CLAUDE_TIMEOUT,
        )
        parts = [b.text for b in resp.content if getattr(b, 'type', None) == 'text']
        return ''.join(parts).strip() or None
    except Exception:
        log.debug('Reinforcement-Claude-Aufruf fehlgeschlagen')
        return None


def _fmt_time(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return ''
    if seconds < 60:
        return f'{seconds}s'
    return f'{seconds // 60}:{seconds % 60:02d} min'


async def _puzzle_text(time_secs: int) -> str:
    time_part = f' in {_fmt_time(time_secs)}' if time_secs and time_secs > 0 else ''
    prompt = f'Der Spieler hat das heutige Tagespuzzle gelöst{time_part}. Beglückwünsche ihn kurz und herzlich.'
    return await _via_claude(_PUZZLE_SYSTEM, prompt) or f'🎉 Tagespuzzle gelöst{time_part} — stark gemacht!'


async def _weekly_text() -> str:
    prompt = 'Der Spieler hat den Wochenpost komplett durchgespielt. Beglückwünsche ihn kurz und herzlich.'
    return await _via_claude(_WEEKLY_SYSTEM, prompt) or '🏆 Wochenpost fertig — das war eine starke Leistung!'


async def _goals_text(cats: list) -> str:
    labels = ', '.join(f'{label} {done}/{target} {unit}' for label, done, target, _, unit in cats)
    prompt = f'Der Spieler hat heute alle Trainingsziele erfüllt: {labels}. Lobe ihn herzlich.'
    return await _via_claude(_GOALS_SYSTEM, prompt) or '🌟 Alle Tagesziele erfüllt — das verdient echten Applaus!'


# ---------------------------------------------------------------------------
# Öffentliche Notify-Funktionen
# ---------------------------------------------------------------------------

async def notify_puzzle_solved(bot, discord_id: str, puzzle_id, time_secs: int = 0) -> None:
    """Glückwunsch-DM an einen neuen Puzzle-Löser.

    Als benachrichtigt markiert wurde er bereits beim Claim in
    ``new_puzzle_solvers`` (verhindert Duplikat-DMs bei überlappenden Webhooks).
    """
    key = str(puzzle_id)
    try:
        text = await _puzzle_text(time_secs)
        user = await bot.fetch_user(int(discord_id))
        dm = await user.create_dm()
        await dm.send(text)
        log.info('Puzzle-Reinforcement an %s (puzzle=%s)', discord_id, key)
    except Exception:
        log.debug('Puzzle-Reinforcement-DM an %s fehlgeschlagen', discord_id)


async def notify_weekly_completed(bot, discord_id: str, weekly_id) -> None:
    """Glückwunsch-DM an einen Spieler, der den Wochenpost fertig hat.

    Markiert wurde er bereits beim Claim in ``new_weekly_completions``.
    """
    key = str(weekly_id)
    try:
        text = await _weekly_text()
        user = await bot.fetch_user(int(discord_id))
        dm = await user.create_dm()
        await dm.send(text)
        log.info('Weekly-Reinforcement an %s (weekly=%s)', discord_id, key)
    except Exception:
        log.debug('Weekly-Reinforcement-DM an %s fehlgeschlagen', discord_id)


async def notify_goals_met(bot, discord_id: str, cats: list) -> None:
    """Glückwunsch-DM wenn ein Motivation-Abonnent alle Tagesziele erfüllt hat."""
    today = _today()
    try:
        text = await _goals_text(cats)
        user = await bot.fetch_user(int(discord_id))
        dm = await user.create_dm()
        await dm.send(text)
        log.info('Goals-Reinforcement an %s (date=%s)', discord_id, today)
    except Exception:
        log.debug('Goals-Reinforcement-DM an %s fehlgeschlagen', discord_id)
    finally:
        await asyncio.to_thread(_mark_notified, 'goals', today, discord_id)
