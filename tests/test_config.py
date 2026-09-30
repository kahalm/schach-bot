"""
Unit-Tests fuer core/config.py (Env-Parsing als Funktion, S4-018).

Standalone-Script, nur stdlib (kein Discord-Mocking noetig).

Ausfuehren: python tests/test_config.py
"""

import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

from core import config

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


def _exit_msg(env):
    try:
        config.load(env)
    except SystemExit as e:
        return str(e)
    return None


def test_defaults():
    cfg = config.load({})
    check('leere Umgebung → kein Abbruch (Token prueft erst main)', cfg.discord_token == '')
    check('Defaults: keine Daily-Channels', cfg.daily_channel_ids == [] and cfg.daily_channel_lang == {})
    check('Defaults: Post-Zeit 9:00', (cfg.puzzle_hour, cfg.puzzle_minute) == (9, 0))
    check('Defaults: Webhook 0.0.0.0:9000 ohne Secret',
          (cfg.webhook_bind_host, cfg.webhook_port, cfg.webhook_secret) == ('0.0.0.0', 9000, ''))
    check('Defaults: GUILD_ID 0, Sprache de', cfg.guild_id == 0 and cfg.daily_default_lang == 'de')


def test_values():
    cfg = config.load({
        'DISCORD_TOKEN': 'tok', 'CHANNEL_ID': '111', 'DAILY_DEFAULT_LANG': 'DE',
        'DAILY_EXTRA_CHANNEL_IDS': ' 222:en, 333 ,0,111:en,', 'GUILD_ID': '42',
        'RALLYE_CHANNEL_ID': '77', 'WOCHENPOST_CHANNEL_ID': '88', 'PUZZLE_HOUR': '7',
        'PUZZLE_MINUTE': '30', 'WEBHOOK_PORT': '9100', 'WEBHOOK_SECRET': 'geheim',
        'ROOKHUB_WEB_URL': 'https://rookhub.test/'})
    check('Token', cfg.discord_token == 'tok')
    check('Daily-Channels: Haupt + Extra, ohne 0 und Duplikat', cfg.daily_channel_ids == [111, 222, 333],
          str(cfg.daily_channel_ids))
    check('Sprache je Channel (Extra-Eintrag ueberschreibt)',
          cfg.daily_channel_lang == {111: 'en', 222: 'en', 333: 'de'}, str(cfg.daily_channel_lang))
    check('RALLYE_CHANNEL_ID als Fallback fuer TOURNAMENT_CHANNEL_ID', cfg.tournament_channel_id == 77)
    check('Zahlen', (cfg.guild_id, cfg.wochenpost_channel_id, cfg.puzzle_hour, cfg.puzzle_minute,
                     cfg.webhook_port) == (42, 88, 7, 30, 9100))
    check('Secret + Web-URL ohne Slash', cfg.webhook_secret == 'geheim'
          and cfg.rookhub_web_url == 'https://rookhub.test')
    check('Platzhalter-Secret zaehlt wie leer',
          config.load({'WEBHOOK_SECRET': 'change_me_webhook'}).webhook_secret == '')


def test_invalid():
    # Meldungen byte-gleich wie vorher in bot.py
    check('CHANNEL_ID ungueltig', _exit_msg({'CHANNEL_ID': 'abc'})
          == "CHANNEL_ID ungültig: 'abc' — muss eine Zahl sein")
    check('GUILD_ID ungueltig', _exit_msg({'GUILD_ID': 'x'}) == "GUILD_ID ungültig: 'x' — muss eine Zahl sein")
    check('TOURNAMENT_CHANNEL_ID ungueltig', _exit_msg({'TOURNAMENT_CHANNEL_ID': 't'})
          == "TOURNAMENT_CHANNEL_ID ungültig: 't' — muss eine Zahl sein")
    check('WEBHOOK_PORT ungueltig', _exit_msg({'WEBHOOK_PORT': 'p'})
          == "WEBHOOK_PORT ungültig: 'p' — muss eine Zahl sein")
    check('DAILY_EXTRA_CHANNEL_IDS ungueltig',
          (_exit_msg({'DAILY_EXTRA_CHANNEL_IDS': '1,zwei:en'}) or '').startswith(
              "DAILY_EXTRA_CHANNEL_IDS enthält ungültige ID: 'zwei'"))
    check('PUZZLE_HOUR keine Zahl', _exit_msg({'PUZZLE_HOUR': 'neun'})
          == "PUZZLE_HOUR/PUZZLE_MINUTE ungültig: 'neun'/None — müssen Zahlen sein")
    check('PUZZLE_HOUR ausserhalb', _exit_msg({'PUZZLE_HOUR': '24'})
          == 'PUZZLE_HOUR/PUZZLE_MINUTE ungültig: 24:0')


if __name__ == '__main__':
    print('=== test_config.py ===\n')
    test_defaults()
    test_values()
    test_invalid()
    print(f'\n--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
