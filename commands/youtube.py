"""YouTube-Sammlung: Schach-YouTube-Kanäle und -Videos teilen und auflisten."""

import json
import logging
import os
from datetime import date

import discord
from discord.ext import commands

from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

YOUTUBE_FILE = os.path.join(CONFIG_DIR, 'youtube.json')


def _load() -> list[dict]:
    try:
        with open(YOUTUBE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(data: list[dict]):
    with open(YOUTUBE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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
            if not beschreibung:
                await interaction.response.send_message(
                    '⚠️ Bitte auch eine `beschreibung` angeben.',
                    ephemeral=True)
                return
            videos = _load()
            videos.append({
                'url': url,
                'beschreibung': beschreibung,
                'user': interaction.user.display_name,
                'datum': str(date.today()),
            })
            _save(videos)
            await interaction.response.send_message(
                f'✅ YouTube-Link gespeichert: **{beschreibung}**\n{url}')
            return

        # Auflisten
        videos = _load()
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
