"""
Test: Puzzle hochladen und via Lichess-API verifizieren.

Prueft:
  1. Studie wurde angelegt (URL zurueckgegeben)
  2. Genau 1 oder 2 Kapitel vorhanden (kein Auto-Kapitel uebrig)
  3. Kapitel 1 ist im Gamebook-Modus
  4. FEN im Kapitel stimmt mit der getrimmten Startposition ueberein
  5. Kapitel 2 (wenn vorhanden) ist im Normal-Modus
  6. URL zeigt direkt auf das Gamebook-Kapitel

Ausfuehren: python test_upload.py
"""
import sys
import os
import io
import requests

from dotenv import load_dotenv
load_dotenv(dotenv_path='.env')

import unittest.mock as _mock
sys.modules.setdefault('discord', _mock.MagicMock())
sys.modules.setdefault('discord.ext', _mock.MagicMock())
sys.modules.setdefault('discord.ext.tasks', _mock.MagicMock())
sys.modules.setdefault('discord.ext.commands', _mock.MagicMock())

import importlib
bot = importlib.import_module('bot')
import chess.pgn

LICHESS_TOKEN = os.getenv('LICHESS_TOKEN', '')
AUTH = {'Authorization': f'Bearer {LICHESS_TOKEN}'} if LICHESS_TOKEN else {}

PASS = 'OK  '
FAIL = 'FAIL'
WARN = 'WARN'


def _get_study_pgn(study_id: str) -> str | None:
    r = requests.get(
        f'https://lichess.org/api/study/{study_id}.pgn',
        headers=AUTH, timeout=15,
    )
    return r.text if r.status_code == 200 else None


def _parse_chapters(pgn_text: str) -> list[dict]:
    """Alle Kapitel einer Studie als Liste von Header-Dicts zurueckgeben."""
    chapters = []
    stream = io.StringIO(pgn_text)
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        chapters.append(dict(game.headers))
    return chapters


def check(label: str, ok: bool, detail: str = '') -> bool:
    icon = PASS if ok else FAIL
    suffix = f'  ({detail})' if detail else ''
    print(f'  {icon}  {label}{suffix}')
    return ok


def run_test(label: str, game, original_game, trimmed: bool) -> bool:
    context = original_game if trimmed else None
    expected_chapters = 2 if trimmed else 1

    print(f'\n--- {label} ---')
    print(f'  Getrimmt   : {trimmed}')
    board = game.board()
    expected_fen = board.fen()
    print(f'  Start-FEN  : {expected_fen}')
    print(f'  Erwartet   : {expected_chapters} Kapitel')
    print()

    # --- Upload ---
    print('  Lade hoch...')
    url = bot.upload_to_lichess(game, context_game=context)

    all_ok = True
    all_ok &= check('URL zurueckgegeben', bool(url), url or 'None')
    if not url:
        return False

    print(f'  URL: {url}')

    # --- URL parsen ---
    parts = url.rstrip('/').split('/')
    study_id = chapter_id = ''
    if 'study' in parts:
        idx = parts.index('study')
        study_id   = parts[idx + 1] if idx + 1 < len(parts) else ''
        chapter_id = parts[idx + 2] if idx + 2 < len(parts) else ''

    all_ok &= check('URL enthaelt Study-ID', bool(study_id), study_id)
    all_ok &= check('URL enthaelt Chapter-ID', bool(chapter_id),
                    chapter_id or 'fehlt – nur Study-Root')

    if not study_id:
        return False

    # --- Studie per API abrufen ---
    pgn_text = _get_study_pgn(study_id)
    all_ok &= check('Studie per API abrufbar', pgn_text is not None)
    if not pgn_text:
        return False

    chapters = _parse_chapters(pgn_text)

    # Prüfung 1: Kapitelanzahl
    all_ok &= check(
        f'Kapitelanzahl = {expected_chapters}',
        len(chapters) == expected_chapters,
        f'tatsaechlich: {len(chapters)}',
    )

    if not chapters:
        return False

    ch1 = chapters[0]

    # Prüfung 2: Kapitel 1 ist Gamebook
    mode1 = ch1.get('ChapterMode', '')
    all_ok &= check('Kapitel 1 = Gamebook', mode1 == 'gamebook', f'mode={mode1!r}')

    # Prüfung 3: FEN stimmt (nur wenn getrimmt)
    if trimmed:
        setup = ch1.get('SetUp', '')
        fen_hdr = ch1.get('FEN', '')
        # Nur die ersten 4 Felder vergleichen (ohne Zugzähler)
        fen_main = ' '.join(expected_fen.split()[:4])
        fen_ch   = ' '.join(fen_hdr.split()[:4])
        all_ok &= check('SetUp=1 gesetzt', setup == '1', f'SetUp={setup!r}')
        all_ok &= check('FEN stimmt ueberein', fen_main == fen_ch,
                        f'\n       erwartet : {fen_main}\n       kapitel  : {fen_ch}')
    else:
        has_fen = ch1.get('SetUp', '') == '1'
        all_ok &= check('Keine FEN (Startstellung)', not has_fen,
                        'SetUp=1 gesetzt obwohl nicht getrimmt')

    # Prüfung 4: Kapitel 2 ist Normal-Modus (wenn vorhanden)
    if trimmed and len(chapters) >= 2:
        mode2 = chapters[1].get('ChapterMode', '')
        all_ok &= check('Kapitel 2 = Normal', mode2 in ('', 'normal'),
                        f'mode={mode2!r}')

    # Prüfung 5: Chapter-ID in URL zeigt auf Gamebook-Kapitel
    if chapter_id:
        url_ch = ch1.get('ChapterURL', '')
        url_ch_id = url_ch.rstrip('/').split('/')[-1] if url_ch else ''
        all_ok &= check('URL-Chapter-ID zeigt auf Kapitel 1',
                        chapter_id == url_ch_id,
                        f'{chapter_id!r} vs {url_ch_id!r}')

    return all_ok


