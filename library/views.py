"""Bibliothek: Discord-Darstellung – Seiten-Embed, Buch-Auswahl, Format-Buttons, Blättern.

Datei-I/O (stat/isfile auf dem Bibliotheks-Mount) läuft nur in Threads
(``_library_page``, ``_BookSelect.callback``, ``_send_book``).
"""

import asyncio
import logging
import os

import discord

from core import stats
from core.version import EMBED_COLOR
from library import catalog as _catalog
from library import config, sharing

log = logging.getLogger('schach-bot')

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
    embed = discord.Embed(title=f'📚 Bibliothek: {query}', color=EMBED_COLOR)
    for e in entries:
        emoji = _TYPE_EMOJI.get(e.get('file_type', ''), '📄')
        year_str = f' ({e["year"]})' if e.get('year') else ''
        tags_str = ', '.join(e.get('tags', []))
        locked = sharing._is_locked(e)
        lock_prefix = '🔒 ' if locked else ''
        name = f'{lock_prefix}{emoji} {e["title"]}{year_str}'
        if len(name) > 256:
            name = name[:253] + '...'
        value = f'**{_catalog._author_str(e.get("author", ""))}**'
        if e.get('targetMinElo'):
            value += f'  ·  Elo {e["targetMinElo"]}+'
        if tags_str:
            value += f'\n`{tags_str}`'
        if locked:
            value += f'\n{sharing._lock_note(e)} (noch nicht teilbar)'
        else:
            formats = sharing._collect_formats(e)
            if formats:
                fmt_str = '  '.join(
                    f'{_FORMAT_EMOJI.get(f, "📄")} {f.upper()}'
                    for f in sorted(formats))
                value += f'\n{fmt_str}'
        embed.add_field(name=name, value=value, inline=False)
    if total_pages > 1:
        embed.set_footer(text=f'Seite {page}/{total_pages}')
    return embed


_FORMAT_EMOJI = {'pdf': '📕', 'djvu': '📘', 'epub': '📗'}
_FORMAT_LABEL = {'pdf': 'PDF', 'djvu': 'DJVU', 'epub': 'EPUB'}


async def _send_book(interaction: discord.Interaction,
                     entry: dict, path: str, fmt: str) -> None:
    """Schickt eine Buchdatei per DM (oder SFTPGo-Link wenn zu groß).
    Setzt voraus dass interaction bereits deferred ist (ephemeral)."""
    # Gemeinfreiheits-Sperre: noch nicht freie Bücher werden nicht geteilt.
    if sharing._is_locked(entry):
        rel = sharing._pd_release(entry)
        await interaction.followup.send(
            f'🔒 **{entry["title"]}** ist noch urheberrechtlich geschützt und wird erst '
            f'am **{rel.strftime("%d.%m.%Y")}** gemeinfrei — bis dahin nicht teilbar.',
            ephemeral=True)
        return
    try:
        # Disk-/Netz-I/O (Bücher liegen auf Syncthing-/Netzpfaden) NICHT im Event-Loop:
        # ein hakendes Laufwerk würde sonst den ganzen Bot einfrieren.
        size = await asyncio.to_thread(os.path.getsize, path)
        if size > config._MAX_UPLOAD:
            # Link-Freigabe laedt bei aktiver Sperre ggf. den Katalog (Mount) → Thread
            if await asyncio.to_thread(sharing._sftpgo_link_allowed):
                msg = await asyncio.to_thread(sharing._sftpgo_message, entry, path, fmt, size)
                await interaction.followup.send(msg, ephemeral=True)
                pw_msg = sharing._sftpgo_password_message()
                if pw_msg:
                    await interaction.followup.send(pw_msg, ephemeral=True)
                await asyncio.to_thread(stats.inc, interaction.user.id, 'downloads')
            else:
                mb = size / (1024 * 1024)
                await interaction.followup.send(
                    f'⚠️ Datei zu groß ({mb:.1f} MB, Discord-Limit 8 MB).{sharing._share_block_note()}',
                    ephemeral=True)
            return
        dm = await interaction.user.create_dm()
        book_file = await asyncio.to_thread(
            lambda: discord.File(path, filename=os.path.basename(path)))
        await dm.send(
            content=f'📖 **{entry["title"]}** — {entry["author"]} `[{fmt.upper()}]`',
            file=book_file)
    except OSError:
        # Datei zwischen View-Bau und Klick verschwunden (Sync/Reindex/Verschiebung).
        log.warning('Buchdatei nicht mehr verfuegbar: %s', path)
        await interaction.followup.send(
            '⚠️ Datei nicht mehr verfügbar (evtl. zwischenzeitlich synchronisiert/verschoben).',
            ephemeral=True)
        return
    await asyncio.to_thread(stats.inc, interaction.user.id, 'downloads')
    await interaction.followup.send(
        f'✅ **{entry["title"]}** `[{fmt.upper()}]` per DM gesendet.', ephemeral=True)


