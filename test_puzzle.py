"""
Standalone-Test: Puzzle-Linie laden, Lichess-Studie anlegen, Ergebnis pruefen.
Ausfuehren: python test_puzzle.py
"""
import sys
import os
import requests

from dotenv import load_dotenv
load_dotenv(dotenv_path='.env')

# discord-Import ueberspringen damit bot.py importierbar ist ohne laufenden Bot
import unittest.mock as _mock
sys.modules.setdefault('discord', _mock.MagicMock())
sys.modules.setdefault('discord.ext', _mock.MagicMock())
sys.modules.setdefault('discord.ext.tasks', _mock.MagicMock())
sys.modules.setdefault('discord.ext.commands', _mock.MagicMock())

import importlib
bot = importlib.import_module('bot')

LICHESS_TOKEN = os.getenv('LICHESS_TOKEN', '')


def verify_study(study_id: str, chapter_id: str) -> dict:
    """Kapiteldetails via Lichess-API abrufen."""
    headers = {'Authorization': f'Bearer {LICHESS_TOKEN}'} if LICHESS_TOKEN else {}
    r = requests.get(
        f'https://lichess.org/api/study/{study_id}/{chapter_id}',
        headers=headers,
        timeout=10,
    )
    if r.status_code == 200:
        return r.json()
    return {'error': f'HTTP {r.status_code}', 'body': r.text[:300]}


def count_chapters(study_id: str) -> int:
    """Anzahl Kapitel in einer Studie zaehlen (via PGN-Export)."""
    headers = {'Authorization': f'Bearer {LICHESS_TOKEN}'} if LICHESS_TOKEN else {}
    r = requests.get(
        f'https://lichess.org/api/study/{study_id}.pgn',
        headers=headers,
        timeout=10,
    )
    return r.text.count('[Event "') if r.status_code == 200 else -1


def main():
    print('=== Puzzle-Test ===\n')

    # 1. Zufaellige Linie laden
    result = bot.pick_random_line()
    if result is None:
        print('FEHLER: Keine Linien gefunden - PGN-Dateien in books/ ablegen.')
        return

    line_id, game = result
    h = dict(game.headers)
    print(f'Linie  : {line_id}')
    print(f'White  : {h.get("White", "?")}')
    print(f'Event  : {h.get("Event", "?")}')
    print(f'FEN    : {h.get("FEN", "(Startstellung)")}')
    print()

    # 2. Auf Trainingsposition kürzen, dann hochladen
    original_game = game
    game = bot._trim_to_training_position(game)
    trimmed = game is not original_game
    h = dict(game.headers)
    import chess as _chess
    board = game.board()
    am_zug = 'Schwarz' if board.turn == _chess.BLACK else 'Weiss'
    print(f'Getrimmt: {trimmed}')
    print(f'Nach Trim FEN: {h.get("FEN", "(Startstellung)")}')
    print(f'Am Zug  : {am_zug}')
    print()

    context = original_game if trimmed else None
    print('Lade auf Lichess hoch...')
    url = bot.upload_to_lichess(game, context_game=context)
    if not url:
        print('FEHLER: Upload fehlgeschlagen.')
        return

    print(f'OK  URL: {url}\n')

    # 3. Study/Chapter-ID aus URL parsen
    parts = url.rstrip('/').split('/')
    study_id = chapter_id = ''
    if 'study' in parts:
        idx = parts.index('study')
        study_id   = parts[idx + 1] if idx + 1 < len(parts) else ''
        chapter_id = parts[idx + 2] if idx + 2 < len(parts) else ''

    if not study_id:
        print(f'INFO: Kein Study-Link (Fallback-Import): {url}')
        return

    # 4. Kapitel per PGN-Export pruefen
    headers_auth = {'Authorization': f'Bearer {LICHESS_TOKEN}'} if LICHESS_TOKEN else {}
    r = requests.get(f'https://lichess.org/api/study/{study_id}.pgn',
                     headers=headers_auth, timeout=10)
    if r.status_code == 200:
        pgn_text = r.text
        n_chapters = pgn_text.count('[ChapterName "')
        n_gamebook = pgn_text.count('[ChapterMode "gamebook"]')
        has_fen    = '[SetUp "1"]' in pgn_text
        expected   = 2 if trimmed else 1
        ok = n_chapters == expected and n_gamebook == (1 if trimmed else 0) and has_fen == trimmed
        print(f'{"OK" if ok else "WARN"}  Kapitel: {n_chapters} (erwartet: {expected}), '
              f'Gamebook: {n_gamebook}, FEN-Setup: {has_fen}')
    else:
        print(f'WARN: PGN-Export HTTP {r.status_code}')

    print('\nFertig.')


if __name__ == '__main__':
    main()