def main():
    print('=== Lichess Upload Test ===\n')

    if not LICHESS_TOKEN:
        print(f'{WARN} Kein LICHESS_TOKEN – nur Fallback-Import moeglich, kein Gamebook-Test.')

    if bot._lichess_rate_limited():
        import time as _t
        remaining = int((bot._lichess_cooldown_until() - _t.time()) / 60) + 1
        print(f'{FAIL} Lichess-Cooldown aktiv – noch ca. {remaining} Minuten warten.')
        print('       lichess_cooldown.json loeschen um Cooldown manuell zurueckzusetzen.')
        return

    results = []

    # Test 1: Puzzle das eine Trainingsposition hat (getrimmt)
    print('Suche Linie mit [%tqu]-Annotation...')
    trimmed_game = trimmed_original = None
    for _ in range(50):
        result = bot.pick_random_line()
        if result is None:
            break
        _, g = result
        trimmed = bot._trim_to_training_position(g)
        if trimmed is not g:
            trimmed_game, trimmed_original = trimmed, g
            break

    if trimmed_game:
        ok = run_test('Test 1: Getrimmt (mit Kontext-Kapitel)', trimmed_game, trimmed_original, True)
        results.append(('Getrimmt', ok))
    else:
        print(f'{WARN} Keine getrimmte Linie in 50 Versuchen gefunden – Test 1 uebersprungen.')

    # Test 2: Puzzle ohne Trim (startet direkt an Trainingsposition)
    print('\nSuche Linie ohne Trim...')
    plain_game = plain_original = None
    for _ in range(50):
        result = bot.pick_random_line()
        if result is None:
            break
        _, g = result
        trimmed = bot._trim_to_training_position(g)
        if trimmed is g:
            plain_game, plain_original = trimmed, g
            break

    if plain_game:
        ok = run_test('Test 2: Nicht getrimmt (nur Gamebook)', plain_game, plain_original, False)
        results.append(('Nicht getrimmt', ok))
    else:
        print(f'{WARN} Keine ungetrimmte Linie in 50 Versuchen gefunden – Test 2 uebersprungen.')

    # Zusammenfassung
    print('\n' + '=' * 40)
    print('Ergebnis:')
    for name, ok in results:
        print(f'  {PASS if ok else FAIL}  {name}')
    if not results:
        print('  Keine Tests ausgefuehrt.')
    print()


if __name__ == '__main__':
    main()
