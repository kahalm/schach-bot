"""Feature-Wunschliste: Vorschläge einreichen, abstimmen, verwalten."""

import logging
import os
from datetime import date

import discord
from discord.ext import commands

from core.paths import CONFIG_DIR
from core.json_store import atomic_read, atomic_write

log = logging.getLogger('schach-bot')

WANTED_FILE = os.path.join(CONFIG_DIR, 'wanted.json')
_MAX_ENTRIES = 100


def _next_id(entries: list) -> int:
    if not entries:
        return 1
    return max(e['id'] for e in entries) + 1


def setup(bot: commands.Bot):
    """Registriert die /wanted, /wanted_list, /wanted_vote, /wanted_delete Commands."""
    tree = bot.tree

    @tree.command(name='wanted',
                  description='Feature-Wunsch einreichen (oder Liste anzeigen ohne Argument)')
    @discord.app_commands.describe(
        beschreibung='Beschreibung des Feature-Wunsches')
    async def cmd_wanted(interaction: discord.Interaction,
                         beschreibung: str = None):
        if not beschreibung:
            # Alias für /wanted_list
            await _show_list(interaction)
            return

        entries = atomic_read(WANTED_FILE, default=list)
        if len(entries) >= _MAX_ENTRIES:
            await interaction.response.send_message(
                f'⚠️ Maximum von {_MAX_ENTRIES} Eintraegen erreicht.',
                ephemeral=True)
            return
        new_id = _next_id(entries)
        entries.append({
            'id': new_id,
            'text': beschreibung,
            'user': interaction.user.display_name,
            'user_id': interaction.user.id,
            'datum': str(date.today()),
            'votes': [interaction.user.id],
        })
        atomic_write(WANTED_FILE, entries)
        await interaction.response.send_message(
            f'✅ Feature-Wunsch #{new_id} gespeichert: **{beschreibung}**')

    @tree.command(name='wanted_list',
                  description='Alle Feature-Wünsche anzeigen (sortiert nach Stimmen)')
    async def cmd_wanted_list(interaction: discord.Interaction):
        await _show_list(interaction)

    @tree.command(name='wanted_vote',
                  description='Für einen Feature-Wunsch abstimmen (Toggle)')
    @discord.app_commands.describe(id='Nummer des Feature-Wunsches')
    async def cmd_wanted_vote(interaction: discord.Interaction, id: int):
        entries = atomic_read(WANTED_FILE, default=list)
        entry = next((e for e in entries if e['id'] == id), None)
        if not entry:
            await interaction.response.send_message(
                f'❌ Feature-Wunsch #{id} nicht gefunden.', ephemeral=True)
            return

        uid = interaction.user.id
        if uid in entry['votes']:
            entry['votes'].remove(uid)
            atomic_write(WANTED_FILE, entries)
            await interaction.response.send_message(
                f'↩️ Stimme für Feature #{id} zurückgenommen.', ephemeral=True)
        else:
            entry['votes'].append(uid)
            atomic_write(WANTED_FILE, entries)
            await interaction.response.send_message(
                f'✅ +1 für Feature #{id}', ephemeral=True)

    @tree.command(name='wanted_delete',
                  description='Feature-Wunsch löschen (Admin)')
    @discord.app_commands.describe(id='Nummer des Feature-Wunsches')
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_wanted_delete(interaction: discord.Interaction, id: int):
        entries = atomic_read(WANTED_FILE, default=list)
        before = len(entries)
        entries = [e for e in entries if e['id'] != id]
        if len(entries) == before:
            await interaction.response.send_message(
                f'❌ Feature-Wunsch #{id} nicht gefunden.', ephemeral=True)
            return
        atomic_write(WANTED_FILE, entries)
        await interaction.response.send_message(
            f'🗑️ Feature-Wunsch #{id} gelöscht.', ephemeral=True)

    async def _show_list(interaction: discord.Interaction):
        entries = atomic_read(WANTED_FILE, default=list)
        if not entries:
            await interaction.response.send_message(
                'Noch keine Feature-Wünsche vorhanden. '
                'Reiche einen ein mit `/wanted beschreibung:…`',
                ephemeral=True)
            return

        # Sortiert nach Votes (meiste zuerst)
        entries_sorted = sorted(entries, key=lambda e: len(e['votes']), reverse=True)

        lines = []
        for e in entries_sorted:
            votes = len(e['votes'])
            lines.append(
                f"**#{e['id']}** — {e['text']} (+{votes})\n"
                f"_von {e['user']} am {e['datum']}_"
            )

        text = '\n\n'.join(lines)
        if len(text) > 4096:
            text = text[:4093] + '...'

        embed = discord.Embed(
            title='💡 Feature-Wünsche',
            description=text,
            color=0x3498db,
        )
        embed.set_footer(text='Abstimmen mit /wanted_vote <id>')
        await interaction.response.send_message(embed=embed)
