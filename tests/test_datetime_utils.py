"""
Unit-Tests fuer core/datetime_utils.py.

Standalone-Script. Kein Discord-Mocking noetig (pure stdlib).

Ausfuehren: python tests/test_datetime_utils.py
"""

import sys
import os
from datetime import date, timezone

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

from core.datetime_utils import parse_datum, parse_utc, parse_zeit

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


def test_parse_datum():
    check('gueltiges TT.MM.JJJJ', parse_datum('31.12.2026') == date(2026, 12, 31))
    check('mit Whitespace', parse_datum('  01.06.2026 ') == date(2026, 6, 1))
    check('ISO-Format -> None', parse_datum('2026-12-31') is None)
    check('Quatsch -> None', parse_datum('foo') is None)
    check('ungueltiger Tag -> None', parse_datum('32.01.2026') is None)


def test_parse_utc():
    check('Z-Suffix -> UTC', parse_utc('2026-06-30T12:00:00Z').tzinfo == timezone.utc)
    naive = parse_utc('2026-06-30T12:00:00')
    check('naiv -> UTC ergaenzt', naive.tzinfo == timezone.utc)
    off = parse_utc('2026-06-30T12:00:00+02:00')
    check('Offset bleibt erhalten', off.utcoffset().total_seconds() == 7200)


def test_parse_zeit():
    check('"17" -> (17,0)', parse_zeit('17') == (17, 0))
    check('"9" -> (9,0)', parse_zeit('9') == (9, 0))
    check('"1730" -> (17,30)', parse_zeit('1730') == (17, 30))
    check('"17:30" -> (17,30)', parse_zeit('17:30') == (17, 30))
    check('"17 30" -> (17,30)', parse_zeit('17 30') == (17, 30))
    check('leer -> None', parse_zeit('') is None)
    check('"25" -> None (Stunde zu gross)', parse_zeit('25') is None)
    check('"1799" -> None (Minute zu gross)', parse_zeit('1799') is None)
    check('"abc" -> None', parse_zeit('abc') is None)
    check('"17:99" -> None', parse_zeit('17:99') is None)


if __name__ == '__main__':
    print('=== test_datetime_utils.py ===\n')
    test_parse_datum()
    test_parse_utc()
    test_parse_zeit()
    print(f'\n--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
