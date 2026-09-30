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

# Registrierter Bestand (48). Neuer/entfernter Befehl → Liste bewusst mitpflegen.
EXPECTED_COMMANDS = sorted([
    'announce', 'autor', 'bestenliste', 'bibliothek', 'blind', 'blindpuzzle', 'chat_clear',
    'chat_whitelist', 'daily', 'dm-log', 'elo', 'endless', 'greeted', 'help', 'ignore_kapitel',
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


def test_import_without_token():
    print('[import bot ohne Token, echtes discord.py]')
    env = dict(os.environ)
    env['DISCORD_TOKEN'] = ''  # leer gesetzt: load_dotenv ueberschreibt nichts
    env['BOT_REPO'] = REPO
    for k in ('GUILD_ID', 'CHANNEL_ID', 'DAILY_EXTRA_CHANNEL_IDS', 'ES_URL'):
        env.pop(k, None)
    with tempfile.TemporaryDirectory(prefix='schach_import_') as cwd:  # config/, bot.log landen hier
        proc = subprocess.run([sys.executable, '-c', _PROBE], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=120)
    line = next((l for l in proc.stdout.splitlines() if l.startswith('RESULT ')), None)
    check('import bot ohne DISCORD_TOKEN laeuft durch', proc.returncode == 0 and line is not None,
          (proc.stderr or proc.stdout)[-800:])
    if line is None:
        return
    res = json.loads(line[len('RESULT '):])
    check('import ruft bot.run nicht auf', res['runs'] == 0, str(res['runs']))
    check('bot.main() vorhanden', res['has_main'])
    check('Befehlsliste == erwarteter Bestand', res['names'] == EXPECTED_COMMANDS,
          f"neu: {sorted(set(res['names']) - set(EXPECTED_COMMANDS))}, "
          f"fehlt: {sorted(set(EXPECTED_COMMANDS) - set(res['names']))}")
    valid = {'puzzle', 'bibliothek', 'community', 'info', 'admin', None}
    bad = {n: a for n, a in res['areas'].items() if a not in valid}
    check('jeder Befehl mit gueltigem extras[help]', not bad, str(bad))
    expected_user = sorted(n for n, a in res['areas'].items() if a not in (None, 'admin'))
    check('generierte /help = sichtbare Nicht-Admin-Befehle', res['user_help'] == expected_user,
          str(set(res['user_help']) ^ set(expected_user)))
    no_perm = sorted(n for n, a in res['areas'].items() if a == 'admin' and not res['admin_perm'][n])
    check('Admin-Befehle mit default_permissions(administrator)', not no_perm, str(no_perm))
    print()


if __name__ == '__main__':
    print('=== test_bot_import.py ===\n')
    test_import_without_token()
    print(f'--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
