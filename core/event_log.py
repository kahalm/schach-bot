"""Event-Log für Reaktionen auf Puzzles.

Append-only JSONL: jede Reaktion (auch Entfernen via delta=-1) wird mit
Zeitstempel, User, Puzzle-ID, Modus (normal/blind), Emoji und der
aktuellen Elo des Users (falls hinterlegt) festgehalten. Damit lassen
sich später Auswertungen wie "Erfolgsquote über Zeit", "Blind vs Normal"
oder "Performance pro Elo-Bracket" erstellen.

Datei: ``config/reaction_log.jsonl``
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone

from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

REACTION_LOG_FILE = os.path.join(CONFIG_DIR, 'reaction_log.jsonl')
_log_lock = threading.Lock()


_elo_cache: dict[int, int | None] = {}
_elo_cache_ts: float = 0.0
_ELO_CACHE_TTL = 60.0  # Sekunden


def _current_elo(user_id: int) -> int | None:
    """Aktuelle Elo des Users (oder None). Gecached fuer 60s."""
    import time
    global _elo_cache, _elo_cache_ts
    now = time.monotonic()
    if now - _elo_cache_ts > _ELO_CACHE_TTL:
        _elo_cache.clear()
        _elo_cache_ts = now
    if user_id in _elo_cache:
        return _elo_cache[user_id]
    try:
        from commands.elo import get_current
        val = get_current(user_id)
    except Exception as e:
        log.debug('Elo-Lookup fehlgeschlagen: %s', e)
        val = None
    _elo_cache[user_id] = val
    return val


def log_reaction(user_id: int,
                 line_id: str | None,
                 mode: str,
                 emoji: str,
                 delta: int = 1):
    """Schreibt eine Reaktions-Zeile ins JSONL-Log.

    delta = +1 bei add, -1 bei remove.
    """
    entry = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'user': user_id,
        'line_id': line_id,
        'mode': mode,
        'emoji': emoji,
        'delta': delta,
        'elo': _current_elo(user_id),
    }
    try:
        with _log_lock:
            with open(REACTION_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError as e:
        log.warning('Reaction-Log Schreibfehler: %s', e)


_MAX_LOG_LINES = 50_000


def read_all(limit: int = _MAX_LOG_LINES) -> list[dict]:
    """Liest das JSONL-Log (neueste `limit` Eintraege)."""
    entries: list[dict] = []
    try:
        with open(REACTION_LOG_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    if len(entries) > limit:
        entries = entries[-limit:]
    return entries


def rotate_log():
    """Kuerzt das JSONL-Log auf die neuesten _MAX_LOG_LINES Eintraege."""
    try:
        with open(REACTION_LOG_FILE, encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return
    if len(lines) <= _MAX_LOG_LINES:
        return
    trimmed = lines[-_MAX_LOG_LINES:]
    with _log_lock:
        with open(REACTION_LOG_FILE, 'w', encoding='utf-8') as f:
            f.writelines(trimmed)
    log.info('Reaction-Log rotiert: %d → %d Zeilen', len(lines), len(trimmed))
