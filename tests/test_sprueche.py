"""
Unit-Tests fuer core/sprueche.py (random_spruch Formatierung).

Standalone-Script. Setzt den Modul-Cache direkt, um deterministisch zu testen
(kein Datei-/Zufalls-Zugriff noetig).

Ausfuehren: python tests/test_sprueche.py
"""

import sys
import os

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

import core.sprueche as sprueche

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


def test_with_author():
    sprueche._sprueche_cache = [{'text': 'Schach ist Leben', 'autor': 'Fischer'}]
    check('mit Autor formatiert', sprueche.random_spruch() == '_"Schach ist Leben"_ — Fischer')


def test_without_author():
    sprueche._sprueche_cache = [{'text': 'Nur ein Zug'}]
    check('ohne Autor formatiert', sprueche.random_spruch() == '_"Nur ein Zug"_')


def test_empty_cache():
    sprueche._sprueche_cache = []
    check('leerer Cache -> leerer String', sprueche.random_spruch() == '')


if __name__ == '__main__':
    print('=== test_sprueche.py ===\n')
    try:
        test_with_author()
        test_without_author()
        test_empty_cache()
    finally:
        sprueche._sprueche_cache = None   # Cache zuruecksetzen
    print(f'\n--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
