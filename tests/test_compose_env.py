"""Guard: jeder Schluessel aus .env.example kommt im Container an.

Ausfuehren: python tests/test_compose_env.py   (laeuft auch in tests/run_all.py)
Nur stdlib, liest docker-compose.yml/.env.example als Text (kein PyYAML im Image).

Hintergrund (Review W4s S4-023): Die Repo-Compose zaehlt die Variablen einzeln
unter ``environment:`` auf (bewusst kein ``env_file``, das reichte jede
Stack-Variable durch). ``load_dotenv()`` hilft im Container nicht, weil
``.dockerignore`` die ``.env`` ausschliesst und sie nicht gemountet wird.
DAILY_EXTRA_CHANNEL_IDS, DAILY_DEFAULT_LANG und LIBRARY_ENFORCE_PD standen in
.env.example, fehlten aber in der Compose: gesetzt, aber still wirkungslos.
Jeder neue Schluessel in .env.example muss deshalb in docker-compose.yml
stehen oder hier mit Begruendung als Ausnahme.
"""

import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Schluessel aus .env.example, die bewusst NICHT durchgereicht werden → Grund.
EXCEPTIONS = {
    'WEBHOOK_BIND_HOST': (
        'im Container fest der Code-Default 0.0.0.0 (bot.py); nur so erreicht das '
        'Port-Mapping den Webhook. Ein aus einer lokalen .env uebernommenes 127.0.0.1 '
        'machte ihn unerreichbar; einschraenken ueber ports (z. B. '
        '"127.0.0.1:${WEBHOOK_PORT}:9000"), nicht ueber die Bind-Adresse.'),
}

_failures = []


def check(name, cond, detail=''):
    print(('  OK   ' if cond else '  FAIL ') + name + (f'  [{detail}]' if detail and not cond else ''))
    if not cond:
        _failures.append(name)


def _read(name):
    with open(os.path.join(_REPO, name), encoding='utf-8') as f:
        return f.read()


def env_example_keys(text):
    """Schluessel der Zuweisungen ``KEY=...`` (Kommentarzeilen zaehlen nicht)."""
    return re.findall(r'^([A-Z][A-Z0-9_]*)=', text, re.M)


def compose_keys(text):
    """Schluessel, die die Compose setzt (``- KEY=``/``KEY:``) oder referenziert (``${KEY}``)."""
    code = '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#'))
    keys = set(re.findall(r'^\s*-\s*([A-Z][A-Z0-9_]*)=', code, re.M))
    keys |= set(re.findall(r'^\s+([A-Z][A-Z0-9_]*):', code, re.M))
    keys |= set(re.findall(r'\$\{([A-Z][A-Z0-9_]*)', code))
    return keys


def test_helpers():
    check('env_example_keys: Kommentare zaehlen nicht',
          env_example_keys('# FOO=1\nBAR=\nBAZ=x # c\n') == ['BAR', 'BAZ'])
    check('compose_keys: Liste, Referenz, auskommentiert',
          compose_keys('    environment:\n      - A=${A}\n      - B=fest\n'
                       '    ports:\n      - "${C:-9}:9000"\n      # - D=${D}\n') == {'A', 'B', 'C'})


def test_every_env_example_key_reaches_container():
    env_keys = env_example_keys(_read('.env.example'))
    compose = _read('docker-compose.yml')
    in_compose = compose_keys(compose)
    check('.env.example hat Schluessel', len(env_keys) > 10, f'{env_keys}')
    missing = [k for k in env_keys if k not in in_compose and k not in EXCEPTIONS]
    check('jeder .env.example-Schluessel steht in docker-compose.yml oder ist Ausnahme',
          not missing, f'fehlen: {missing}')
    for k in ('DAILY_EXTRA_CHANNEL_IDS', 'DAILY_DEFAULT_LANG', 'LIBRARY_ENFORCE_PD'):
        check(f'{k} unter environment:',
              re.search(rf'^\s*-\s*{k}=\$\{{{k}(:-[^}}]*)?\}}\s*$', compose, re.M) is not None)
    check('kein env_file (reichte jede Stack-Variable durch)',
          re.search(r'^\s*env_file\s*:', compose, re.M) is None)


def test_exceptions_are_current():
    env_keys = set(env_example_keys(_read('.env.example')))
    in_compose = compose_keys(_read('docker-compose.yml'))
    stale = sorted(k for k in EXCEPTIONS if k not in env_keys or k in in_compose)
    check('Ausnahmen stehen in .env.example und NICHT in der Compose', not stale, f'{stale}')
    check('jede Ausnahme hat eine Begruendung', all(len(v) > 20 for v in EXCEPTIONS.values()))


def main():
    for t in (test_helpers, test_every_env_example_key_reaches_container, test_exceptions_are_current):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle Compose-Env-Tests bestanden.')


if __name__ == '__main__':
    main()
