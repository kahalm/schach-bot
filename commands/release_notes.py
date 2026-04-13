"""/release-notes: zeigt Einträge aus CHANGELOG.md im Channel."""

import logging
import os
import re

import discord
from discord.ext import commands

from core.version import VERSION

log = logging.getLogger('schach-bot')

CHANGELOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'CHANGELOG.md',
)

# "## [1.1.0] - 2026-04-13"
_VERSION_HEADER_RE = re.compile(r'^##\s+\[([^\]]+)\](?:\s*-\s*(.*))?\s*$')


def _parse_changelog() -> list[dict]:
    """Parst CHANGELOG.md zu einer Liste von {version, date, body}-Dicts.

    Reihenfolge wie in der Datei (neueste zuerst). Body enthält den
    Markdown-Text zwischen den Versions-Headern (ohne den Header selbst).
    """
    try:
        with open(CHANGELOG_FILE, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return []

    entries: list[dict] = []
    current: dict | None = None
    for line in lines:
        m = _VERSION_HEADER_RE.match(line)
        if m:
            if current is not None:
                current['body'] = '\n'.join(current['body']).strip()
                entries.append(current)
            current = {
                'version': m.group(1).strip(),
                'date': (m.group(2) or '').strip(),
                'body': [],
            }
            continue
        if current is not None:
            current['body'].append(line)
    if current is not None:
        current['body'] = '\n'.join(current['body']).strip()
        entries.append(current)
    return entries


def setup(bot: commands.Bot):
    """Registriert den /release-notes Command."""
    tree = bot.tree

    @tree.command(name='release-notes',
                  description='Zeigt die Versionshistorie (Changelog) des Bots')
    @discord.app_commands.describe(
        version='Optional: bestimmte Version anzeigen (z.B. 1.1.0)',
        anzahl='Wie viele Versionen anzeigen (Default 3)')
    async def cmd_release_notes(interaction: discord.Interaction,
                                version: str = None,
                                anzahl: int = 3):
        entries = _parse_changelog()
        if not entries:
            await interaction.response.send_message(
                'ℹ️ Kein Changelog gefunden.', ephemeral=True)
            return

        if version:
            entries = [e for e in entries if e['version'] == version]
            if not entries:
                await interaction.response.send_message(
                    f'⚠️ Version `{version}` nicht im Changelog.',
                    ephemeral=True)
                return
        else:
            anzahl = max(1, min(anzahl, 10))
            entries = entries[:anzahl]

        embed = discord.Embed(
            title=f'📝 Release Notes (aktuell v{VERSION})',
            color=discord.Color.blue(),
        )
        for entry in entries:
            name = f"v{entry['version']}"
            if entry['date']:
                name += f" — {entry['date']}"
            body = entry['body'] or '_(keine Notizen)_'
            # Discord embed-field limit: 1024 Zeichen
            if len(body) > 1024:
                body = body[:1020] + '\n…'
            embed.add_field(name=name, value=body, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)
