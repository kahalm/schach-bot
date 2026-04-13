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
from datetime import datetime, timezone

from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

REACTION_LOG_FILE = os.path.join(CONFIG_DIR, 'reaction_log.jsonl')


def _current_elo(user_id: int) -> int | None:
    """Aktuelle Elo des Users (oder None). Lazy-Import um Zyklen zu vermeiden."""
    try:
        from commands.elo import get_current
        return get_current(user_id)
    except Exception as e:
        log.debug('Elo-Lookup fehlgeschlagen: %s', e)
        return None


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
        with open(REACTION_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError as e:
        log.warning('Reaction-Log Schreibfehler: %s', e)


def read_all() -> list[dict]:
    """Liest das gesamte JSONL-Log (für spätere Auswertungen)."""
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
    return entries
