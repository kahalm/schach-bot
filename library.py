"""Bibliothek-Katalog: index.txt parsen, Tags generieren, Suche, Slash-Commands."""

import asyncio
import json
import logging
import os
import re
from collections import defaultdict

import discord

log = logging.getLogger('schach-bot')

# --- Config (aus Umgebung) ---

LIBRARY_INDEX = os.getenv('LIBRARY_INDEX', '')
LIBRARY_FILE  = (os.path.join(os.path.dirname(LIBRARY_INDEX), 'library.json')
                 if LIBRARY_INDEX else 'library.json')
# Lokaler Basis-Pfad (Verzeichnis der index.txt) für Pfad-Übersetzung
_LOCAL_BASE   = os.path.dirname(LIBRARY_INDEX) if LIBRARY_INDEX else ''

# SFTPGo-Config für Dateien über dem Discord-Upload-Limit
_SFTPGO_BASE_URL       = os.getenv('SFTPGO_BASE_URL', '').rstrip('/')
_SFTPGO_SHARE_ID       = os.getenv('SFTPGO_SHARE_ID', '')
_SFTPGO_SHARE_PASSWORD = os.getenv('SFTPGO_SHARE_PASSWORD', '')

_REMOTE_PREFIX_RE = re.compile(r'.*/schach/')

def _local_path(remote: str) -> str:
    """Übersetzt einen remote-Pfad aus index.txt in den lokalen Syncthing-Pfad."""
    suffix = _REMOTE_PREFIX_RE.sub('', remote)
    return os.path.join(_LOCAL_BASE, suffix) if _LOCAL_BASE else remote

# ---------------------------------------------------------------------------
# Tag-Wörterbücher
# ---------------------------------------------------------------------------

_OPENING_TAGS: dict[str, list[str]] = {
    'Sicilian':       [r'\bsicilian\b', r'\bsizilian\b'],
    'French':         [r'\bfrench\b', r'\bfranz[oö]sisch\b'],
    "King's Indian":  [r"\bking'?s?\s+indian\b", r'\bk[oö]nigsindisch\b'],
    'Caro-Kann':      [r'\bcaro[\s-]?kann\b'],
    'Ruy Lopez':      [r'\bruy\s+lopez\b', r'\bspanish\b', r'\bspanisch\b'],
    "Queen's Gambit": [r"\bqueen'?s?\s+gambit\b", r'\bdamengambit\b'],
    'Nimzo-Indian':   [r'\bnimzo[\s-]?indian\b'],
    'Dutch':          [r'\bdutch\b', r'\bholl[aä]ndisch\b'],
    'Pirc':           [r'\bpirc\b'],
    'Scandinavian':   [r'\bscandinavian\b', r'\bskandinavisch\b'],
    'Slav':           [r'\bslav\b', r'\bslaw\b'],
    'Grünfeld':       [r'\bgr[uü]nfeld\b'],
    'Benoni':         [r'\bbenoni\b'],
    'English':        [r'\benglish\s+opening\b', r'\benglisch\b'],
    'Italian':        [r'\bitalian\b', r'\bitalienisch\b'],
    'Catalan':        [r'\bcatalan\b', r'\bkatalanisch\b'],
    'Philidor':       [r'\bphilidor\b'],
    'Alekhine':       [r"\balekhine'?s?\s+defen[cs]e\b", r'\balechin\b'],
    'Petrov':         [r'\bpetrov\b', r'\bpetroff\b', r'\brussian\s+game\b'],
    'Grob':           [r'\bgrob\b'],
    'Kings Gambit':   [r"\bking'?s?\s+gambit\b", r'\bk[oö]nigsgambit\b'],
}

_TOPIC_TAGS: dict[str, list[str]] = {
    'Tactics':    [r'\btactic', r'\btaktik', r'\bcombination'],
    'Endgame':    [r'\bendgame\b', r'\bendspiel\b', r'\bending\b'],
    'Strategy':   [r'\bstrateg', r'\bpositional\b'],
    'Middlegame': [r'\bmiddlegame\b', r'\bmittelspiel\b'],
    'Opening':    [r'\bopening\b', r'\ber[oö]ffnung\b'],
    'Checkmate':  [r'\bcheckmate\b', r'\bmatt\b', r'\bmate\b'],
    'Problems':   [r'\bpuzzle\b', r'\bproblem\b', r'\br[aä]tsel\b'],
    'Attack':     [r'\battack\b', r'\bangriff\b'],
    'Defense':    [r'\bdefen[cs]e\b', r'\bverteidigung\b', r'\bdefensive\b'],
}

