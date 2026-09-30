"""/blind: abgelöster Discord-Blind-Modus – nur noch ein Hinweis-Stub.

Früher: Stellung X Halbzüge VOR der Trainingsposition aus lokalen Büchern. Gelöst wird jetzt
auf RookHub (``/puzzle``, ``/blindpuzzle``). Der Stub bleibt parameterlos für eine Version,
damit alte Gewohnheiten einen Hinweis statt „unbekannter Befehl“ bekommen; er steht weder in
der Begrüßung noch in ``/help`` (``extras={'help': None}``).
"""

import logging

import discord
from discord.ext import commands

import puzzle

log = logging.getLogger('schach-bot')


def setup(bot: commands.Bot):
    tree = bot.tree

    @tree.command(
        name='blind',
        description='Abgelöst: Blind-Puzzles gibt es jetzt über /blindpuzzle bzw. RookHub.',
        extras={'help': None},
    )
    @discord.app_commands.checks.cooldown(1, 10.0)
    async def cmd_blind(interaction: discord.Interaction):
        # Der Discord-Blind-Modus (lokale Bücher) wurde abgelöst: gelöst wird auf RookHub.
        log.info('/blind von %s (abgelöst)', interaction.user)
        await interaction.response.send_message(
            '🙈 Der **Blind-Modus im Discord wurde abgelöst** — gelöst wird jetzt auf RookHub. '
            'Hol dir ein Puzzle mit `/puzzle` (optional aus einem Buch: `/puzzle buch:<ID>`, '
            'IDs via `/kurs`) oder ein Blind-Puzzle mit `/blindpuzzle`.',
            ephemeral=True)
