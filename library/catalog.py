"""Bibliothek: Katalogbau – index.txt parsen, gruppieren, Sidecar-JSON, library.json schreiben.

- ``ignore.json`` je Ordner (rekursiv, fnmatch) blendet Einträge aus (``_is_excluded``)
- ``_parse_index_entry``: eine index.txt-Zeile → (Autor, Titel, Jahr, Endung, Pfad)
- ``build_library_catalog``: index.txt mit library.json abgleichen (/reindex)
"""

import fnmatch
import json
import logging
import os
import re
from collections import defaultdict

from core.json_store import atomic_write
from library import config
from library import tags as _tags

log = logging.getLogger('schach-bot')

# Per-Ordner-Filter via ``ignore.json``: ein JSON-Array fnmatch-tauglicher
# Patterns (``*.pgn``, ``A01.pgn``, …). Eine ignore.json gilt rekursiv für
# alle Dateien in diesem Ordner und allen Unterordnern. library.json bleibt
# unverändert – die ignore.json wandert mit dem Ordner mit, sodass dieselben
# Dateien an einem neuen Ort weiter gefiltert werden.


# Cache: folder-pfad → Liste von Patterns (oder [])
_ignore_cache: dict[str, list[str]] = {}


def _load_ignore_patterns(folder: str) -> list[str]:
    """Lädt ``ignore.json`` aus ``folder`` (cached). Gibt fnmatch-Patterns zurück."""
    if folder in _ignore_cache:
        return _ignore_cache[folder]
    patterns: list[str] = []
    path = os.path.join(folder, config._IGNORE_FILE)
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                patterns = [str(p) for p in data if p]
        except (json.JSONDecodeError, OSError) as e:
            log.warning('ignore.json kaputt (%s): %s', path, e)
    _ignore_cache[folder] = patterns
    return patterns


def _file_is_ignored(remote: str) -> bool:
    """Walkt vom File aufwärts und prüft jede ignore.json bis ``_LOCAL_BASE``."""
    if not config._LOCAL_BASE:
        return False
    local = config._local_path(remote)
    if not local:
        return False
    base  = os.path.normpath(config._LOCAL_BASE)
    folder = os.path.normpath(os.path.dirname(local))
    basename = os.path.basename(local)
    while folder.startswith(base):
        for pat in _load_ignore_patterns(folder):
            if fnmatch.fnmatch(basename, pat):
                return True
            rel = os.path.relpath(local, folder).replace('\\', '/')
            if fnmatch.fnmatch(rel, pat):
                return True
        if folder == base:
            break
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return False


def _is_excluded(entry: dict) -> bool:
    """Eintrag wird ausgeblendet, wenn ALLE seiner Files via ignore.json gefiltert sind."""
    files = entry.get('files', [])
    if not files:
        return False
    return all(_file_is_ignored(f) for f in files)


_MEDIA_PART_RE = re.compile(
    r'[\s_-]*(disc|disk|cd|part|teil|vol|volume|chapter|ch|track)[\s_-]*\d+.*',
    re.IGNORECASE,
)

_YEAR_BRACKET_RE = re.compile(r'\[([^]]*?,\s*(\d{4})(?:\s*-\s*[^]]*)?)\]')
_YEAR_PAREN_RE   = re.compile(r'\((\d{4})(?:,\s*[^)]+)?\)')
_YEAR_PLAIN_RE   = re.compile(r'\b(1[89]\d{2}|20[0-2]\d)\b')

def _normalize_for_dedup(text: str) -> str:
    t = text.lower()
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def _extract_title_stem(raw_title: str) -> str:
    """Disc/Chapter/Part-Suffixe entfernen für Dedup."""
    stem = _MEDIA_PART_RE.sub('', raw_title).strip()
    stem = re.sub(r'\s*-\s*$', '', stem).strip()
    return stem if stem else raw_title

