"""Einfache User-Statistiken (Rätsel, Downloads)."""

import os

from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR

STATS_FILE = os.path.join(CONFIG_DIR, 'user_stats.json')


def inc(user_id: int, key: str, n: int = 1):
    """Zähler für user_id[key] um n erhöhen."""
    def _update(data):
        uid = str(user_id)
        if uid not in data:
            data[uid] = {}
        data[uid][key] = data[uid].get(key, 0) + n
        return data
    atomic_update(STATS_FILE, _update)


def get(user_id: int) -> dict:
    """Alle Zähler für einen User."""
    return atomic_read(STATS_FILE).get(str(user_id), {})


def get_all() -> dict:
    """Alle User-Stats."""
    return atomic_read(STATS_FILE)