_FORMAT_TAGS: dict[str, list[str]] = {
    'eBook': ['pdf', 'epub', 'djvu', 'azw', 'azw3', 'mobi'],
    'PGN':   ['pgn'],
    'Video': ['mp4', 'avi', 'mkv', 'wmv'],
    'Audio': ['mp3', 'm4b', 'm4a', 'wma', 'flac'],
}

_LANGUAGE_TAGS: dict[str, list[str]] = {
    'Deutsch':  [r'\(german\)', r'\bdeutsch\b'],
    'Russian':  [r'\(russian\)', r'\brussisch\b'],
    'French':   [r'\(french\)', r'\bfrançais\b'],
    'Spanish':  [r'\(spanish\)', r'\bespañol\b'],
}

def _auto_tag(title: str, author: str, file_ext: str) -> list[str]:
    """Generiert Tags aus Titel und Dateityp."""
    tags: list[str] = []
    text = f'{title} {author}'.lower()
    for tag, patterns in _OPENING_TAGS.items():
        if any(re.search(p, text) for p in patterns):
            tags.append(tag)
    for tag, patterns in _TOPIC_TAGS.items():
        if any(re.search(p, text) for p in patterns):
            tags.append(tag)
    for tag, exts in _FORMAT_TAGS.items():
        if file_ext in exts:
            tags.append(tag)
            break
    for tag, patterns in _LANGUAGE_TAGS.items():
        if any(re.search(p, text) for p in patterns):
            tags.append(tag)
    return tags


# ---------------------------------------------------------------------------
# Filename Parser
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Katalog-Builder
# ---------------------------------------------------------------------------

