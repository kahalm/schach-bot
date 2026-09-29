"""Standalone-Tests: Platzhalter-Geheimnisse aus .env.example schalten das Feature ab (core/secret_env.py).

Ausführen: python tests/test_secret_env.py   (laeuft auch in tests/run_all.py)
Braucht requests + python-chess (fuer puzzle/rookhub.py), kein discord.

Hintergrund (Review W2 I2-001): .env.example trug fuer ROOKHUB_LINK_SECRET und
ROOKHUB_STATS_SECRET denselben nicht-leeren Platzhalter, und der Bot uebernahm ihn
ungeprueft. Wer ihn beim Aufsetzen stehen liess, signierte ?dl=-Links und Bot-Aufrufe mit
einem oeffentlich bekannten Schluessel und pruefte /webhook/build-info damit.
"""

import importlib
import importlib.util
import inspect
import logging
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from core import secret_env  # noqa: E402
from core import discord_link  # noqa: E402

_failures = []


def check(name, cond, detail=''):
    print(('  OK   ' if cond else '  FAIL ') + name + (f'  [{detail}]' if detail and not cond else ''))
    if not cond:
        _failures.append(name)


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class _Env:
    """Setzt Umgebungsvariablen fuer einen Block und stellt sie danach wieder her."""

    def __init__(self, **values):
        self.values = values
        self.saved = {}

    def __enter__(self):
        for k, v in self.values.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _capture():
    cap = _Capture()
    logging.getLogger('schach-bot').addHandler(cap)
    secret_env._reported.clear()
    return cap


def _release(cap):
    logging.getLogger('schach-bot').removeHandler(cap)
    secret_env._reported.clear()


def _read(*parts):
    with open(os.path.join(_REPO, *parts), encoding='utf-8') as f:
        return f.read()


def test_is_placeholder():
    for v in ('change_me', 'change_me_shared_with_rookhub', 'CHANGE_ME_x', '  change_me_x ',
              'your_private_key_here', 'change_me_stats_secret_same_as_rookhub_SchachBot__StatsSecret'):
        check(f'Platzhalter erkannt: {v!r}', secret_env.is_placeholder(v))
    for v in ('', None, 'x9f3Kq2-echter-wert', 'mein_change_me', 'yourself-secret'):
        check(f'kein Platzhalter: {v!r}', not secret_env.is_placeholder(v))


def test_secret_from_env():
    cap = _capture()
    try:
        with _Env(RH_TEST_SECRET='echt-9f3Kq2'):
            check('echter Wert bleibt', secret_env.secret_from_env('RH_TEST_SECRET', 'Test') == 'echt-9f3Kq2')
        with _Env(RH_TEST_SECRET=''):
            check('leer bleibt leer', secret_env.secret_from_env('RH_TEST_SECRET', 'Test') == '')
        check('echt/leer → kein ERROR', cap.messages == [], f'{cap.messages}')
        with _Env(RH_TEST_SECRET='change_me_shared_with_rookhub'):
            check('Platzhalter → leer', secret_env.secret_from_env('RH_TEST_SECRET', 'Testfeature') == '')
            secret_env.secret_from_env('RH_TEST_SECRET', 'Testfeature')
        check('Platzhalter → genau ein ERROR je Variable', len(cap.messages) == 1, f'{cap.messages}')
        check('ERROR nennt Variable und Feature', bool(cap.messages)
              and 'RH_TEST_SECRET' in cap.messages[0] and 'Testfeature' in cap.messages[0])
        check('ERROR enthaelt den Wert nicht', not any('change_me_shared' in m for m in cap.messages))
    finally:
        _release(cap)


def test_link_secret_placeholder_disables_links():
    cap = _capture()
    try:
        with _Env(ROOKHUB_LINK_SECRET='change_me_link_secret_same_as_rookhub_Discord__LinkSecret'):
            dl = importlib.reload(discord_link)
            check('Link-Platzhalter → LINK_SECRET leer', dl.LINK_SECRET == '')
            check('Link-Platzhalter → Feature aus', not dl.is_enabled())
            check('Link-Platzhalter → kein ?dl=-Token',
                  dl.append_dl('https://rh.example/register', 123, 'x') == 'https://rh.example/register')
        check('Link-Platzhalter → ERROR beim Laden', any('ROOKHUB_LINK_SECRET' in m for m in cap.messages))
        with _Env(ROOKHUB_LINK_SECRET='echt-link-secret'):
            dl = importlib.reload(discord_link)
            check('echtes Link-Secret → Token wie bisher', dl.LINK_SECRET == 'echt-link-secret'
                  and '?dl=' in dl.append_dl('https://rh.example/register', 123, 'x'))
    finally:
        _release(cap)
        importlib.reload(discord_link)


