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
        moves='Anzahl Halbzüge, die du im Kopf spielen musst (1–20, Standard: 4)',
        anzahl='Anzahl Puzzles (1–20, Standard: 1)',
        buch='Buchnummer aus /kurs (Standard: zufälliges Blind-Buch)',
    )
    async def cmd_blind(interaction: discord.Interaction,
                        moves: int = 4,
                        anzahl: int = 1,
                        buch: int = 0):
        log.info('/blind von %s: moves=%d anzahl=%d buch=%d',
                 interaction.user, moves, anzahl, buch)
        if moves < 1:
            await interaction.response.send_message(
                '⚠️ `moves` muss mindestens 1 sein.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            dm = await interaction.user.create_dm()
            await puzzle.post_blind_puzzle(
                dm,
                moves=moves,
                count=anzahl,
                book_idx=buch,
                user_id=interaction.user.id,
            )
            await interaction.followup.send(
                f'🙈 Blind-Puzzle ({anzahl}× / {moves} Züge) per DM gesendet.',
                ephemeral=True)
        except Exception as e:
            log.exception('/blind fehlgeschlagen')
            await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)
