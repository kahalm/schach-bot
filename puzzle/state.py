"""Zustand und Persistenz: Puzzle-Msg-Registry, Ignore-Listen, Endless-Sessions,
Puzzle-/Study-/Training-State, Books-Config-Cache."""

import json
import logging
import os
import time as _time_mod
from collections import OrderedDict
from datetime import date as _date

from core.json_store import atomic_read, atomic_write, atomic_update
from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

# --- File-Pfade ---
IGNORE_FILE = os.path.join(CONFIG_DIR, 'puzzle_ignore.json')
CHAPTER_IGNORE_FILE = os.path.join(CONFIG_DIR, 'chapter_ignore.json')
BOOKS_DIR = os.getenv('BOOKS_DIR', 'books')
PUZZLE_STUDY_ID = os.getenv('PUZZLE_STUDY_ID', '')
PUZZLE_STATE_FILE = os.path.join(CONFIG_DIR, 'puzzle_state.json')
USER_STUDIES_FILE = os.path.join(CONFIG_DIR, 'user_studies.json')
LICHESS_COOLDOWN_FILE = os.path.join(CONFIG_DIR, 'lichess_cooldown.json')

# ---------------------------------------------------------------------------
# Puzzle-Nachrichten-Registry
# ---------------------------------------------------------------------------
# WICHTIG: Nur aus dem asyncio Event Loop mutieren (nicht aus Threads)!
_PUZZLE_MSG_CAP = 500
_puzzle_msg_ids: OrderedDict[int, dict] = OrderedDict()


def _register_puzzle_msg(msg_id: int, line_id: str, mode: str = 'normal'):
    _puzzle_msg_ids[msg_id] = {'line_id': line_id, 'mode': mode}
    while len(_puzzle_msg_ids) > _PUZZLE_MSG_CAP:
        _puzzle_msg_ids.popitem(last=False)


def is_puzzle_message(msg_id: int) -> bool:
    return msg_id in _puzzle_msg_ids


def get_puzzle_line_id(msg_id: int) -> str | None:
    entry = _puzzle_msg_ids.get(msg_id)
    return entry['line_id'] if entry else None


def get_puzzle_mode(msg_id: int) -> str | None:
    """'normal' oder 'blind' — None wenn die Nachricht nicht registriert ist."""
    entry = _puzzle_msg_ids.get(msg_id)
    return entry['mode'] if entry else None


# ---------------------------------------------------------------------------
# Ignore-System
# ---------------------------------------------------------------------------
_ignore_cache: set[str] | None = None


def _load_ignore_list() -> set[str]:
    global _ignore_cache
    if _ignore_cache is None:
        _ignore_cache = set(atomic_read(IGNORE_FILE, default=list))
    return _ignore_cache


def _invalidate_ignore_cache():
    global _ignore_cache
    _ignore_cache = None


def ignore_puzzle(line_id: str):
    def _add(data):
        s = set(data)
        s.add(line_id)
        return sorted(s)
    atomic_update(IGNORE_FILE, _add, default=list)
    _invalidate_ignore_cache()


def unignore_puzzle(line_id: str):
    def _remove(data):
        s = set(data)
        s.discard(line_id)
        return sorted(s)
    atomic_update(IGNORE_FILE, _remove, default=list)
    _invalidate_ignore_cache()


_chapter_ignore_cache: set[str] | None = None


def _load_chapter_ignore_list() -> set[str]:
    """Lädt ignorierte Kapitel als Set von '<filename>:<chapter_prefix>'."""
    global _chapter_ignore_cache
    if _chapter_ignore_cache is None:
        _chapter_ignore_cache = set(atomic_read(CHAPTER_IGNORE_FILE, default=list))
    return _chapter_ignore_cache


def _invalidate_chapter_ignore_cache():
    global _chapter_ignore_cache
    _chapter_ignore_cache = None


def _is_chapter_ignored(line_id: str, chapter_ignored: set[str]) -> bool:
    """Prüft, ob die line_id zu einem ignorierten Kapitel gehört.
    Extrahiert 'filename:chapter' aus line_id und prüft Set-Mitgliedschaft (O(1))."""
    colon = line_id.find(':')
    if colon < 0:
        return False
    rest = line_id[colon + 1:]
    dot = rest.find('.')
    if dot < 0:
        return False
    key = line_id[:colon + 1 + dot]  # "filename:chapter"
    return key in chapter_ignored


def ignore_chapter(book_filename: str, chapter_prefix: str):
    entry = f'{book_filename}:{chapter_prefix}'
    def _add(data):
        s = set(data)
        s.add(entry)
        return sorted(s)
    atomic_update(CHAPTER_IGNORE_FILE, _add, default=list)
    _invalidate_chapter_ignore_cache()


def unignore_chapter(book_filename: str, chapter_prefix: str):
    entry = f'{book_filename}:{chapter_prefix}'
    def _remove(data):
        s = set(data)
        s.discard(entry)
        return sorted(s)
    atomic_update(CHAPTER_IGNORE_FILE, _remove, default=list)
    _invalidate_chapter_ignore_cache()


def get_chapter_from_line_id(line_id: str) -> tuple[str, str] | None:
    """Extrahiert (book_filename, chapter_prefix) aus einer line_id, oder None."""
    if ':' not in line_id:
        return None
    fname, _, round_part = line_id.partition(':')
    if '.' not in round_part:
        return None
    return (fname, round_part.split('.', 1)[0])


