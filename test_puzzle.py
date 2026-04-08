"""
Standalone-Test: Puzzle-Linie laden, Lichess-Studie anlegen, Ergebnis pruefen.
Ausfuehren: python test_puzzle.py
"""
import sys
import os
import requests

from dotenv import load_dotenv
load_dotenv()

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

    # 2. Auf Lichess hochladen (neue Studie + Gamebook-Kapitel)
    print('Lade auf Lichess hoch...')
    url = bot.upload_to_lichess(game)
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

    # 4. Anzahl Kapitel pruefen (sollte genau 1 sein)
    n = count_chapters(study_id)
    status = 'OK' if n == 1 else 'WARN'
    print(f'{status}  Kapitel in Studie: {n} (erwartet: 1)')

    # 5. Kapiteldetails pruefen
    if chapter_id:
        print(f'Pruefe Kapitel {chapter_id}...')
        data = verify_study(study_id, chapter_id)
        if 'error' in data:
            print(f'WARN: API-Antwort: {data}')
        else:
            print(f'OK  Name : {data.get("name", "?")}')
            print(f'    Felder: {sorted(data.keys())}')

    print('\nFertig.')


if __name__ == '__main__':
    main()
