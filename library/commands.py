"""Bibliothek: Slash-Commands /bibliothek, /tag, /autor (mit Autocomplete) und /reindex."""

import asyncio

import discord

from core.permissions import require_privileged
from library import catalog as _catalog
from library import config, search, views

# ---------------------------------------------------------------------------
# Slash-Commands registrieren
# ---------------------------------------------------------------------------

def setup(bot: discord.ext.commands.Bot):
    """Registriert alle Bibliothek-Commands auf dem Bot."""
    tree = bot.tree

    @tree.command(name='bibliothek', description='Schachbuch-Bibliothek durchsuchen',
                  extras={'help': 'bibliothek'})
    @discord.app_commands.describe(suche='Suchbegriff (Titel, Autor oder Tag)')
    async def cmd_bibliothek(interaction: discord.Interaction, suche: str):
        await interaction.response.defer(ephemeral=True)
        results = await asyncio.to_thread(search._search_library, suche, limit=50)
        if not results:
            await interaction.followup.send(
                f'Keine Treffer für „{suche}".', ephemeral=True)
            return
        pages = [results[i:i + 10] for i in range(0, len(results), 10)]
        embed, sizes = await views._library_page(pages, 0, suche)
        view = views.LibraryPaginationView(pages, query=suche, sizes=sizes)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @cmd_bibliothek.autocomplete('suche')
    async def bibliothek_autocomplete(
        interaction: discord.Interaction, current: str,
    ) -> list[discord.app_commands.Choice[str]]:
        if len(current) < 2:
            return []
        results = await asyncio.to_thread(search._search_library, current, limit=25)
        return [
            discord.app_commands.Choice(
                name=f'{_catalog._author_str(e.get("author", ""))}: {e["title"]}'[:100],
                value=e['title'][:100],
            )
            for e in results
        ]

    @tree.command(name='tag', description='Bücher nach Tag filtern', extras={'help': 'bibliothek'})
    @discord.app_commands.describe(tag='Tag zum Filtern')
    async def cmd_tag(interaction: discord.Interaction, tag: str):
        await interaction.response.defer(ephemeral=True)
        catalog = await asyncio.to_thread(search._ensure_library)
        results = [e for e in catalog
                   if tag.lower() in [t.lower() for t in e.get('tags', [])]]
        if not results:
            await interaction.followup.send(
                f'Keine Bücher mit Tag „{tag}".', ephemeral=True)
            return
        results.sort(key=lambda e: (_catalog._author_str(e.get('author', '')), e['title']))
        pages = [results[i:i + 10] for i in range(0, len(results), 10)]
        embed, sizes = await views._library_page(pages, 0, f'Tag: {tag}')
        view = views.LibraryPaginationView(pages, query=f'Tag: {tag}', sizes=sizes)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @cmd_tag.autocomplete('tag')
    async def tag_autocomplete(
        interaction: discord.Interaction, current: str,
    ) -> list[discord.app_commands.Choice[str]]:
        tags = await asyncio.to_thread(search._all_tags)
        if current:
            tags = [t for t in tags if current.lower() in t.lower()]
        return [
            discord.app_commands.Choice(name=t, value=t)
            for t in tags[:25]
        ]

    @tree.command(name='autor', description='Bücher eines Autors anzeigen',
                  extras={'help': 'bibliothek'})
    @discord.app_commands.describe(autor='Autorname')
    async def cmd_autor(interaction: discord.Interaction, autor: str):
        await interaction.response.defer(ephemeral=True)
        catalog = await asyncio.to_thread(search._ensure_library)
        results = [e for e in catalog
                   if autor.lower() in _catalog._author_str(e.get('author', '')).lower()]
        if not results:
            await interaction.followup.send(
                f'Keine Bücher von „{autor}".', ephemeral=True)
            return
        results.sort(key=lambda e: e['title'])
        pages = [results[i:i + 10] for i in range(0, len(results), 10)]
        embed, sizes = await views._library_page(pages, 0, f'Autor: {autor}')
        view = views.LibraryPaginationView(pages, query=f'Autor: {autor}', sizes=sizes)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @cmd_autor.autocomplete('autor')
    async def autor_autocomplete(
        interaction: discord.Interaction, current: str,
    ) -> list[discord.app_commands.Choice[str]]:
        authors = await asyncio.to_thread(search._all_authors)
        if current:
            authors = [a for a in authors if current.lower() in a.lower()]
        return [
            discord.app_commands.Choice(name=a[:100], value=a[:100])
            for a in authors[:25]
        ]

    @tree.command(name='reindex', description='Bibliotheks-Katalog + Puzzle-Cache neu aufbauen (Admin)',
                  extras={'help': 'admin'})
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_reindex(interaction: discord.Interaction):
        if not await require_privileged(interaction):
            return
        from puzzle import selection as _puzzle_sel  # lazy: zirkulaere Imports vermeiden
        await interaction.response.defer(ephemeral=True)

        loop = asyncio.get_running_loop()

        # Bibliotheks-Katalog – nur wenn config.LIBRARY_INDEX konfiguriert
        if config.LIBRARY_INDEX:
            lib_stats = await loop.run_in_executor(None, _catalog.build_library_catalog)
            search._reload_library()
            lib_msg = (
                f'📚 Bibliothek: Dateien **{lib_stats[0]}** · Bücher **{lib_stats[1]}** · '
                f'neu **{lib_stats[2]}** · aktualisiert **{lib_stats[3]}** · entfernt **{lib_stats[4]}**'
            )
        else:
            lib_msg = '📚 Bibliothek: übersprungen (`LIBRARY_INDEX` nicht in `.env`).'

        # Puzzle-Cache – PGNs neu parsen + filtern + auf Disk pickeln
        _puzzle_sel.clear_lines_cache()
        puzzle_lines = await loop.run_in_executor(None, _puzzle_sel.load_all_lines)
        puzzle_msg = f'♟️ Puzzle-Cache: **{len(puzzle_lines)}** gültige Linien gepickelt.'

        await interaction.followup.send(
            f'✅ Reindex fertig:\n{lib_msg}\n{puzzle_msg}',
            ephemeral=True)
