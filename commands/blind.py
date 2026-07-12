"""/blind: Blind-Puzzle – Stellung X Züge VOR der Trainingsposition.

Der User sieht das Brett X Halbzüge früher und muss die X Züge im Kopf
spielen, bevor er das eigentliche Puzzle löst. Nur Bücher mit
`"blind": true` in `books/books.json` sind erlaubt.
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
        description='Blind-Puzzle: Stellung X Züge vor der eigentlichen Aufgabe.',
    )
    @discord.app_commands.describe(
        moves='Anzahl Halbzüge, die du im Kopf spielen musst (Standard: 4; hat das Spiel weniger, wird das Maximum verwendet)',
        anzahl='Anzahl Puzzles (1–20, Standard: 1)',
        buch='Buchnummer aus /kurs (Standard: zufälliges Blind-Buch)',
        user='Puzzle an diesen User schicken (Standard: an dich selbst)',
    )
    @discord.app_commands.checks.cooldown(1, 10.0)
    async def cmd_blind(interaction: discord.Interaction,
                        moves: int = 4,
                        anzahl: int = 1,
                        buch: int = 0,
                        user: discord.Member | None = None):
        # Der Discord-Blind-Modus (lokale Bücher) wurde abgelöst: gelöst wird auf RookHub.
        log.info('/blind von %s (abgelöst)', interaction.user)
        await interaction.response.send_message(
            '🙈 Der **Blind-Modus im Discord wurde abgelöst** — gelöst wird jetzt auf RookHub. '
            'Hol dir ein Puzzle mit `/puzzle` (optional aus einem Buch: `/puzzle buch:<ID>`, '
            'IDs via `/kurs`).',
            ephemeral=True)