def _parse_index_entry(line: str) -> tuple | None:
    """Parst eine Zeile aus index.txt → (author, title, year, ext, path) oder None."""
    line = line.strip()
    if not line:
        return None

    parts = line.split('/')
    try:
        schach_idx = parts.index('schach')
    except ValueError:
        return None

    remaining = parts[schach_idx + 1:]
    if len(remaining) < 2:
        return None

    author = remaining[0]
    filename = remaining[-1]

    _, ext_raw = os.path.splitext(filename)
    ext = ext_raw.lstrip('.').lower()
    if not ext:
        return None

    title_raw = os.path.splitext(filename)[0]
    year = None
    m = _YEAR_BRACKET_RE.search(title_raw)
    if m:
        year = int(m.group(2))
        title_raw = title_raw[:m.start()] + title_raw[m.end():]
    if not year:
        m = _YEAR_PAREN_RE.search(title_raw)
        if m:
            year = int(m.group(1))
            title_raw = title_raw[:m.start()] + title_raw[m.end():]

    author_parts = author.replace(',', '').split()
    for ap in author_parts:
        title_raw = re.sub(re.escape(ap), '', title_raw, count=1, flags=re.IGNORECASE)

    title_raw = title_raw.replace('_', ' ')
    title_raw = re.sub(r'\s*-\s*-\s*', ' - ', title_raw)
    title_raw = re.sub(r'^\s*[-–—:]+\s*', '', title_raw)
    title_raw = re.sub(r'\s*[-–—:]+\s*$', '', title_raw)
    title_raw = re.sub(r'\s+', ' ', title_raw).strip()

    if not title_raw:
        title_raw = filename

    if not year:
        m = _YEAR_PLAIN_RE.search(title_raw)
        if m:
            year = int(m.group(1))

    return (author, title_raw, year, ext, line)


