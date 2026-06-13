"""Tagespuzzle-Leaderboards formatieren (Monats-Ladder + Hall of Fame).

Reine, eigenständig testbare Formatierungs-/Zeitlogik — bewusst OHNE discord-/puzzle-Paket-Importe
(nur stdlib), analog zu :mod:`puzzle.daily_results`. Die Discord-Anbindung (Slash-Command +
monatlicher Auto-Post) liegt in :mod:`commands.leaderboard`; die HTTP-Abfragen in
:mod:`puzzle.rookhub` (``get_daily_leaderboard`` / ``get_daily_hall_of_fame``).
"""

from datetime import datetime

MEDALS = {1: '🥇', 2: '🥈', 3: '🥉'}
MAX_LADDER = 10

_MONTHS_DE = [
    'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
    'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember',
]


def _name(entry: dict) -> str:
    """Verknüpfte Spieler als @mention, sonst RookHub-Name."""
    did = entry.get('discordId')
    return f'<@{did}>' if did else (entry.get('name') or '—')


def _rank_marker(rank: int) -> str:
    return MEDALS.get(rank, f'`{rank}.`')


def _fmt_time(seconds: int) -> str:
    """Sekunden als m:ss (ab 60 s) oder Xs."""
    if not seconds or seconds <= 0:
        return '—'
    if seconds < 60:
        return f'{seconds}s'
    return f'{seconds // 60}:{seconds % 60:02d}'


def format_period(period: str) -> str:
    """„2026-06" → „Juni 2026" (Fallback: unverändert)."""
    try:
        y, m = period.split('-')
        return f'{_MONTHS_DE[int(m) - 1]} {int(y)}'
    except (ValueError, IndexError, AttributeError):
        return period or ''


def format_ladder(ladder: dict, max_entries: int = MAX_LADDER) -> str:
    """Baut den Ladder-Block: Rang · Spieler · Punkte (gelöst, n×🥇)."""
    entries = (ladder or {}).get('entries') or []
    if not entries:
        return 'Noch keine Wertung in diesem Monat — löse das Tagespuzzle, um Punkte zu sammeln!'
    lines = []
    for i, e in enumerate(entries[:max_entries], start=1):
        pts = e.get('points', 0)
        solved = e.get('solved', 0)
        golds = e.get('golds', 0)
        gold_str = f' · {golds}×🥇' if golds else ''
        lines.append(f'{_rank_marker(i)} {_name(e)} — **{pts}** Pkt ({solved} gelöst{gold_str})')
    more = len(entries) - max_entries
    if more > 0:
        lines.append(f'…und {more} weitere')
    return '\n'.join(lines)


def format_hof_list(entries: list, unit: str) -> str:
    """Baut eine Hall-of-Fame-Kategorie (z. B. „🥇 12 gelöst"). Leer → „—"."""
    entries = entries or []
    if not entries:
        return '—'
    lines = []
    for i, e in enumerate(entries, start=1):
        lines.append(f'{_rank_marker(i)} {_name(e)} — {e.get("value", 0)} {unit}')
    return '\n'.join(lines)


def format_fastest(fastest: dict | None) -> str:
    """Baut die „schnellste Lösung"-Zeile. None → „—"."""
    if not fastest:
        return '—'
    date = fastest.get('date') or ''
    suffix = f' ({date})' if date else ''
    return f'{_name(fastest)} — {_fmt_time(fastest.get("timeSeconds", 0))}{suffix}'


# --- Monatlicher Auto-Post: reine Termin-/Dedupe-Logik --------------------------------

def previous_month(now: datetime) -> tuple[int, int]:
    """(Jahr, Monat) des Vormonats relativ zu ``now``."""
    return (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)


def month_key(year: int, month: int) -> str:
    return f'{year:04d}-{month:02d}'


def should_post_monthly(state: dict, now: datetime) -> str | None:
    """Am 1. eines Monats genau einmal den Vormonat posten.

    Gibt den Monatsschlüssel (``yyyy-MM``) zurück, der gepostet werden soll, oder ``None``
    (nicht der 1. / bereits gepostet). Dedupe über ``state['last_posted']``.
    """
    if now.day != 1:
        return None
    key = month_key(*previous_month(now))
    if (state or {}).get('last_posted') == key:
        return None
    return key