class _FormatView(discord.ui.View):
    """Ein Button pro verfügbarem Format; User wählt welches er herunterladen will."""

    def __init__(self, entry: dict, formats: dict[str, str],
                 sizes: dict[str, int] | None = None, link_ok: bool | None = None):
        """``sizes`` (fmt → Bytes) und ``link_ok`` (_sftpgo_link_allowed, laedt bei
        aktiver Sperre ggf. den Katalog) idealerweise vorab in einem Thread ermitteln
        (siehe _BookSelect.callback) — der Konstruktor laeuft im Event-Loop und
        Buecher liegen auf Syncthing-/Netzpfaden. Fehlt eine Groesse, zaehlt sie als 0
        (kein getsize hier; der Klick-Pfad meldet eine verschwundene Datei sauber)."""
        super().__init__(timeout=60)
        self.entry = entry
        if link_ok is None:
            link_ok = sharing._sftpgo_link_allowed()
        for fmt, path in formats.items():
            size = (sizes or {}).get(fmt, 0)
            mb    = size / (1024 * 1024)
            big   = size > config._MAX_UPLOAD
            link  = big and link_ok
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
            btn.callback = self._make_callback(fmt, path, big, link, size)
            self.add_item(btn)

    def _make_callback(self, fmt: str, path: str, big: bool, link: bool,
                       size: int | None = None):
        async def _cb(interaction: discord.Interaction):
            # Gemeinfreiheits-Sperre auch hier (deckt den direkten SFTPGo-Link-Pfad ab).
            if sharing._is_locked(self.entry):
                rel = sharing._pd_release(self.entry)
                await interaction.response.send_message(
                    f'🔒 **{self.entry["title"]}** ist noch urheberrechtlich geschützt und wird '
                    f'erst am **{rel.strftime("%d.%m.%Y")}** gemeinfrei — bis dahin nicht teilbar.',
                    ephemeral=True)
                return
            if big and link:
                # Direkt antworten (kein defer nötig); Link-Bau liest den Mount → Thread
                msg = await asyncio.to_thread(sharing._sftpgo_message, self.entry, path, fmt, size)
                await interaction.response.send_message(msg, ephemeral=True)
                pw_msg = sharing._sftpgo_password_message()
                if pw_msg:
                    await interaction.followup.send(pw_msg, ephemeral=True)
                await asyncio.to_thread(stats.inc, interaction.user.id, 'downloads')
            elif big:
                try:
                    mb = (await asyncio.to_thread(os.path.getsize, path)) / (1024 * 1024)
                    msg = f'⚠️ Datei zu groß ({mb:.1f} MB, Discord-Limit 8 MB).{sharing._share_block_note()}'
                except OSError:
                    msg = '⚠️ Datei nicht mehr verfügbar (evtl. zwischenzeitlich synchronisiert/verschoben).'
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.response.defer(ephemeral=True)
                await _send_book(interaction, self.entry, path, fmt)
        return _cb


def _first_file_sizes(entries: list[dict]) -> list[int | None]:
    """Größe der ersten vorhandenen Datei je Eintrag (Bytes) oder None.

    Macht bis zu zwei stat-Aufrufe je Eintrag auf dem Bibliotheks-Mount
    (Syncthing-/Netzpfad) → NUR in einem Thread aufrufen (_library_page).
    """
    sizes: list[int | None] = []
    for e in entries:
        size = None
        for f in e.get('files', []):
            local = config._local_path(f)
            try:
                if local and os.path.isfile(local):
                    size = os.path.getsize(local)
                    break
            except OSError:
                continue
        sizes.append(size)
    return sizes


async def _library_page(pages: list[list[dict]], idx: int,
                        query: str) -> tuple[discord.Embed, list[int | None]]:
    """Embed + Dateigrößen einer Bibliotheks-Seite, alle stat-Aufrufe in einem Thread.

    _build_library_embed (sharing._collect_formats) und die Größen für _BookSelect lesen
    den Bibliotheks-Mount; im Event-Loop würde ein hängender Mount den ganzen Bot
    anhalten (Review W4s S4-025, Rest von PD-124).
    """
    entries = pages[idx]

    def _build():
        embed = _build_library_embed(entries, page=idx + 1, total_pages=len(pages), query=query)
        return embed, _first_file_sizes(entries)
    return await asyncio.to_thread(_build)


