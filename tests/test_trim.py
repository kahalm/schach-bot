"""
Snapshot-Regressionstests fuer _trim_to_training_position.

Pro Buch ein fixierter Testcase. Prueft:
  - trimmed (ja/nein)
  - FEN der resultierenden Startstellung
  - Seite am Zug
  - Erster Zug (UCI) oder '-' wenn keine Variante vorhanden

Ausfuehren: python tests/test_trim.py
"""
import sys
import os
import json
import unittest.mock as _mock

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# Mock heavy/unavailable dependencies before importing puzzle.legacy
for mod_name in (
    'discord', 'discord.ext', 'discord.ext.tasks', 'discord.ext.commands',
    'discord.ui',
    'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',
    'PIL.ImageChops', 'PIL.ImageOps',
    'svglib', 'svglib.svglib',
    'reportlab', 'reportlab.graphics', 'reportlab.graphics.renderPM',
    'requests',
):
    sys.modules.setdefault(mod_name, _mock.MagicMock())

from puzzle.legacy import (
    _trim_to_training_position, trim_and_advance, _strip_pgn_annotations,
    _prelude_pgn, _flatten_null_move_variations,
)
import chess.pgn

BOOKS_DIR = os.path.join(parent_dir, 'books')
SNAPSHOTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trim_snapshots.json')

PASS = 'OK  '
FAIL = 'FAIL'

total = 0
failed = 0


def check(label, ok, detail=''):
    global total, failed
    total += 1
    if ok:
        print(f'  {PASS} {label}')
    else:
        failed += 1
        msg = f'  {FAIL} {label}'
        if detail:
            msg += f'  ({detail})'
        print(msg)


def find_game(filename, round_id):
    """PGN-Datei lesen und Partie mit passendem Round-Header finden."""
    path = os.path.join(BOOKS_DIR, filename)
    with open(path, encoding='utf-8') as f:
        pgn_text = _flatten_null_move_variations(f.read())
    import io
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


def load_snapshots():
    with open(SNAPSHOTS_FILE, encoding='utf-8') as f:
        return json.load(f)


def main():
    snapshots = load_snapshots()
    print(f'Snapshot-Tests fuer _trim_to_training_position ({len(snapshots)} Buecher)\n')

    for snap in snapshots:
        filename = snap['filename']
        round_id = snap['round']
        exp_trimmed = snap['trimmed']
        exp_fen = snap['fen']
        exp_side = snap['side']
        exp_first = snap['first_move_uci']

        label = filename.replace('_firstkey.pgn', '')
        print(f'[{label}]  Round {round_id}')

        game = find_game(filename, round_id)
        line_id_key = f'{filename}:{round_id}'
        result = trim_and_advance(game, line_id=line_id_key)
        was_trimmed = result is not game

        check('trimmed', was_trimmed == exp_trimmed,
              f'got {was_trimmed}, expected {exp_trimmed}')

        result_fen = result.headers.get('FEN', result.board().fen())
        check('fen', result_fen == exp_fen,
              f'got {result_fen}')

        side = 'b' if ' b ' in result_fen else 'w'
        check('side', side == exp_side,
              f'got {side}, expected {exp_side}')

        if result.variations:
            first_move = result.variations[0].move.uci()
        else:
            first_move = '-'
        check('first_move', first_move == exp_first,
              f'got {first_move}, expected {exp_first}')

        context = game if was_trimmed else None

        exporter = chess.pgn.StringExporter(
            headers=False, variations=True, comments=True)
        solution = _strip_pgn_annotations(result.accept(exporter))
        exp_solution = snap.get('solution', '')
        if exp_solution:
            check('solution', solution == exp_solution,
                  f'got {solution!r}')

        if exp_trimmed:
            prelude = _prelude_pgn(context, result) if context else ''
            exp_prelude = snap.get('prelude', '')
            if exp_prelude:
                check('prelude', prelude == exp_prelude,
                      f'got {prelude!r}')

        print()

    print(f'---\n{total - failed}/{total} checks passed.')
    if failed:
        print(f'{failed} FAILED')
        sys.exit(1)
    else:
        print('Alle Snapshots OK.')


if __name__ == '__main__':
    main()
