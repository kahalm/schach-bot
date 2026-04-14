"""Slash-Command /test – Trim-Snapshot-Regressionstests live im Discord."""

import asyncio
import json
import logging
import os

import io

import chess.pgn
import discord

from puzzle.legacy import (
    find_line_by_id, _trim_to_training_position, build_puzzle_embed,
    _render_board, _load_books_config, _strip_pgn_annotations, _prelude_pgn,
    _flatten_null_move_variations, upload_to_lichess,
)

log = logging.getLogger('schach-bot')

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(_ROOT, 'books')
SNAPSHOTS_FILE = os.path.join(_ROOT, 'tests', 'trim_snapshots.json')


def _load_snapshots():
    with open(SNAPSHOTS_FILE, encoding='utf-8') as f:
        return json.load(f)


def _find_game(filename, round_id):
    """PGN-Datei lesen und Partie mit passendem Round-Header finden."""
    path = os.path.join(BOOKS_DIR, filename)
    with open(path, encoding='utf-8') as f:
        pgn_text = _flatten_null_move_variations(f.read())
    stream = io.StringIO(pgn_text)
    while True:
        try:
            game = chess.pgn.read_game(stream)
        except Exception:
            continue
        if game is None:
            raise ValueError(f'Round {round_id!r} nicht gefunden in {filename}')
        if game.headers.get('Round', '') == round_id:
            return game


def _book_label(filename):
    return filename.replace('_firstkey.pgn', '')


class _PuzzleSelect(discord.ui.Select):
    """Dropdown zum Rendern eines getesteten Puzzles."""

    def __init__(self, puzzle_ids: list[tuple[str, str]]):
        options = [
            discord.SelectOption(label=label[:100], value=pid)
            for label, pid in puzzle_ids
        ]
        super().__init__(placeholder='Puzzle anzeigen...', options=options)

    async def callback(self, interaction: discord.Interaction):
        puzzle_id = self.values[0]
        await interaction.response.defer(ephemeral=True)

        result = find_line_by_id(puzzle_id)
        if not result:
            await interaction.followup.send(
                f'Puzzle `{puzzle_id}` nicht gefunden.', ephemeral=True)
            return

        line_id, original_game = result
        game = _trim_to_training_position(original_game)
        context = original_game if game is not original_game else None

        board = game.board()
        turn = board.turn
        try:
            img = await asyncio.to_thread(_render_board, board)
        except Exception:
            img = None

        fname = line_id.split(':')[0]
        meta = _load_books_config().get(fname, {})
        embed = build_puzzle_embed(
            game, turn=turn,
            difficulty=meta.get('difficulty', ''),
            rating=meta.get('rating', 0),
            line_id=line_id,
        )

        # Loesung + Partie als Felder anhaengen (max 1024 Zeichen pro Feld)
        def _field_val(text):
            val = f'||`{text}`||'
            if len(val) > 1024:
                val = f'||`{text[:1014]}`…||'
            return val

        exporter = chess.pgn.StringExporter(
            headers=False, variations=True, comments=True)
        pgn_moves = _strip_pgn_annotations(game.accept(exporter))
        if pgn_moves:
            embed.add_field(
                name='Loesung', value=_field_val(pgn_moves), inline=False)
        if context:
            prelude = _prelude_pgn(context, game)
            if prelude:
                embed.add_field(
                    name='Ganze Partie', value=_field_val(prelude), inline=False)

        # Lichess-Upload
        loop = asyncio.get_running_loop()
        puzzle_url = await loop.run_in_executor(
            None, lambda: upload_to_lichess(game, context_game=context))

        if puzzle_url:
            embed.add_field(
                name='Lichess', value=f'[Studie öffnen]({puzzle_url})', inline=False)

        if img:
            file = discord.File(img, filename='board.png')
            embed.set_image(url='attachment://board.png')
            await interaction.followup.send(
                file=file, embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)


def setup(bot):
    @bot.tree.command(name='test', description='Trim-Snapshot-Tests ausfuehren (Admin)')
    @discord.app_commands.default_permissions(administrator=True)
    async def test_cmd(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        snapshots = _load_snapshots()
        ok_count = 0
        fields = []
        puzzle_ids = []  # (label, puzzle_id) fuer Dropdown

        # Pro Buch zaehlen fuer #1, #2, #3 ...
        book_counter = {}
        for snap in snapshots:
            fn = snap['filename']
            book_counter[fn] = book_counter.get(fn, 0) + 1

        book_seen = {}
        for snap in snapshots:
            filename = snap['filename']
            round_id = snap['round']
            exp_trimmed = snap['trimmed']
            exp_fen = snap['fen']
            exp_side = snap['side']
            exp_first = snap['first_move_uci']

            base = _book_label(filename)
            book_seen[filename] = book_seen.get(filename, 0) + 1
            label = f'{base} #{book_seen[filename]}' if book_counter[filename] > 1 else base
            errors = []

            try:
                game = _find_game(filename, round_id)
                result = _trim_to_training_position(game)
                was_trimmed = result is not game

                if was_trimmed != exp_trimmed:
                    errors.append(f'trimmed: {was_trimmed}, erwartet {exp_trimmed}')

                result_fen = result.headers.get('FEN', result.board().fen())
                if result_fen != exp_fen:
                    errors.append(f'FEN abweichend')

                side = 'b' if ' b ' in result_fen else 'w'
                if side != exp_side:
                    errors.append(f'side: {side}, erwartet {exp_side}')

                if result.variations:
                    first_move = result.variations[0].move.uci()
                else:
                    first_move = '-'
                if first_move != exp_first:
                    errors.append(f'move: {first_move}, erwartet {exp_first}')

                context = game if was_trimmed else None

                exporter = chess.pgn.StringExporter(
                    headers=False, variations=True, comments=True)
                solution = _strip_pgn_annotations(result.accept(exporter))
                exp_solution = snap.get('solution', '')
                if exp_solution and solution != exp_solution:
                    errors.append(f'solution abweichend')

                if exp_trimmed:
                    prelude = _prelude_pgn(context, result) if context else ''
                    exp_prelude = snap.get('prelude', '')
                    if exp_prelude and prelude != exp_prelude:
                        errors.append(f'prelude abweichend')

            except Exception as exc:
                errors.append(str(exc))

            puzzle_id = f'{filename}:{round_id}'
            puzzle_ids.append((label, puzzle_id))

            if errors:
                fields.append((
                    f'FAIL {label}',
                    f'`{puzzle_id}`\n' + '\n'.join(errors),
                ))
            else:
                ok_count += 1
                side_label = 'w' if exp_side == 'w' else 'b'
                move_info = exp_first if exp_first != '-' else 'keine Variante'
                fields.append((
                    f'OK {label}',
                    f'`{puzzle_id}`\n{"trimmed" if exp_trimmed else "untrimmed"} · {side_label} am Zug · {move_info}',
                ))

        total = len(snapshots)
        all_ok = ok_count == total
        colour = 0x4e9e4e if all_ok else 0xe74c3c

        embed = discord.Embed(
            title='Trim-Snapshot-Tests',
            colour=colour,
        )
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)
        embed.set_footer(text=f'{ok_count}/{total} OK')

        view = discord.ui.View(timeout=300)
        view.add_item(_PuzzleSelect(puzzle_ids[:25]))  # Select max 25 Optionen

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