class _BookSelect(discord.ui.Select):
    """Dropdown zum Auswählen eines Buchs zum Download."""

    def __init__(self, entries: list[dict], sizes: list[int | None] | None = None):
        """``sizes`` (je Eintrag Bytes der ersten Datei, siehe _first_file_sizes)
        vorab in einem Thread ermitteln — der Konstruktor läuft im Event-Loop und
        macht selbst keine Datei-I/O; ohne ``sizes`` fehlt nur die Größenangabe."""
        options = []
        for i, e in enumerate(entries):
            emoji = _TYPE_EMOJI.get(e.get('file_type', ''), '📄')
            label = f'{e["title"]}'[:100]
            # Autor · Format · Größe
            parts = [_catalog._author_str(e.get('author', ''))]
            ft = e.get('file_type', '')
            if ft:
                parts.append(ft.upper())
            # Dateigröße der ersten vorhandenen Datei
            size = sizes[i] if sizes is not None and i < len(sizes) else None
            if size is not None:
                parts.append(f'{size / (1024 * 1024):.1f} MB')
            desc = ' · '.join(p for p in parts if p)[:100]
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

        # sharing._collect_formats macht viele os.path.isfile über evtl. langsame Netz-/Syncthing-Pfade
        # → in einen Thread auslagern, damit der Event-Loop nicht blockiert.
        formats = await asyncio.to_thread(sharing._collect_formats, entry)

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
            # Mehrere Formate → User wählen lassen. Groessen und Link-Freigabe vorab
            # im Thread ermitteln (getsize auf Netzpfaden und das Katalog-Laden der
            # Freigabe-Pruefung duerfen den Loop nicht blockieren).
            def _sizes():
                out = {}
                for f, p in formats.items():
                    try:
                        out[f] = os.path.getsize(p)
                    except OSError:
                        out[f] = 0
                return out, sharing._sftpgo_link_allowed()
            sizes, link_ok = await asyncio.to_thread(_sizes)
            fmts = '  '.join(
                f'{_FORMAT_EMOJI.get(f, "📄")} **{_FORMAT_LABEL.get(f, f.upper())}**'
                for f in formats)
            await interaction.response.send_message(
                f'**{entry["title"]}**\nVerfügbare Formate: {fmts}',
                view=_FormatView(entry, formats, sizes, link_ok),
                ephemeral=True)


class LibraryPaginationView(discord.ui.View):
    def __init__(self, pages: list[list[dict]], query: str,
                 sizes: list[int | None] | None = None):
        """``sizes``: Dateigrößen der ersten Seite aus _library_page (Thread)."""
        super().__init__(timeout=120)
        self.pages = pages
        self.query = query
        self.current = 0
        # Vor/Zurück nacheinander abarbeiten, siehe _show_page.
        self._nav_lock = asyncio.Lock()
        self._update_select(sizes)

    def _update_select(self, sizes: list[int | None] | None = None):
        # Altes Select entfernen falls vorhanden
        for child in self.children:
            if isinstance(child, _BookSelect):
                self.remove_item(child)
                break
        self.add_item(_BookSelect(self.pages[self.current], sizes))

    async def _show_page(self, interaction: discord.Interaction, step: int):
        """Blättert um ``step`` Seiten und zeigt die Seite an.

        discord.py startet je Klick einen eigenen Task, und _library_page gibt den
        Loop frei. Ohne Sperre überholen sich schnelle Klicks: Embed der einen,
        Auswahl der anderen Seite. Deshalb laufen die Klicks einer View nacheinander
        (zweimal Weiter = zwei Seiten, Edits in Klick-Reihenfolge). ``self.current``
        gilt erst nach dem Thread, damit Embed, Auswahl und Größen dieselbe Seite
        zeigen, auch wenn der Thread fehlschlägt (Review W4s S4-025).
        """
        async with self._nav_lock:
            idx = max(0, min(len(self.pages) - 1, self.current + step))
            embed, sizes = await _library_page(self.pages, idx, self.query)
            self.current = idx
            self._update_select(sizes)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='◀ Zurück', style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        await self._show_page(interaction, -1)

    @discord.ui.button(label='Weiter ▶', style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        await self._show_page(interaction, 1)
