"""Einfache User-Statistiken (Rätsel, Downloads)."""

import json
import os

from core.paths import CONFIG_DIR

STATS_FILE = os.path.join(CONFIG_DIR, 'user_stats.json')


def _load() -> dict:
    try:
        with open(STATS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict):
    with open(STATS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def inc(user_id: int, key: str, n: int = 1):
    """Zähler für user_id[key] um n erhöhen."""
    data = _load()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {}
    data[uid][key] = data[uid].get(key, 0) + n
    _save(data)


def get(user_id: int) -> dict:
    """Alle Zähler für einen User."""
    return _load().get(str(user_id), {})


def get_all() -> dict:
    """Alle User-Stats."""
    return _load()
