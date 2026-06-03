"""Embed-Bau fuer Puzzle-Nachrichten."""

import chess
import discord

# Wird auch von daily_results.refresh() referenziert (gleicher String dort als SOLVER_FIELD).
# Wenn dieser Name geaendert wird, muss daily_results.SOLVER_FIELD mitgezogen werden.
DAILY_SOLVER_FIELD = '🏆 Tagespuzzle'


def build_daily_embed(turn: chess.Color,
                      solution_san: str = '',
                      color: int = 0x7fa650) -> discord.Embed:
    """Minimaler Embed fuers Tagespuzzle.

    Reihenfolge (von oben nach unten, wie Discord rendert):
      [Brett-Bild]  – wird vom Aufrufer ueber ``set_image`` angehaengt
      Am Zug        – Field
      🏆 Tagespuzzle – Placeholder; ``daily_results.refresh`` setzt die Solver-Zeile
      💡 Lösung     – Spoiler mit der SAN-Lösung

    Kein Titel, keine Kapitel/Linie/Schwierigkeit, kein Footer, kein RookHub-Link.
    """
    embed = discord.Embed(color=color)
    turn_str = '⬜ Weiß am Zug' if turn == chess.WHITE else '⬛ Schwarz am Zug'
    embed.add_field(name='Am Zug', value=turn_str, inline=False)
    embed.add_field(name=DAILY_SOLVER_FIELD, value='Noch niemand gelöst', inline=False)
    if solution_san:
        embed.add_field(name='💡 Lösung', value=f'||`{solution_san}`||', inline=False)
    return embed


def build_puzzle_embed(game: chess.pgn.Game,
                       turn: chess.Color | None = None,
                       puzzle_num: int = 0,
                       puzzle_total: int = 0,
                       difficulty: str = '',
                       rating: int = 0,
                       line_id: str = '',
                       blind_moves: int = 0) -> discord.Embed:
    h = dict(game.headers)
    line_name  = h.get('White', h.get('Event', 'Linie'))
    event_name = h.get('Event', '')
    black_name = h.get('Black', '')

    # Kursname als Titel
    course = event_name or 'Puzzle'
    if len(course) > 80:
        course = course[:77] + '...'

    embed = discord.Embed(
        title=f'🧩 {course}',
        color=0x7fa650,
    )

    if black_name:
        embed.add_field(name='📖 Kapitel', value=f'||{black_name}||', inline=False)

    if line_name and line_name != event_name:
        embed.add_field(name='📝 Linie', value=f'||{line_name}||', inline=False)

    if difficulty:
        embed.add_field(name='📊 Schwierigkeit', value=difficulty, inline=True)

    # Bild wird extern via set_image gesetzt

    if turn is not None:
        turn_str = '⬜ Weiß am Zug' if turn == chess.WHITE else '⬛ Schwarz am Zug'
        embed.add_field(name='Am Zug', value=turn_str, inline=True)

    if puzzle_num > 0:
        stats = f'Heute: **{puzzle_num}** · Gesamt: **{puzzle_total}**'
        embed.add_field(name='\u200b', value=stats, inline=False)

    if line_id:
        footer = f'ID: {line_id}:blind:{blind_moves}' if blind_moves else f'ID: {line_id}'
    else:
        footer = '🧩 Tägliches Puzzle'
    embed.set_footer(text=footer)
    return embed
