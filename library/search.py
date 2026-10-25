"""Bibliothek: Such-Index im Speicher (Katalog-Cache, Suche, Tag-/Autorenlisten).

Der Cache wird aus Worker-Threads gelesen und per /reindex invalidiert (Lock).
"""

import os
import re
import threading

from library import catalog as _catalog

_library_cache: list[dict] = []
# Voller Katalog inkl. per ignore.json ausgeblendeter Einträge: die liegen trotzdem
# im SFTPGo-Share und zählen für sharing._share_exposes_locked mit.
_library_all: list[dict] = []
_library_loaded: bool = False
# Der Cache wird aus mehreren Worker-Threads (asyncio.to_thread) gelesen UND per /reindex
# invalidiert — ohne Lock kann ein konkurrierender Aufbau einen teilgefüllten Cache liefern.
_library_lock = threading.Lock()

def _ensure_library() -> list[dict]:
    global _library_cache, _library_all, _library_loaded
    if _library_loaded:
        return _library_cache
    with _library_lock:
        # Double-checked: ein anderer Thread kann den Cache gefüllt haben, während wir warteten.
        if not _library_loaded:
            full = _catalog._load_library()
            _library_all = full
            _library_cache = [e for e in full if not _catalog._is_excluded(e)]
            _library_loaded = True
    return _library_cache

def _reload_library():
    global _library_loaded
    with _library_lock:
        _library_loaded = False
    _catalog._ignore_cache.clear()


def _search_library(query: str, limit: int = 25) -> list[dict]:
    catalog = _ensure_library()
    words = re.sub(r'[^\w\s]', '', query.lower()).split()
    if not words:
        return []
    scored: list[tuple[int, dict]] = []
    for entry in catalog:
        author = _catalog._author_str(entry.get('author', ''))
        filenames = ' '.join(os.path.splitext(os.path.basename(f))[0] for f in entry.get('files', []))
        searchable = f"{entry['title']} {author} {' '.join(entry.get('tags', []))} {filenames}".lower()
        matched = sum(1 for w in words if w in searchable)
        if matched < len(words):
            continue  # ALL Suchbegriffe müssen vorkommen
        score = matched
        if query.lower() in entry['title'].lower():
            score += 5
        if query.lower() in author.lower():
            score += 3
        scored.append((score, entry))
    scored.sort(key=lambda x: (-x[0], _catalog._author_str(x[1].get('author', ''))))
    return [e for _, e in scored[:limit]]

def _all_tags() -> list[str]:
    catalog = _ensure_library()
    tags: set[str] = set()
    for entry in catalog:
        tags.update(entry.get('tags', []))
    return sorted(tags)


def _all_authors() -> list[str]:
    catalog = _ensure_library()
    authors: set[str] = set()
    for entry in catalog:
        a = entry.get('author', '')
        if isinstance(a, list):
            authors.update(a)
        elif a:
            authors.add(a)
    return sorted(authors)