# ---------------------------------------------------------------------------
# Endless-Modus
# ---------------------------------------------------------------------------
_endless_sessions: dict[int, dict] = {}
_ENDLESS_TIMEOUT_SECS = 7200  # 2 Stunden


def _evict_stale_endless():
    """Entfernt Endless-Sessions, die seit >2h inaktiv sind."""
    now = _time_mod.time()
    stale = [uid for uid, s in _endless_sessions.items()
             if now - s.get('last_active', 0) > _ENDLESS_TIMEOUT_SECS]
    for uid in stale:
        _endless_sessions.pop(uid, None)
    if stale:
        log.info('Endless: %d inaktive Session(s) aufgeräumt.', len(stale))


def start_endless(user_id: int, book_filename: str | None = None):
    _evict_stale_endless()
    _endless_sessions[user_id] = {'book': book_filename, 'count': 0,
                                  'last_active': _time_mod.time()}


def stop_endless(user_id: int) -> int:
    """Session beenden, gibt Anzahl gelöster Puzzles zurück."""
    session = _endless_sessions.pop(user_id, None)
    return session['count'] if session else 0


def is_endless(user_id: int) -> bool:
    _evict_stale_endless()
    return user_id in _endless_sessions


def get_endless_session(user_id: int) -> dict | None:
    """Gibt die Endless-Session zurück (oder None)."""
    return _endless_sessions.get(user_id)


# ---------------------------------------------------------------------------
# Puzzle-/Study-/Training-State
# ---------------------------------------------------------------------------

def load_puzzle_state() -> dict:
    return atomic_read(PUZZLE_STATE_FILE, default=lambda: {'posted': []})


def save_puzzle_state(state: dict):
    atomic_write(PUZZLE_STATE_FILE, state)


def _load_user_studies() -> dict:
    return atomic_read(USER_STUDIES_FILE)


def _save_user_studies(data: dict):
    atomic_write(USER_STUDIES_FILE, data)


def _get_user_study_id(user_id: int) -> str | None:
    entry = _load_user_studies().get(str(user_id))
    if isinstance(entry, dict):
        val = entry.get('id')
    else:
        val = None
    log.debug('User-Studie laden: user=%s → %s', user_id, val or 'neu')
    return val


def _get_user_puzzle_count(user_id: int) -> tuple[int, int]:
    """Gibt (heute, gesamt) zurück."""
    entry = _load_user_studies().get(str(user_id))
    if not isinstance(entry, dict):
        return 0, 0
    total = entry.get('total', 0)
    if entry.get('today') == _date.today().isoformat():
        return entry.get('count', 0), total
    return 0, total


def _set_user_study_id(user_id: int, study_id: str, count: int, total: int):
    key = str(user_id)
    def _update(data):
        prev = data.get(key) if isinstance(data.get(key), dict) else {}
        data[key] = {
            'id':    study_id,
            'today': _date.today().isoformat(),
            'count': count,
            'total': total,
        }
        if 'training' in prev:
            data[key]['training'] = prev['training']
        return data
    atomic_update(USER_STUDIES_FILE, _update)
    log.debug('User-Studie gespeichert: user=%s study_id=%s count=%d total=%d', user_id, study_id, count, total)


_books_config_cache: dict | None = None


def _load_books_config() -> dict:
    """Lädt books.json mit Metadaten (z.B. difficulty) pro PGN-Datei."""
    global _books_config_cache
    if _books_config_cache is not None:
        return _books_config_cache
    p = os.path.join(BOOKS_DIR, 'books.json')
    try:
        with open(p, encoding='utf-8') as f:
            _books_config_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _books_config_cache = {}
    return _books_config_cache


def _invalidate_books_config_cache():
    global _books_config_cache
    _books_config_cache = None


def _get_user_training(user_id: int) -> dict | None:
    """Gibt {'book': ..., 'position': ...} oder None zurück."""
    entry = _load_user_studies().get(str(user_id))
    if isinstance(entry, dict):
        return entry.get('training')
    return None


def _set_user_training(user_id: int, book: str, position: int):
    """Setzt das Trainingsbuch und die Position für den User."""
    key = str(user_id)
    def _update(data):
        if key not in data or not isinstance(data[key], dict):
            data[key] = {}
        data[key]['training'] = {'book': book, 'position': position}
        return data
    atomic_update(USER_STUDIES_FILE, _update)


def _clear_user_training(user_id: int):
    """Entfernt die Trainingsbuch-Zuordnung."""
    key = str(user_id)
    def _update(data):
        if key in data and isinstance(data[key], dict):
            data[key].pop('training', None)
        return data
    atomic_update(USER_STUDIES_FILE, _update)


# ---------------------------------------------------------------------------
# Puzzle-Kontext fuer KI-Chat
# ---------------------------------------------------------------------------
_last_puzzle_context: dict[int, dict] = {}   # user_id → puzzle info
_last_channel_puzzle: dict | None = None      # letztes Channel-Puzzle (global)


def save_puzzle_context(user_id: int | None, info: dict):
    """Speichert Puzzle-Kontext. user_id=None fuer Channel-Posts."""
    global _last_channel_puzzle
    _last_channel_puzzle = info
    if user_id is not None:
        _last_puzzle_context[user_id] = info


def get_puzzle_context(user_id: int) -> dict | None:
    """Gibt Puzzle-Kontext zurueck: zuerst per-User, dann Channel-Fallback."""
    return _last_puzzle_context.get(user_id) or _last_channel_puzzle
