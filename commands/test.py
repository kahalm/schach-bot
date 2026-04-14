"""Slash-Command /test – Trim-Snapshot-Regressionstests live im Discord."""

import asyncio
import json
import logging
import os

import io

import chess.pgn
import discord

from puzzle.legacy import (
    find_line_by_id, _trim_to_training_position, trim_and_advance,
    build_puzzle_embed,
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
        game = trim_and_advance(original_game, line_id=line_id)
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


def _resolve_book_filename(book_idx: int) -> str | None:
    """1-basierte Buchnummer → Dateiname oder None."""
    if book_idx < 1:
        return None
    books = sorted(f for f in os.listdir(BOOKS_DIR) if f.endswith('.pgn'))
    if 1 <= book_idx <= len(books):
        return books[book_idx - 1]
    return None


def setup(bot):
    @bot.tree.command(name='test', description='Trim-Snapshot-Tests ausfuehren (Admin)')
    @discord.app_commands.default_permissions(administrator=True)
    @discord.app_commands.describe(
        kurs='Buchnummer aus /kurs (Standard: alle Buecher)',
        puzzle='1 = Board-Bild + Loesung pro Snapshot',
        lichess='1 = Lichess-Studienlink pro Snapshot',
    )
    async def test_cmd(interaction: discord.Interaction, kurs: int = 0,
                       puzzle: int = 0, lichess: int = 0):
        await interaction.response.defer(ephemeral=True)

        snapshots = _load_snapshots()

        # Optional nach Buch filtern
        if kurs > 0:
            book_fn = _resolve_book_filename(kurs)
            if not book_fn:
                await interaction.followup.send(
                    f'Buch {kurs} nicht gefunden. `/kurs` zeigt die Liste.',
                    ephemeral=True)
                return
            snapshots = [s for s in snapshots if s['filename'] == book_fn]
            if not snapshots:
                await interaction.followup.send(
                    f'Keine Snapshots fuer Buch {kurs} (`{_book_label(book_fn)}`).',
                    ephemeral=True)
                return
        show_puzzle = puzzle == 1
        show_lichess = lichess == 1

        ok_count = 0
        fields = []
        puzzle_ids = []  # (label, puzzle_id) fuer Dropdown
        # Fuer Detail-Ausgabe (puzzle/lichess) die Ergebnisse merken
        detail_results: list[dict] = []

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
            trimmed_game = None
            context_game = None
            solution_text = ''

            try:
                game = _find_game(filename, round_id)
                line_id_key = f'{filename}:{round_id}'
                result = trim_and_advance(game, line_id=line_id_key)
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

                context_game = game if was_trimmed else None

                exporter = chess.pgn.StringExporter(
                    headers=False, variations=True, comments=True)
                solution_text = _strip_pgn_annotations(result.accept(exporter))
                exp_solution = snap.get('solution', '')
                if exp_solution and solution_text != exp_solution:
                    errors.append(f'solution abweichend')

                if exp_trimmed:
                    prelude = _prelude_pgn(context_game, result) if context_game else ''
                    exp_prelude = snap.get('prelude', '')
                    if exp_prelude and prelude != exp_prelude:
                        errors.append(f'prelude abweichend')

                trimmed_game = result

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

            if (show_puzzle or show_lichess) and trimmed_game is not None:
                detail_results.append({
                    'label': label,
                    'puzzle_id': puzzle_id,
                    'game': trimmed_game,
                    'context': context_game,
                    'solution': solution_text,
                    'side': exp_side,
                })

        total = len(snapshots)
        all_ok = ok_count == total
        colour = 0x4e9e4e if all_ok else 0xe74c3c

        # Discord max 25 Felder pro Embed — bei Bedarf auf mehrere aufteilen.
        MAX_FIELDS = 25
        embeds = []
        for i in range(0, len(fields), MAX_FIELDS):
            chunk = fields[i:i + MAX_FIELDS]
            embed = discord.Embed(
                title='Trim-Snapshot-Tests' if i == 0 else None,
                colour=colour,
            )
            for name, value in chunk:
                embed.add_field(name=name, value=value, inline=False)
            embeds.append(embed)
        embeds[-1].set_footer(text=f'{ok_count}/{total} OK')

        view = discord.ui.View(timeout=300)
        view.add_item(_PuzzleSelect(puzzle_ids[:25]))  # Select max 25 Optionen

        await interaction.followup.send(embeds=embeds, view=view, ephemeral=True)

        # Detail-Nachrichten (puzzle / lichess)
        for det in detail_results:
            g = det['game']
            ctx = det['context']
            side_str = 'Weiss' if det['side'] == 'w' else 'Schwarz'
            header = f"**{det['label']}** · `{det['puzzle_id']}` · {side_str} am Zug"

            parts = [header]

            # Loesung als Spoiler
            if show_puzzle and det['solution']:
                sol = det['solution']
                if len(sol) > 1900:
                    sol = sol[:1900] + '…'
                parts.append(f'||`{sol}`||')

            # Lichess-Link
            lichess_url = None
            if show_lichess:
                loop = asyncio.get_running_loop()
                lichess_url = await loop.run_in_executor(
                    None, lambda _g=g, _c=ctx: upload_to_lichess(_g, context_game=_c))
                if lichess_url:
                    parts.append(lichess_url)

            text = '\n'.join(parts)

            # Board-Bild
            if show_puzzle:
                try:
                    img = await asyncio.to_thread(_render_board, g.board())
                    file = discord.File(img, filename='board.png')
                    await interaction.followup.send(
                        text, file=file, ephemeral=True)
                except Exception:
                    await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.followup.send(text, ephemeral=True)
