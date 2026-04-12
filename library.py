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
LIBRARY_FILE  = 'library.json'

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

def build_library_catalog() -> tuple[int, int, int, int]:
    """index.txt → library.json. Returns (dateien, bücher, neu, aktualisiert)."""
    if not LIBRARY_INDEX or not os.path.exists(LIBRARY_INDEX):
        return (0, 0, 0, 0)

    old_catalog = _load_library()
    old_by_id = {e['id']: e for e in old_catalog}

    with open(LIBRARY_INDEX, encoding='utf-8', errors='replace') as f:
        raw_lines = [l.strip() for l in f if l.strip()]

    groups: dict[str, list[tuple]] = defaultdict(list)
    for raw in raw_lines:
        parsed = _parse_index_entry(raw)
        if parsed is None:
            continue
        author, title, year, ext, path = parsed
        stem = _extract_title_stem(title)
        key = _normalize_for_dedup(author) + '::' + _normalize_for_dedup(stem)
        groups[key].append((author, title, year, ext, path, stem))

    new_catalog: list[dict] = []
    new_count = 0
    updated_count = 0

    for key, entries in groups.items():
        entries.sort(key=lambda e: _FILE_PRIO.get(e[3], 99))
        best = entries[0]
        author, title, year, ext, path, stem = best

        years = [e[2] for e in entries if e[2]]
        chosen_year = max(set(years), key=years.count) if years else None

        entry_id = _normalize_for_dedup(author) + '--' + _normalize_for_dedup(stem)
        auto_tags = _auto_tag(stem, author, ext)

        old_entry = old_by_id.get(entry_id)
        manual_tags = old_entry.get('manual_tags', []) if old_entry else []
        all_tags = sorted(set(auto_tags + manual_tags))

        entry = {
            'id':          entry_id,
            'title':       stem if stem else title,
            'author':      author,
            'year':        chosen_year,
            'tags':        all_tags,
            'manual_tags': manual_tags,
            'file_type':   ext,
            'files':       [e[4] for e in entries],
        }

        if old_entry is None:
            new_count += 1
        else:
            updated_count += 1

        new_catalog.append(entry)

    new_catalog.sort(key=lambda e: (e['author'], e['title']))
    _save_library(new_catalog)
    return (len(raw_lines), len(new_catalog), new_count, updated_count)


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

class LibraryPaginationView(discord.ui.View):
    def __init__(self, pages: list[list[dict]], query: str):
        super().__init__(timeout=120)
        self.pages = pages
        self.query = query
        self.current = 0

    @discord.ui.button(label='◀ Zurück', style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        self.current = max(0, self.current - 1)
        embed = _build_library_embed(
            self.pages[self.current], page=self.current + 1,
            total_pages=len(self.pages), query=self.query)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='Weiter ▶', style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        self.current = min(len(self.pages) - 1, self.current + 1)
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
        if len(pages) > 1:
            view = LibraryPaginationView(pages, query=suche)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

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
        if len(pages) > 1:
            view = LibraryPaginationView(pages, query=f'Tag: {tag}')
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

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
            f'✅ Katalog aktualisiert:\n'
            f'Dateien: **{stats[0]}** · Bücher: **{stats[1]}** · '
            f'Neu: **{stats[2]}** · Aktualisiert: **{stats[3]}**',
            ephemeral=True)
