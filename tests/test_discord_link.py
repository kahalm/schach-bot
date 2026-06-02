"""Standalone-Tests für den Discord-Link-Token-Helfer (core/discord_link.py).

Ausführen: python tests/test_discord_link.py
Nur stdlib (kein discord, keine PGN-Daten).
"""

import base64
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from core import discord_link as dl

_failures = []

SECRET = 'shared-test-secret-1234567890'

# Golden-Vektor: MUSS mit RookHubs C#-Test (DiscordLinkServiceTests.Verify_AcceptsKnownPythonToken)
# identisch sein – verankert den Cross-Language-Round-Trip (Python signiert → C# verifiziert).
GOLDEN = ('eyJpZCI6IjEyMzQ1Njc4OTAxMjM0NTY3OCIsInUiOiJDb29sdXNlciIsImV4cCI6OTk5OTk5OTk5OX0'
          '.U2wXL2W7i08klm58xTSHnpy4S6FE0RYmvurRKuQrIsY')


def check(name, cond):
    print(('  OK   ' if cond else '  FAIL ') + name)
    if not cond:
        _failures.append(name)


def _b64url_decode(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def test_golden_vector():
    tok = dl.make_link_token('123456789012345678', 'Cooluser',
                             ttl_seconds=9999999999, secret=SECRET, now=0)
    check('Golden-Token reproduzierbar (Cross-Language-Anker)', tok == GOLDEN)


def test_token_structure():
    tok = dl.make_link_token('42', 'Name', secret=SECRET, now=1000, ttl_seconds=60)
    check('Token hat genau ein Trennzeichen', tok.count('.') == 1)
    body, sig = tok.split('.')
    payload = json.loads(_b64url_decode(body))
    check('payload.id', payload['id'] == '42')
    check('payload.u', payload['u'] == 'Name')
    check('payload.exp = now + ttl', payload['exp'] == 1060)
    check('kein base64-Padding im body', '=' not in body)
    check('kein base64-Padding in der Signatur', '=' not in sig)


def test_signature_depends_on_secret():
    a = dl.make_link_token('42', 'x', secret='secret-a', now=0, ttl_seconds=60)
    b = dl.make_link_token('42', 'x', secret='secret-b', now=0, ttl_seconds=60)
    check('andere Secrets → andere Signatur', a.split('.')[1] != b.split('.')[1])


def test_no_secret_returns_none():
    check('kein Secret → kein Token', dl.make_link_token('42', 'x', secret='') is None)
    check('is_enabled(False) ohne Secret', dl.is_enabled('') is False)
    check('is_enabled(True) mit Secret', dl.is_enabled('s') is True)


def test_append_dl():
    url = dl.append_dl('https://rookhub.example/register', '42', 'Name', secret=SECRET)
    check('append_dl hängt ?dl= an', '?dl=' in url and url.startswith('https://rookhub.example/register?dl='))


def test_append_dl_preserves_existing_query():
    url = dl.append_dl('https://x.example/profile?foo=1', '42', secret=SECRET)
    check('append_dl behält bestehende Query', 'foo=1' in url and 'dl=' in url)


def test_append_dl_no_secret_unchanged():
    url = dl.append_dl('https://x.example/register', '42', secret='')
    check('append_dl ohne Secret → URL unverändert', url == 'https://x.example/register')


def test_append_dl_empty_url():
    check('append_dl(None) → None', dl.append_dl(None, '42', secret=SECRET) is None)
    check('append_dl("") → ""', dl.append_dl('', '42', secret=SECRET) == '')


def main():
    for t in (test_golden_vector, test_token_structure, test_signature_depends_on_secret,
              test_no_secret_returns_none, test_append_dl, test_append_dl_preserves_existing_query,
              test_append_dl_no_secret_unchanged, test_append_dl_empty_url):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle Discord-Link-Token-Tests bestanden.')


if __name__ == '__main__':
    main()