def _load_library() -> list[dict]:
    try:
        with open(config.LIBRARY_FILE, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        log.warning('library.json korrupt: %s', e)
        return []

def _save_library(catalog: list[dict]):
    atomic_write(config.LIBRARY_FILE, catalog)

_FILE_PRIO = {'pdf': 0, 'epub': 1, 'djvu': 2, 'pgn': 3}


def _load_sidecar(remote_path: str) -> dict | None:
    """Prüft ob neben der Datei ein gleichnamiges .json liegt und liest es."""
    local = config._local_path(remote_path)
    if not local:
        return None
    json_path = os.path.splitext(local)[0] + '.json'
    if not os.path.isfile(json_path):
        return None
    try:
        with open(json_path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def build_library_catalog() -> tuple[int, int, int, int, int]:
    """index.txt mit library.json abgleichen: alle Einträge neu aufbauen.
    Returns (dateien, bücher_gesamt, neu, aktualisiert, entfernt)."""
    if not config.LIBRARY_INDEX or not os.path.exists(config.LIBRARY_INDEX):
        return (0, 0, 0, 0, 0)

    old_catalog = _load_library()
    old_by_id = {e['id']: e for e in old_catalog}

    with open(config.LIBRARY_INDEX, encoding='utf-8', errors='replace') as f:
        raw_lines = list(dict.fromkeys(l.strip() for l in f if l.strip()))

    # index.txt parsen und gruppieren (Autor + Titel-Stem)
    groups: dict[str, list[tuple]] = defaultdict(list)
    for raw in raw_lines:
        parsed = _parse_index_entry(raw)
        if parsed is None:
            continue
        author, title, year, ext, path = parsed
        stem = _extract_title_stem(title)
        key = _normalize_for_dedup(author) + '::' + _normalize_for_dedup(stem)
        groups[key].append((author, title, year, ext, path, stem))

    # Zweite Dedup-Runde: Gruppen mit gleichem Dateinamen aber unterschiedlichem
    # Autor-Verzeichnis zusammenführen (z.B. gleiche Datei in falschem Ordner)
    by_filename: dict[str, list[str]] = defaultdict(list)
    for key, entries in groups.items():
        for _, _, _, _, path, _ in entries:
            fname = os.path.basename(path).lower()
            if key not in by_filename[fname]:
                by_filename[fname].append(key)
    for fname, keys in by_filename.items():
        if len(keys) <= 1:
            continue
        # Alle in die erste Gruppe zusammenlegen
        target = keys[0]
        for other in keys[1:]:
            if other in groups:
                groups[target].extend(groups.pop(other))

    # IDs aus index.txt ermitteln — Eintrag mit Sidecar als "best" bevorzugen
    index_ids: dict[str, tuple] = {}
    for key, entries in groups.items():
        entries.sort(key=lambda e: _FILE_PRIO.get(e[3], 99))
        # Eintrag mit Sidecar nach vorne
        best_idx = 0
        for i, e in enumerate(entries):
            if _load_sidecar(e[4]):
                best_idx = i
                break
        if best_idx:
            entries.insert(0, entries.pop(best_idx))
        best = entries[0]
        author, title, year, ext, path, stem = best
        sidecar = _load_sidecar(path)
        if sidecar:
            raw_sc = sidecar.get('author', author)
            if isinstance(raw_sc, list):
                author = ', '.join(str(a) for a in raw_sc)
            else:
                author = str(raw_sc or author)
        entry_id = _normalize_for_dedup(author) + '--' + _normalize_for_dedup(stem)
        index_ids[entry_id] = (key, entries)

    # Einträge ergänzen / aktualisieren
    new_count = 0
    updated_count = 0
    for entry_id, (key, entries) in index_ids.items():
        best = entries[0]
        author, title, year, ext, path, stem = best
        is_new = entry_id not in old_by_id
        old_entry = old_by_id.get(entry_id)

        # Sidecar-JSON prüfen (beim besten File der Gruppe)
        sidecar = _load_sidecar(path)

        if sidecar:
            raw_author = sidecar.get('author', author)
            sc_author = ', '.join(str(a) for a in raw_author) if isinstance(raw_author, list) else str(raw_author or author)
            sc_title  = sidecar.get('title', stem or title)
            sc_year   = sidecar.get('year')
            sc_tags   = sidecar.get('tags', [])
            sc_format = sidecar.get('format', ext)
            sc_elo    = sidecar.get('targetMinElo')
            sc_fav    = sidecar.get('favorite', [])
            sc_size   = sidecar.get('size')
            auto_tags = sorted(set(sc_tags + _tags._auto_tag(sc_title, sc_author, ext)))
            new_entry = {
                'id':           entry_id,
                'title':        sc_title,
                'author':       sc_author,
                'year':         sc_year,
                'tags':         auto_tags,
                'manual_tags':  sc_tags,
                'file_type':    sc_format,
                'targetMinElo': sc_elo,
                'favorite':     sc_fav,
                'size':         sc_size,
                'publicDomainFrom': sidecar.get('publicDomainFrom'),
                'files':        [e[4] for e in entries],
            }
        else:
            years = [e[2] for e in entries if e[2]]
            chosen_year = max(set(years), key=lambda y: (years.count(y), y)) if years else None
            auto_tags = _tags._auto_tag(stem, author, ext)
            new_entry = {
                'id':          entry_id,
                'title':       stem if stem else title,
                'author':      author,
                'year':        chosen_year,
                'tags':        auto_tags,
                'manual_tags': [],
                'file_type':   ext,
                'publicDomainFrom': None,
                'files':       [e[4] for e in entries],
            }

        if is_new:
            old_catalog.append(new_entry)
            new_count += 1
        else:
            # Bestehenden Eintrag aktualisieren
            old_by_id[entry_id].update(new_entry)
            updated_count += 1

    # Fehlende entfernen (nicht mehr in index.txt)
    before_remove = len(old_catalog)
    old_catalog = [e for e in old_catalog if e['id'] in index_ids]
    removed_count = before_remove - len(old_catalog)

    old_catalog.sort(key=lambda e: (_author_str(e.get('author', '')), e['title']))
    _save_library(old_catalog)
    return (len(raw_lines), len(old_catalog), new_count, updated_count, removed_count)


def _author_str(author) -> str:
    """Gibt author als String zurück (egal ob str oder list)."""
    if isinstance(author, list):
        return ', '.join(author)
    return author or ''
