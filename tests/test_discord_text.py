"""Standalone-Tests fuer core/discord_text.py (Discord-Grenzen clip/fit_list).

Ausfuehren: python tests/test_discord_text.py   (laeuft auch in tests/run_all.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.discord_text import (  # noqa: E402
    EMBED_FIELD_VALUE_MAX, EMBED_TITLE_MAX, clip, fit_list,
)

_failures = []


def check(name, cond):
    print(('  OK   ' if cond else '  FAIL ') + name)
    if not cond:
        _failures.append(name)


def test_limits():
    check('Embed-Titel 256', EMBED_TITLE_MAX == 256)
    check('Feldwert 1024', EMBED_FIELD_VALUE_MAX == 1024)


def test_clip():
    check('passt → byte-gleich', clip('Mate in 2', 256) == 'Mate in 2')
    check('genau an der Grenze → unveraendert', clip('a' * 256, 256) == 'a' * 256)
    check('leer/None → leer', clip(None, 10) == '' and clip('', 10) == '')
    hard = clip('a' * 300, 256)
    check('ohne Wortgrenze hart gekuerzt + …', len(hard) == 256 and hard.endswith('…'))
    words = clip('Kapitel ' + 'Wort ' * 80, 256)
    check('an der Wortgrenze gekuerzt', len(words) <= 256 and words.endswith('Wort…'))
    mention = clip('x' * 200 + ' <@123456789012345678>' + 'y' * 10, 215)
    check('keine halbe Erwaehnung', '<@' not in mention and mention.endswith('…'))
    esc = clip('a' * 8 + '\\*' * 10, 10)
    check('kein verwaister Backslash vor …', not esc.rstrip('…').endswith('\\') and len(esc) <= 10)
    pair = clip('a' * 7 + '\\\\' + 'b' * 10, 10)
    check('escapter Backslash bleibt als Paar', pair == 'a' * 7 + '\\\\…')


def test_fit_list():
    def render(shown):
        more = 20 - len(shown)
        return ', '.join(shown) + (f' +{more} weitere' if more else '') + ' | Fuss'

    items = [f'Name{i:02d}' for i in range(20)]
    full = fit_list(items, render, 1024)
    check('passt → genau render(items)', full == render(items))
    tight = fit_list(items, render, 60)
    check('zu lang → hinten Eintraege weg', len(tight) <= 60 and tight.endswith(' | Fuss'))
    shown = tight.count('Name')
    check('+N weitere passt zu den weggefallenen', f'+{20 - shown} weitere' in tight)
    check('clip sichert den Rest ab', len(fit_list(items, lambda s: 'z' * 2000, 1024)) == 1024)


def main():
    for t in (test_limits, test_clip, test_fit_list):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle discord_text-Tests bestanden.')


if __name__ == '__main__':
    main()
