"""YouTube-Sammlung: Schach-YouTube-Kanäle und -Videos teilen und auflisten."""

import logging
import os
from datetime import date

import discord
from discord.ext import commands

from core.paths import CONFIG_DIR
from core.json_store import atomic_read, atomic_write

log = logging.getLogger('schach-bot')

YOUTUBE_FILE = os.path.join(CONFIG_DIR, 'youtube.json')
_MAX_ENTRIES = 100


def setup(bot: commands.Bot):
    """Registriert den /youtube Command."""
    tree = bot.tree

    @tree.command(name='youtube',
                  description='YouTube-Kanäle/Videos anzeigen oder hinzufügen')
    @discord.app_commands.describe(
        url='YouTube-URL (zum Hinzufügen)',
        beschreibung='Kurze Beschreibung (Kanal/Video)')
    async def cmd_youtube(interaction: discord.Interaction,
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
            videos = atomic_read(YOUTUBE_FILE, default=list)
            if len(videos) >= _MAX_ENTRIES:
                await interaction.response.send_message(
                    f'⚠️ Maximum von {_MAX_ENTRIES} Eintraegen erreicht.',
                    ephemeral=True)
                return
            videos.append({
                'url': url,
                'beschreibung': beschreibung,
                'user': interaction.user.display_name,
                'datum': str(date.today()),
            })
            atomic_write(YOUTUBE_FILE, videos)
            await interaction.response.send_message(
                f'✅ YouTube-Link gespeichert: **{beschreibung}**\n{url}')
            return

        # Auflisten
        videos = atomic_read(YOUTUBE_FILE, default=list)
        if not videos:
            await interaction.response.send_message(
                'Noch keine YouTube-Links vorhanden. '
                'Füge einen hinzu mit `/youtube url:… beschreibung:…`',
                ephemeral=True)
            return

        embed = discord.Embed(title='▶️ YouTube', color=0xff0000)
        for i, v in enumerate(videos, 1):
            name = f'{i}. {v["beschreibung"]}'
            if len(name) > 256:
                name = name[:253] + '...'
            value = f'{v["url"]}\n_von {v["user"]} am {v["datum"]}_'
            embed.add_field(name=name, value=value, inline=False)

        await interaction.response.send_message(embed=embed)
