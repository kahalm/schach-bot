"""
bot.py mit dem ECHTEN discord.py importieren (S4-018, S4-013).

Eigener Prozess ohne die Stubs aus test_helpers: ``import bot`` ohne DISCORD_TOKEN darf weder
abbrechen noch verbinden (``bot.run`` nur in ``main()`` hinter ``__name__ == '__main__'``).
Danach prueft der Test an den echten ``app_commands.Command``-Objekten:
- Befehlsliste == erwarteter Bestand (Netz fuer die weitere Zerlegung von bot.py),
- jeder Befehl traegt ``extras['help']`` mit gueltigem Bereich,
- die generierte /help zeigt genau die sichtbaren Nicht-Admin-Befehle,
- jeder Admin-Befehl hat ``default_permissions(administrator=True)``.

Ausfuehren: python tests/test_bot_import.py
"""

import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Registrierter Bestand ohne CLAUDE_API_KEY (46); mit Key kommen die zwei KI-Chat-Befehle dazu
# (S4-019). Neuer/entfernter Befehl → Liste bewusst mitpflegen.
CHAT_COMMANDS = ['chat_clear', 'chat_whitelist']
EXPECTED_COMMANDS = sorted([
    'announce', 'autor', 'bestenliste', 'bibliothek', 'blind', 'blindpuzzle',
    'daily', 'dm-log', 'elo', 'endless', 'greeted', 'help', 'ignore_kapitel',
    'kurs', 'link', 'log', 'motivation', 'motivation_send', 'next', 'puzzle', 'randompuzzle',
    'reindex', 'release-notes', 'reminder', 'resourcen', 'schachrallye', 'schachrallye_add',
    'schachrallye_del', 'schachrallye_sub', 'schachrallye_unsub', 'stats', 'tag', 'test',
    'train', 'turnier', 'turnier_parse', 'turnier_pending', 'turnier_review', 'turnier_sub',
    'turnier_unsub', 'version', 'wanted', 'wanted_delete', 'wanted_list', 'wanted_vote',
    'youtube',
])

_PROBE = r'''
import json, os, sys
sys.path.insert(0, os.environ['BOT_REPO'])
from discord.ext import commands as _dc
_runs = []
_dc.Bot.run = lambda self, *a, **k: _runs.append(1)  # Netz: falls doch run → nicht verbinden
import bot
from commands import help as H
cmds = H.registered_commands(bot.tree)
user = []
for b in H.BEREICHE:
    user += [sig.split()[0][1:] for sig, _ in H.help_fields(b, None, cmds)[1]]
print('RESULT ' + json.dumps({
    'runs': len(_runs),
    'has_main': callable(getattr(bot, 'main', None)),
    'names': sorted(c.name for c in cmds),
    'areas': {c.name: c.extras.get('help', '<fehlt>') for c in cmds},
    'admin_perm': {c.name: bool(c.default_permissions and c.default_permissions.administrator)
                   for c in cmds},
    'user_help': sorted(user),
}))
'''

# N10-004: main() installiert ueber setup_hook einen SIGTERM-Handler (→ bot.close()) und leert
# nach bot.run die ES-Warteschlange. bot.run wird durch einen Mini-Lauf ersetzt, der wie
# discord.py setup_hook im laufenden Loop aufruft und sich dann selbst SIGTERM schickt; ohne
# Handler beendet der Kernel-Standard den Prozess sofort (Exit -15, kein RESULT).
_SIGTERM_PROBE = r'''
import asyncio, json, os, signal, sys
sys.path.insert(0, os.environ['BOT_REPO'])
import bot
order, closed = [], []

async def _fake_close():
    closed.append(1)

def _fake_run(token, *a, **k):
    async def _sim():
        await bot.bot.setup_hook()
        os.kill(os.getpid(), signal.SIGTERM)
        for _ in range(100):
            if closed:
                break
            await asyncio.sleep(0.02)
    asyncio.run(_sim())
    order.append('run')

bot.bot.close = _fake_close
bot.bot.run = _fake_run
bot.DISCORD_TOKEN = 'probe-token'
bot.dm_log.install = lambda: None
from core import es_client as _es
_es.shutdown = lambda: order.append('es_shutdown')
bot.main()
print('RESULT ' + json.dumps({'closed': len(closed), 'order': order}))
'''

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


