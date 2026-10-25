"""turnier.json – einziger Besitzer der Turnier-/Rallye-Datei (lesen, schreiben, sperren).

Alle Termine liegen in EINER Datei mit Tags (``schachrallye`` = Rallye-Termin mit Reminder +
Subscribern), dazu ``subscribers`` (Tag → User-IDs), ``reviewers`` und ``next_id``. Andere
Module fassen ``TURNIER_FILE`` nicht an, sondern lesen/aendern ueber ``read``/``update``
(``core.json_store``: Lock je Datei, atomares Ersetzen).
"""

import logging
import os
from datetime import date, timedelta

from commands import termine
from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

TURNIER_FILE = os.path.join(CONFIG_DIR, 'turnier.json')
_PRUNE_DAYS = 90  # Alte Events nach N Tagen entfernen


def _fresh_default():
    """Frisches Default-Dict (Deep Copy) — vermeidet Shared-State durch shallow copy."""
    return {"events": [], "subscribers": {}, "reviewers": [], "next_id": 1}


def read() -> dict:
    """Inhalt von turnier.json (fehlend/kaputt → ``{}``)."""
    return atomic_read(TURNIER_FILE, default=dict)


def update(fn, default=None):
    """``fn(data) -> data`` unter dem Datei-Lock anwenden und atomar zurueckschreiben."""
    return atomic_update(TURNIER_FILE, fn, default=default)


def _prune_old_events():
    """Entfernt Events die aelter als _PRUNE_DAYS Tage sind."""
    cutoff = date.today() - timedelta(days=_PRUNE_DAYS)
    pruned = [0]

    def _prune(data):
        before = len(data.get('events', []))
        data['events'] = [
            e for e in data.get('events', [])
            if (termine._parse_stored(e.get('datum', '')) or date.min) >= cutoff
        ]
        pruned[0] = before - len(data['events'])
        return data

    update(_prune, default=_fresh_default)
    if pruned[0]:
        log.info('Turnier-Prune: %d alte Events entfernt (> %d Tage).', pruned[0], _PRUNE_DAYS)
