"""Zufalls-Schachsprüche aus assets/sprueche.json (für Motivations-DMs u. ä.)."""

import json
import os
import random
import threading

_sprueche_cache = None
_sprueche_lock = threading.Lock()


def random_spruch() -> str:
    """Gibt einen zufaelligen Spruch als formatierten String zurueck (leer, wenn keiner verfuegbar)."""
    global _sprueche_cache
    with _sprueche_lock:
        if _sprueche_cache is None:
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                'assets', 'sprueche.json')
            try:
                with open(path, encoding='utf-8') as f:
                    _sprueche_cache = json.load(f)
            except Exception:
                _sprueche_cache = []
        if not _sprueche_cache:
            return ''
        s = random.choice(_sprueche_cache)
    text = s.get('text', '')
    autor = s.get('autor')
    if autor:
        return f'_"{text}"_ — {autor}'
    return f'_"{text}"_'