def _load_library() -> list[dict]:
    try:
        with open(LIBRARY_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _save_library(catalog: list[dict]):
    with open(LIBRARY_FILE, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

_FILE_PRIO = {'pdf': 0, 'epub': 1, 'djvu': 2, 'pgn': 3}


def _load_sidecar(remote_path: str) -> dict | None:
    """Prüft ob neben der Datei ein gleichnamiges .json liegt und liest es."""
    local = _local_path(remote_path)
    json_path = os.path.splitext(local)[0] + '.json'
    if not os.path.isfile(json_path):
        return None
    try:
        with open(json_path, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def build_library_catalog() -> tuple[int, int, int, int]:
    """index.txt mit library.json abgleichen: neue ergänzen, fehlende entfernen.
    Returns (dateien, bücher_gesamt, neu, entfernt)."""
    if not LIBRARY_INDEX or not os.path.exists(LIBRARY_INDEX):
        return (0, 0, 0, 0)

    old_catalog = _load_library()
    old_by_id = {e['id']: e for e in old_catalog}

    with open(LIBRARY_INDEX, encoding='utf-8', errors='replace') as f:
        raw_lines = [l.strip() for l in f if l.strip()]

    # index.txt parsen und gruppieren
    groups: dict[str, list[tuple]] = defaultdict(list)
    for raw in raw_lines:
        parsed = _parse_index_entry(raw)
        if parsed is None:
            continue
        author, title, year, ext, path = parsed
        stem = _extract_title_stem(title)
        key = _normalize_for_dedup(author) + '::' + _normalize_for_dedup(stem)
        groups[key].append((author, title, year, ext, path, stem))

    # IDs aus index.txt ermitteln
    index_ids: dict[str, tuple] = {}
    for key, entries in groups.items():
        entries.sort(key=lambda e: _FILE_PRIO.get(e[3], 99))
        best = entries[0]
        author, title, year, ext, path, stem = best
        entry_id = _normalize_for_dedup(author) + '--' + _normalize_for_dedup(stem)
        index_ids[entry_id] = (key, entries)

    # Neue Einträge ergänzen
    new_count = 0
    for entry_id, (key, entries) in index_ids.items():
        if entry_id in old_by_id:
            continue  # existiert bereits → nicht anfassen
        best = entries[0]
        author, title, year, ext, path, stem = best

        # Sidecar-JSON prüfen (beim besten File der Gruppe)
        sidecar = _load_sidecar(path)

        if sidecar:
            sc_author = ', '.join(sidecar['author']) if isinstance(sidecar.get('author'), list) else sidecar.get('author', author)
            sc_title  = sidecar.get('title', stem or title)
            sc_year   = sidecar.get('year')
            sc_tags   = sidecar.get('tags', [])
            sc_format = sidecar.get('format', ext)
            sc_elo    = sidecar.get('targetMinElo')
            sc_fav    = sidecar.get('favorite', [])
            sc_size   = sidecar.get('size')
            auto_tags = sorted(set(sc_tags + _auto_tag(sc_title, sc_author, ext)))
            old_catalog.append({
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
                'files':        [e[4] for e in entries],
            })
        else:
            years = [e[2] for e in entries if e[2]]
            chosen_year = max(set(years), key=years.count) if years else None
            auto_tags = _auto_tag(stem, author, ext)
            old_catalog.append({
                'id':          entry_id,
                'title':       stem if stem else title,
                'author':      author,
                'year':        chosen_year,
                'tags':        auto_tags,
                'manual_tags': [],
                'file_type':   ext,
                'files':       [e[4] for e in entries],
            })
        new_count += 1

    # Fehlende entfernen (nicht mehr in index.txt)
    before_remove = len(old_catalog)
    old_catalog = [e for e in old_catalog if e['id'] in index_ids]
    removed_count = before_remove - len(old_catalog)

    old_catalog.sort(key=lambda e: (e['author'], e['title']))
    _save_library(old_catalog)
    return (len(raw_lines), len(old_catalog), new_count, removed_count)


# ---------------------------------------------------------------------------
# Such-Index (in-memory)
# ---------------------------------------------------------------------------

_library_cache: list[dict] = []
_library_loaded: bool = False

def _ensure_library() -> list[dict]:
    global _library_cache, _library_loaded
    if not _library_loaded:
        _library_cache = _load_library()
        _library_loaded = True
    return _library_cache

def _reload_library():
    global _library_loaded
    _library_loaded = False

def _search_library(query: str, limit: int = 25) -> list[dict]:
    catalog = _ensure_library()
    words = query.lower().split()
    if not words:
        return []
    scored: list[tuple[int, dict]] = []
    for entry in catalog:
        searchable = f"{entry['title']} {entry['author']} {' '.join(entry.get('tags', []))}".lower()
        score = sum(1 for w in words if w in searchable)
        if query.lower() in entry['title'].lower():
            score += 5
        if query.lower() in entry['author'].lower():
            score += 3
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda x: (-x[0], x[1]['author']))
    return [e for _, e in scored[:limit]]

def _all_tags() -> list[str]:
    catalog = _ensure_library()
    tags: set[str] = set()
    for entry in catalog:
        tags.update(entry.get('tags', []))
    return sorted(tags)


# ---------------------------------------------------------------------------
# Embed + Pagination
# ---------------------------------------------------------------------------

_TYPE_EMOJI = {
    'pdf': '📕', 'epub': '📗', 'djvu': '📘', 'pgn': '♟️',
    'mp4': '🎬', 'mp3': '🎧', 'm4b': '🎧',
    'azw': '📱', 'azw3': '📱', 'mobi': '📱',
}

def _build_library_embed(entries: list[dict], page: int, total_pages: int,
                          query: str) -> discord.Embed:
    embed = discord.Embed(title=f'📚 Bibliothek: {query}', color=0x4e9e4e)
    for e in entries:
        emoji = _TYPE_EMOJI.get(e.get('file_type', ''), '📄')
        year_str = f' ({e["year"]})' if e.get('year') else ''
        tags_str = ', '.join(e.get('tags', []))
        name = f'{emoji} {e["title"]}{year_str}'
        if len(name) > 256:
            name = name[:253] + '...'
        value = f'**{e["author"]}**'
        if tags_str:
            value += f'\n`{tags_str}`'
        if len(e.get('files', [])) > 1:
            value += f'\n_{len(e["files"])} Dateien_'
        embed.add_field(name=name, value=value, inline=False)
    if total_pages > 1:
        embed.set_footer(text=f'Seite {page}/{total_pages}')
    return embed

_MAX_UPLOAD = 8 * 1024 * 1024  # Discord-Limit 8 MB (ohne Nitro)

_FORMAT_EMOJI = {'pdf': '📕', 'djvu': '📘', 'epub': '📗'}
_FORMAT_LABEL = {'pdf': 'PDF', 'djvu': 'DJVU', 'epub': 'EPUB'}


def _collect_formats(entry: dict) -> dict[str, str]:
    """Gibt {ext: lokaler_pfad} für alle auf der Disk vorhandenen Formatvarianten zurück.

    Prüft entry['files'] sowie Geschwisterdateien mit gleichem Stem
    (die von convert_formats.sh erzeugt wurden).
    """
    found: dict[str, str] = {}
    stems: set[str] = set()

    for f in entry.get('files', []):
        local = _local_path(f)
        if not os.path.isfile(local):
            continue
        raw = os.path.splitext(local)[1].lower().lstrip('.')
        canon = 'djvu' if raw == 'djv' else raw
        if canon in ('pdf', 'djvu', 'epub') and canon not in found:
            found[canon] = local
        stems.add(os.path.splitext(local)[0])

    # Geschwisterdateien prüfen (z. B. durch Konvertierung erzeugt)
    for stem in stems:
        for ext in ('pdf', 'djvu', 'epub'):
            if ext not in found and os.path.isfile(f'{stem}.{ext}'):
                found[ext] = f'{stem}.{ext}'

    return found


def _sftpgo_configured() -> bool:
    return bool(_SFTPGO_BASE_URL and _SFTPGO_SHARE_ID)


def _sftpgo_rel_path(local_path: str) -> str | None:
    """Gibt den relativen Pfad der Datei innerhalb der Library zurück."""
    if not _LOCAL_BASE:
        return None
    norm = local_path.replace('\\', '/')
    base = _LOCAL_BASE.replace('\\', '/')
    if not norm.startswith(base):
        return None
    return norm[len(base):].lstrip('/')


def _sftpgo_message(entry: dict, path: str, fmt: str) -> str:
    """Baut die ephemere Antwort-Nachricht mit Web-Client-Link, Pfad und Passwort."""
    # Web-Client-URL: zeigt SFTPGo-eigenes Passwortformular statt Browser-Basic-Auth-Dialog
    browse_url = f'{_SFTPGO_BASE_URL}/web/client/shares/{_SFTPGO_SHARE_ID}/browse'
    rel        = _sftpgo_rel_path(path) or os.path.basename(path)
    size       = os.path.getsize(path)
    mb         = size / (1024 * 1024)
    return (
        f'📥 **{entry["title"]}** `[{fmt.upper()} · {mb:.1f} MB]`\n\n'
        f'🔗 {browse_url}\n'
        f'📂 `{rel}`\n\n'
        f'🔑 Passwort: `{_SFTPGO_SHARE_PASSWORD}`'
    )


async def _send_book(interaction: discord.Interaction,
                     entry: dict, path: str, fmt: str) -> None:
    """Schickt eine Buchdatei per DM (oder SFTPGo-Link wenn zu groß).
    Setzt voraus dass interaction bereits deferred ist (ephemeral)."""
    size = os.path.getsize(path)
    if size > _MAX_UPLOAD:
        if _sftpgo_configured():
            await interaction.followup.send(
                _sftpgo_message(entry, path, fmt), ephemeral=True)
        else:
            mb = size / (1024 * 1024)
            await interaction.followup.send(
                f'⚠️ Datei zu groß ({mb:.1f} MB, Discord-Limit 8 MB).', ephemeral=True)
        return
    dm = await interaction.user.create_dm()
    await dm.send(
        content=f'📖 **{entry["title"]}** — {entry["author"]} `[{fmt.upper()}]`',
        file=discord.File(path, filename=os.path.basename(path)))
    await interaction.followup.send(
        f'✅ **{entry["title"]}** `[{fmt.upper()}]` per DM gesendet.', ephemeral=True)


class _FormatView(discord.ui.View):
    """Ein Button pro verfügbarem Format; User wählt welches er herunterladen will."""

    def __init__(self, entry: dict, formats: dict[str, str]):
        super().__init__(timeout=60)
        self.entry = entry
        for fmt, path in formats.items():
            size  = os.path.getsize(path)
            mb    = size / (1024 * 1024)
            big   = size > _MAX_UPLOAD
            link  = big and bool(_sftpgo_configured())
            label = f'{_FORMAT_LABEL.get(fmt, fmt.upper())}  {mb:.1f} MB'
            if link:
                style = discord.ButtonStyle.success   # grün  → SFTPGo-Link
                label = f'{label}  🔗'
            elif big:
                style = discord.ButtonStyle.secondary  # grau   → kein Fallback
                label = f'{label}  ⚠️'
            else:
                style = discord.ButtonStyle.primary    # blau   → DM-Download
            btn = discord.ui.Button(
                label=label, emoji=_FORMAT_EMOJI.get(fmt, '📄'),
                style=style, custom_id=f'fmt_{fmt}')
            btn.callback = self._make_callback(fmt, path, big, link)
            self.add_item(btn)

    def _make_callback(self, fmt: str, path: str, big: bool, link: bool):
        async def _cb(interaction: discord.Interaction):
            if big and link:
                # Direkt antworten (kein defer nötig)
                await interaction.response.send_message(
                    _sftpgo_message(self.entry, path, fmt), ephemeral=True)
            elif big:
                size = os.path.getsize(path)
                mb = size / (1024 * 1024)
                await interaction.response.send_message(
                    f'⚠️ Datei zu groß ({mb:.1f} MB, Discord-Limit 8 MB).',
                    ephemeral=True)
            else:
                await interaction.response.defer(ephemeral=True)
                await _send_book(interaction, self.entry, path, fmt)
        return _cb


class _BookSelect(discord.ui.Select):
    """Dropdown zum Auswählen eines Buchs zum Download."""

    def __init__(self, entries: list[dict]):
        options = []
        for i, e in enumerate(entries):
            emoji = _TYPE_EMOJI.get(e.get('file_type', ''), '📄')
            label = f'{e["title"]}'[:100]
            desc = f'{e["author"]}'[:100]
            options.append(discord.SelectOption(
                label=label, description=desc, emoji=emoji, value=str(i)))
        super().__init__(placeholder='📥 Buch auswählen …', options=options)
        self.entries = entries

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        entry = self.entries[idx]

        if not entry.get('files'):
            await interaction.response.send_message(
                '⚠️ Keine Datei hinterlegt.', ephemeral=True)
            return

        formats = _collect_formats(entry)

        if not formats:
            await interaction.response.send_message(
                '⚠️ Datei nicht lokal gefunden (Sync noch nicht fertig?).',
                ephemeral=True)
            return

        if len(formats) == 1:
            # Nur ein Format vorhanden → direkt herunterladen
            fmt, path = next(iter(formats.items()))
            await interaction.response.defer(ephemeral=True)
            await _send_book(interaction, entry, path, fmt)
        else:
            # Mehrere Formate → User wählen lassen
            fmts = '  '.join(
                f'{_FORMAT_EMOJI.get(f, "📄")} **{_FORMAT_LABEL.get(f, f.upper())}**'
                for f in formats)
            await interaction.response.send_message(
                f'**{entry["title"]}**\nVerfügbare Formate: {fmts}',
                view=_FormatView(entry, formats),
                ephemeral=True)


class LibraryPaginationView(discord.ui.View):
    def __init__(self, pages: list[list[dict]], query: str):
        super().__init__(timeout=120)
        self.pages = pages
        self.query = query
        self.current = 0
        self._update_select()

    def _update_select(self):
        # Altes Select entfernen falls vorhanden
        for child in self.children:
            if isinstance(child, _BookSelect):
                self.remove_item(child)
                break
        self.add_item(_BookSelect(self.pages[self.current]))

    @discord.ui.button(label='◀ Zurück', style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        self.current = max(0, self.current - 1)
        self._update_select()
        embed = _build_library_embed(
            self.pages[self.current], page=self.current + 1,
            total_pages=len(self.pages), query=self.query)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='Weiter ▶', style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        self.current = min(len(self.pages) - 1, self.current + 1)
        self._update_select()
        embed = _build_library_embed(
            self.pages[self.current], page=self.current + 1,
            total_pages=len(self.pages), query=self.query)
        await interaction.response.edit_message(embed=embed, view=self)


# ---------------------------------------------------------------------------
# Slash-Commands registrieren
# ---------------------------------------------------------------------------

def setup(bot: discord.ext.commands.Bot):
    """Registriert alle Bibliothek-Commands auf dem Bot."""
    tree = bot.tree

    @tree.command(name='bibliothek', description='Schachbuch-Bibliothek durchsuchen')
    @discord.app_commands.describe(suche='Suchbegriff (Titel, Autor oder Tag)')
    async def cmd_bibliothek(interaction: discord.Interaction, suche: str):
        await interaction.response.defer(ephemeral=True)
        results = _search_library(suche, limit=50)
        if not results:
            await interaction.followup.send(
                f'Keine Treffer für „{suche}".', ephemeral=True)
            return
        pages = [results[i:i + 10] for i in range(0, len(results), 10)]
        embed = _build_library_embed(pages[0], page=1, total_pages=len(pages), query=suche)
        view = LibraryPaginationView(pages, query=suche)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @cmd_bibliothek.autocomplete('suche')
    async def bibliothek_autocomplete(
        interaction: discord.Interaction, current: str,
    ) -> list[discord.app_commands.Choice[str]]:
        if len(current) < 2:
            return []
        results = _search_library(current, limit=25)
        return [
            discord.app_commands.Choice(
                name=f'{e["author"]}: {e["title"]}'[:100],
                value=e['title'][:100],
            )
            for e in results
        ]

    @tree.command(name='tag', description='Bücher nach Tag filtern')
    @discord.app_commands.describe(tag='Tag zum Filtern')
    async def cmd_tag(interaction: discord.Interaction, tag: str):
        await interaction.response.defer(ephemeral=True)
        catalog = _ensure_library()
        results = [e for e in catalog
                   if tag.lower() in [t.lower() for t in e.get('tags', [])]]
        if not results:
            await interaction.followup.send(
                f'Keine Bücher mit Tag „{tag}".', ephemeral=True)
            return
        results.sort(key=lambda e: (e['author'], e['title']))
        pages = [results[i:i + 10] for i in range(0, len(results), 10)]
        embed = _build_library_embed(pages[0], page=1, total_pages=len(pages),
                                      query=f'Tag: {tag}')
        view = LibraryPaginationView(pages, query=f'Tag: {tag}')
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @cmd_tag.autocomplete('tag')
    async def tag_autocomplete(
        interaction: discord.Interaction, current: str,
    ) -> list[discord.app_commands.Choice[str]]:
        tags = _all_tags()
        if current:
            tags = [t for t in tags if current.lower() in t.lower()]
        return [
            discord.app_commands.Choice(name=t, value=t)
            for t in tags[:25]
        ]

    @tree.command(name='reindex', description='Bibliotheks-Katalog neu aufbauen (Admin)')
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_reindex(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not LIBRARY_INDEX:
            await interaction.followup.send(
                '⚠️ `LIBRARY_INDEX` nicht in `.env` konfiguriert.', ephemeral=True)
            return
        loop = asyncio.get_running_loop()
        stats = await loop.run_in_executor(None, build_library_catalog)
        _reload_library()
        await interaction.followup.send(
            f'✅ Katalog abgeglichen:\n'
            f'Dateien: **{stats[0]}** · Bücher: **{stats[1]}** · '
            f'Neu: **{stats[2]}** · Entfernt: **{stats[3]}**',
            ephemeral=True)