def _load_rookhub():
    spec = importlib.util.spec_from_file_location(
        'rookhub_secret_test', os.path.join(_REPO, 'puzzle', 'rookhub.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stats_secret_placeholder_disables_feature():
    cap = _capture()
    try:
        with _Env(ROOKHUB_STATS_SECRET='change_me_stats_secret_same_as_rookhub_SchachBot__StatsSecret',
                  ROOKHUB_API_URL='http://rookhub.test'):
            rh = _load_rookhub()
        check('Stats-Platzhalter → ROOKHUB_STATS_SECRET leer', rh.ROOKHUB_STATS_SECRET == '')
        check('Stats-Platzhalter → ERROR beim Laden', any('ROOKHUB_STATS_SECRET' in m for m in cap.messages))
        calls = []
        orig_get = rh.requests.get

        class _Resp200:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {'username': 'x'}

        rh.requests.get = lambda *a, **kw: calls.append(a) or _Resp200()
        try:
            check('Stats-Platzhalter → Ergebnis-GETs unsigniert', rh._bot_auth_headers('/api/x') == {})
            check('Stats-Platzhalter → /motivation aus (PROGRESS_UNAVAILABLE, kein Aufruf)',
                  rh.get_player_progress(1) is rh.PROGRESS_UNAVAILABLE and not calls)
        finally:
            rh.requests.get = orig_get
        with _Env(ROOKHUB_STATS_SECRET='echt-stats-secret'):
            rh2 = _load_rookhub()
        check('echtes Stats-Secret → signiert wie bisher', rh2.ROOKHUB_STATS_SECRET == 'echt-stats-secret'
              and 'X-Bot-Signature' in rh2._bot_auth_headers('/api/x'))
    finally:
        _release(cap)


def test_all_bot_secrets_use_check():
    """Jede Stelle, die ein mit RookHub geteiltes Geheimnis liest, geht ueber secret_from_env."""
    from core import webhook_server
    start_src = inspect.getsource(webhook_server.start)
    check('build-info prueft mit secret_from_env(ROOKHUB_STATS_SECRET)',
          "secret_from_env('ROOKHUB_STATS_SECRET'" in start_src
          and "os.environ.get('ROOKHUB_STATS_SECRET'" not in start_src)
    bot_src = _read('bot.py')
    check('bot.py: WEBHOOK_SECRET ueber secret_from_env',
          re.search(r"^WEBHOOK_SECRET = secret_from_env\('WEBHOOK_SECRET'", bot_src, re.M) is not None)
    for name in ('ROOKHUB_LINK_SECRET', 'ROOKHUB_STATS_SECRET', 'WEBHOOK_SECRET'):
        raw = [f for f in ('bot.py', 'core/discord_link.py', 'puzzle/rookhub.py', 'core/webhook_server.py')
               if re.search(rf"os\.(getenv|environ\.get)\(\s*'{name}'", _read(*f.split('/')))]
        check(f'{name} nirgends ungeprueft aus os.getenv', not raw, f'{raw}')


def test_env_example_placeholders():
    env = dict(re.findall(r'^([A-Z_]+)=(.*)$', _read('.env.example'), re.M))
    link, stats = env.get('ROOKHUB_LINK_SECRET', ''), env.get('ROOKHUB_STATS_SECRET', '')
    check('.env.example: Link- und Stats-Secret haben eigene Platzhalter', link and stats and link != stats,
          f'{link!r} / {stats!r}')
    for name in ('ROOKHUB_LINK_SECRET', 'ROOKHUB_STATS_SECRET', 'WEBHOOK_SECRET'):
        v = env.get(name, '')
        check(f'.env.example: {name} leer oder als Platzhalter erkannt',
              v == '' or secret_env.is_placeholder(v), repr(v))


def main():
    for t in (test_is_placeholder, test_secret_from_env, test_link_secret_placeholder_disables_links,
              test_stats_secret_placeholder_disables_feature, test_all_bot_secrets_use_check,
              test_env_example_placeholders):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle Secret-Platzhalter-Tests bestanden.')


if __name__ == '__main__':
    main()