def _import_probe(claude_key: str):
    """``import bot`` im eigenen Prozess; liefert (proc, RESULT-Dict oder None)."""
    env = dict(os.environ)
    env['DISCORD_TOKEN'] = ''  # leer gesetzt: load_dotenv ueberschreibt nichts
    env['CLAUDE_API_KEY'] = claude_key  # ebenso: KI-Chat an/aus unabhaengig von der Umgebung
    env['BOT_REPO'] = REPO
    for k in ('GUILD_ID', 'CHANNEL_ID', 'DAILY_EXTRA_CHANNEL_IDS', 'ES_URL'):
        env.pop(k, None)
    with tempfile.TemporaryDirectory(prefix='schach_import_') as cwd:  # config/, bot.log landen hier
        proc = subprocess.run([sys.executable, '-c', _PROBE], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=120)
    line = next((l for l in proc.stdout.splitlines() if l.startswith('RESULT ')), None)
    return proc, (json.loads(line[len('RESULT '):]) if line else None)


def _check_names(label, names, expected):
    check(label, names == expected,
          f"neu: {sorted(set(names) - set(expected))}, "
          f"fehlt: {sorted(set(expected) - set(names))}")


def test_import_without_token():
    print('[import bot ohne Token, echtes discord.py]')
    proc, res = _import_probe('')
    check('import bot ohne DISCORD_TOKEN laeuft durch', proc.returncode == 0 and res is not None,
          (proc.stderr or proc.stdout)[-800:])
    if res is None:
        return
    check('import ruft bot.run nicht auf', res['runs'] == 0, str(res['runs']))
    check('bot.main() vorhanden', res['has_main'])
    _check_names('Befehlsliste == erwarteter Bestand (ohne CLAUDE_API_KEY, KI-Chat aus)',
                 res['names'], EXPECTED_COMMANDS)

    # Mit Key registriert der KI-Chat seine zwei Befehle (Client wird nur gebaut, kein Netz);
    # die Pruefungen unten laufen auf diesem vollen Bestand.
    proc, res = _import_probe('probe-key')
    check('import bot mit CLAUDE_API_KEY laeuft durch', proc.returncode == 0 and res is not None,
          (proc.stderr or proc.stdout)[-800:])
    if res is None:
        return
    _check_names('mit CLAUDE_API_KEY: Bestand + /chat_clear, /chat_whitelist',
                 res['names'], sorted(EXPECTED_COMMANDS + CHAT_COMMANDS))
    valid = {'puzzle', 'bibliothek', 'community', 'info', 'admin', None}
    bad = {n: a for n, a in res['areas'].items() if a not in valid}
    check('jeder Befehl mit gueltigem extras[help]', not bad, str(bad))
    expected_user = sorted(n for n, a in res['areas'].items() if a not in (None, 'admin'))
    check('generierte /help = sichtbare Nicht-Admin-Befehle', res['user_help'] == expected_user,
          str(set(res['user_help']) ^ set(expected_user)))
    no_perm = sorted(n for n, a in res['areas'].items() if a == 'admin' and not res['admin_perm'][n])
    check('Admin-Befehle mit default_permissions(administrator)', not no_perm, str(no_perm))
    print()


def test_sigterm_closes_bot():
    print('[SIGTERM → bot.close(), danach ES-Flush (N10-004)]')
    env = dict(os.environ)
    env['DISCORD_TOKEN'] = ''
    env['BOT_REPO'] = REPO
    for k in ('GUILD_ID', 'CHANNEL_ID', 'DAILY_EXTRA_CHANNEL_IDS', 'ES_URL'):
        env.pop(k, None)
    with tempfile.TemporaryDirectory(prefix='schach_sigterm_') as cwd:
        proc = subprocess.run([sys.executable, '-c', _SIGTERM_PROBE], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=120)
    line = next((l for l in proc.stdout.splitlines() if l.startswith('RESULT ')), None)
    check('SIGTERM beendet den Prozess nicht hart', proc.returncode == 0 and line is not None,
          f'rc={proc.returncode} ' + (proc.stderr or proc.stdout)[-600:])
    if line is None:
        return
    res = json.loads(line[len('RESULT '):])
    check('SIGTERM ruft bot.close() auf', res['closed'] == 1, str(res))
    check('ES-Warteschlange nach bot.run geleert', res['order'] == ['run', 'es_shutdown'], str(res))
    print()


if __name__ == '__main__':
    print('=== test_bot_import.py ===\n')
    test_import_without_token()
    test_sigterm_closes_bot()
    print(f'--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
