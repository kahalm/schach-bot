"""Tests fuer .github/scripts/changelog_discord.py (Changelog → Discord-Announce).

Ausfuehren: python tests/test_changelog_discord.py
"""

import importlib.util
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

_spec = importlib.util.spec_from_file_location(
    'changelog_discord', os.path.join(_REPO, '.github', 'scripts', 'changelog_discord.py'))
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)

_failures = []


def check(name, cond):
    print(('  OK   ' if cond else '  FAIL ') + name)
    if not cond:
        _failures.append(name)


_SAMPLE = """# Changelog

Kopftext.

## [2.78.18] - 2026-07-12
### Changed
- Duplikate konsolidiert.

## [2.78.17] - 2026-07-12
### Fixed
- dm_log-Pruning.

## [2.78.16] - 2026-07-11
### Fixed
- Sechs kleinere Bugs.
"""


def test_parse_sections():
    print('[parse_sections]')
    s = cd.parse_sections(_SAMPLE)
    check('3 Abschnitte', len(s) == 3)
    check('neuester zuerst', next(iter(s)) == '2.78.18')
    check('Datum extrahiert', s['2.78.18'][0] == '2026-07-12')
    check('Body ohne Kopfzeile', s['2.78.17'][1] == '### Fixed\n- dm_log-Pruning.')
    check('letzter Abschnitt bis Dateiende', 'kleinere Bugs' in s['2.78.16'][1])


def test_added_versions():
    print('[added_versions]')
    diff = (
        '+## [2.78.18] - 2026-07-12\n'
        '+### Changed\n'
        ' ## [2.78.16] - 2026-07-11\n'   # Kontextzeile → nicht neu
        '+## [2.78.17] - 2026-07-12\n'
        '-## [alt] - 2020-01-01\n'
    )
    v = cd.added_versions(diff)
    check('nur +-Header, chronologisch (aelteste zuerst)', v == ['2.78.17', '2.78.18'])
    check('leerer Diff → leer', cd.added_versions('') == [])


def test_build_message():
    print('[build_message]')
    m = cd.build_message('schach-bot', '2.78.18', '2026-07-12', 'Body-Zeile')
    check('Header + Body', m.startswith('**schach-bot v2.78.18** (2026-07-12)\n'))
    long = cd.build_message('schach-bot', '1.0.0', '2026-01-01', 'x' * 5000)
    check('Discord-Limit eingehalten', len(long) <= 2000)
    check('Ellipse bei Kuerzung', long.endswith('…'))


def test_main_without_webhook_is_noop():
    print('[main ohne Webhook]')
    os.environ.pop('WEBHOOK', None)
    check('Exit 0 ohne Secret', cd.main() == 0)


def main():
    for t in (test_parse_sections, test_added_versions, test_build_message,
              test_main_without_webhook_is_noop):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle changelog-discord-Tests bestanden.')


if __name__ == '__main__':
    main()
