"""Atomare JSON-Persistenz: Thread-safe Read/Write/Update.

Jede Datei bekommt einen eigenen Lock, damit gleichzeitige
Load-Modify-Save-Zyklen keine Daten verlieren. Writes gehen
über eine temporäre Datei + os.replace (atomar auf allen OS).
"""

import json
import os
import tempfile
import threading
from typing import Callable

_locks: dict[str, threading.Lock] = {}
_meta_lock = threading.Lock()


def _lock_for(path: str) -> threading.Lock:
    """Gibt den Lock für eine bestimmte Datei zurück (lazy erzeugt)."""
    with _meta_lock:
        if path not in _locks:
            _locks[path] = threading.Lock()
        return _locks[path]


def atomic_read(path: str, default=None):
    """Liest JSON-Datei thread-safe. Gibt *default* bei Fehler zurück."""
    lock = _lock_for(path)
    with lock:
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return default() if callable(default) else (default if default is not None else {})


def atomic_write(path: str, data):
    """Schreibt JSON-Datei atomar (tempfile → os.replace)."""
    lock = _lock_for(path)
    with lock:
        _write_unlocked(path, data)


def _write_unlocked(path: str, data):
    """Interner Write ohne Lock (wird auch von atomic_update genutzt)."""
    dir_name = os.path.dirname(path) or '.'
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_update(path: str, fn: Callable, default=None):
    """Read-Modify-Write in einem Lock: fn(data) → neues data, wird geschrieben.

    fn bekommt den geladenen Inhalt und muss den neuen Inhalt zurückgeben.
    """
    lock = _lock_for(path)
    with lock:
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            data = default() if callable(default) else (default if default is not None else {})
        data = fn(data)
        _write_unlocked(path, data)
        return data
