"""Ressourcen-Sammlung: Online-Lernressourcen teilen und auflisten."""

import json
import logging
import os
from datetime import date

import discord
from discord.ext import commands

from paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

RESOURCEN_FILE = os.path.join(CONFIG_DIR, 'resourcen.json')


def _load() -> list[dict]:
    try:
        with open(RESOURCEN_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(data: list[dict]):
    with open(RESOURCEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def setup(bot: commands.Bot):
    """Registriert den /resourcen Command."""
    tree = bot.tree

    @tree.command(name='resourcen',
                  description='Online-Lernressourcen anzeigen oder hinzufügen')
    @discord.app_commands.describe(
        url='URL der Ressource (zum Hinzufügen)',
        beschreibung='Kurze Beschreibung der Ressource')
    async def cmd_resourcen(interaction: discord.Interaction,
                            url: str = None,
                            beschreibung: str = None):
        # Hinzufügen
        if url:
            if not beschreibung:
                await interaction.response.send_message(
                    '⚠️ Bitte auch eine `beschreibung` angeben.',
                    ephemeral=True)
                return
            ressourcen = _load()
            ressourcen.append({
                'url': url,
                'beschreibung': beschreibung,
                'user': interaction.user.display_name,
                'datum': str(date.today()),
            })
            _save(ressourcen)
            await interaction.response.send_message(
                f'✅ Ressource gespeichert: **{beschreibung}**\n{url}')
            return

        # Auflisten
        ressourcen = _load()
        if not ressourcen:
            await interaction.response.send_message(
                'Noch keine Ressourcen vorhanden. '
                'Füge eine hinzu mit `/resourcen url:… beschreibung:…`',
                ephemeral=True)
            return

        embed = discord.Embed(title='🔗 Ressourcen', color=0x3498db)
        for i, r in enumerate(ressourcen, 1):
            name = f'{i}. {r["beschreibung"]}'
            if len(name) > 256:
                name = name[:253] + '...'
            value = f'{r["url"]}\n_von {r["user"]} am {r["datum"]}_'
            embed.add_field(name=name, value=value, inline=False)

        await interaction.response.send_message(embed=embed)
