"""
Unit-Tests fuer core/i18n.py.

Standalone-Script. Kein Discord-Mocking noetig.

Ausfuehren: python tests/test_i18n.py
"""

import sys
import os

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

from core.i18n import norm, t

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


def test_norm():
    check('Grossschreibung -> klein', norm('EN') == 'en')
    check('Locale-Suffix abgeschnitten', norm('de-DE') == 'de')
    check('None -> Default de', norm(None) == 'de')
    check('leer -> Default de', norm('') == 'de')
    check('nicht unterstuetzt -> de', norm('fr') == 'de')


def test_t():
    check('Default ist Deutsch', t('daily.label') == 'Tagespuzzle')
    check('Englisch explizit', t('daily.label', 'en') == 'Daily puzzle')
    check('unbekannte Sprache faellt auf de', t('daily.label', 'fr') == 'Tagespuzzle')
    check('format-Platzhalter (en)', t('daily.solved', 'en', n=2, body='Max') == '✅ Solved (2): Max')
    check('format-Platzhalter (de)', t('daily.more', 'de', n=3) == '+3 weitere')


if __name__ == '__main__':
    print('=== test_i18n.py ===\n')
    test_norm()
    test_t()
    print(f'\n--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
