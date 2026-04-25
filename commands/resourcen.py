"""Ressourcen-Sammlung: Online-Lernressourcen teilen und auflisten."""

import logging
import os
from datetime import date

import discord
from discord.ext import commands

from core.paths import CONFIG_DIR
from core.json_store import atomic_read, atomic_write

log = logging.getLogger('schach-bot')

RESOURCEN_FILE = os.path.join(CONFIG_DIR, 'resourcen.json')
_MAX_ENTRIES = 100


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
            if not url.startswith(('http://', 'https://')):
                await interaction.response.send_message(
                    '⚠️ Bitte eine gueltige URL angeben (http:// oder https://).',
                    ephemeral=True)
                return
            if not beschreibung:
                await interaction.response.send_message(
                    '⚠️ Bitte auch eine `beschreibung` angeben.',
                    ephemeral=True)
                return
            ressourcen = atomic_read(RESOURCEN_FILE, default=list)
            if len(ressourcen) >= _MAX_ENTRIES:
                await interaction.response.send_message(
                    f'⚠️ Maximum von {_MAX_ENTRIES} Eintraegen erreicht.',
                    ephemeral=True)
                return
            ressourcen.append({
                'url': url,
                'beschreibung': beschreibung,
                'user': interaction.user.display_name,
                'datum': str(date.today()),
            })
            atomic_write(RESOURCEN_FILE, ressourcen)
            await interaction.response.send_message(
                f'✅ Ressource gespeichert: **{beschreibung}**\n{url}')
            return

        # Auflisten
        ressourcen = atomic_read(RESOURCEN_FILE, default=list)
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
