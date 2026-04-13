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
        user='Puzzle an diesen User schicken (Standard: an dich selbst)',
    )
    async def cmd_blind(interaction: discord.Interaction,
                        moves: int = 4,
                        anzahl: int = 1,
                        buch: int = 0,
                        user: discord.Member | None = None):
        target_user = user or interaction.user
        log.info('/blind von %s: moves=%d anzahl=%d buch=%d user=%s',
                 interaction.user, moves, anzahl, buch, target_user)
        if moves < 1:
            await interaction.response.send_message(
                '⚠️ `moves` muss mindestens 1 sein.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            dm = await target_user.create_dm()
            if user:
                await dm.send(f'**{interaction.user.display_name}** schickt dir ein Blind-Puzzle 🙈')
            await puzzle.post_blind_puzzle(
                dm,
                moves=moves,
                count=anzahl,
                book_idx=buch,
                user_id=target_user.id,
            )
            dest = f'an {target_user.mention}' if user else 'dir'
            await interaction.followup.send(
                f'🙈 Blind-Puzzle ({anzahl}× / {moves} Züge) {dest} per DM gesendet.',
                ephemeral=True)
        except Exception as e:
            log.exception('/blind fehlgeschlagen')
            await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)
