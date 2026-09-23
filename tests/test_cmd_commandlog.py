"""Tests fuer das Befehls-Protokoll (core/command_log.py + Listener in bot.py)."""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from test_helpers import bot_mod, check, run_async, FakeUser


class _Capture(logging.Handler):
    """Sammelt die Records des 'schach-bot'-Loggers."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


class _Namespace:
    """Wie discord.app_commands.Namespace: iterierbar als (name, wert)-Paare."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __iter__(self):
        yield from self.__dict__.items()


class _Guild:
    def __init__(self, gid=111, name='Schachclub'):
        self.id = gid
        self.name = name


class _Channel:
    def __init__(self, name='puzzles'):
        self.name = name


class _Cmd:
    def __init__(self, qualified_name):
        self.qualified_name = qualified_name
        self.name = qualified_name.split()[-1]


def _interaction(guild=True, **options):
    ia = MagicMock()
    ia.user = FakeUser(uid=728550010496745472, name='kahalm')
    ia.guild = _Guild() if guild else None
    ia.guild_id = 111 if guild else None
    ia.channel = _Channel() if guild else None
    ia.channel_id = 222
    ia.namespace = _Namespace(**options)
    ia.created_at = datetime.now(timezone.utc) - timedelta(milliseconds=250)
    ia.command = _Cmd('elo')
    return ia


def _capture():
    log = logging.getLogger('schach-bot')
    cap = _Capture()
    log.addHandler(cap)
    return log, cap


def test_command_log():
    print('[Befehls-Log]')
    from core import command_log

    # 1) build_entry: Nachricht + Felder fuer einen Guild-Befehl mit Parametern
    msg, f = command_log.build_entry(
        command='elo', user_id=728550010496745472, user_name='kahalm',
        guild_id=111, guild_name='Schachclub', channel_id=222, channel_name='puzzles',
        options={'wert': 1650, 'leer': None}, outcome='ok', duration_ms=250)
    check('Nachricht nennt Befehl', '/elo' in msg, msg)
    check('Nachricht nennt Nutzer', 'kahalm' in msg and '728550010496745472' in msg, msg)
    check('Nachricht nennt Server', 'Schachclub' in msg, msg)
    check('Parameter in Nachricht', 'wert=1650' in msg, msg)
    check('None-Parameter fallen weg', 'leer' not in msg and 'leer' not in f.get('options', ''), msg)
    check('tags=[command]', f.get('tags') == ['command'], str(f))
    check('command-Feld', f.get('command') == 'elo')
    check('user_id als String (Snowflake > 2^53)', f.get('user_id') == '728550010496745472')
    check('user_name', f.get('user_name') == 'kahalm')
    check('guild_id als String', f.get('guild_id') == '111')
    check('channel_name', f.get('channel_name') == 'puzzles')
    check('options als ein String', f.get('options') == 'wert=1650', str(f.get('options')))
    check('outcome ok', f.get('outcome') == 'ok')
    check('duration_ms', f.get('duration_ms') == 250)
    check('ok ohne Pfeil in Nachricht', '→' not in msg, msg)

    # 2) DM: kein Server, Ort = DM, keine guild-Felder
    msg, f = command_log.build_entry(
        command='motivation', user_id=5, user_name='x', guild_id=None, guild_name=None,
        channel_id=9, channel_name=None, options={}, outcome='ok')
    check('DM in Nachricht', 'in DM' in msg, msg)
    check('DM: kein guild_id', 'guild_id' not in f, str(f))
    check('DM: location=dm', f.get('location') == 'dm', str(f))

    # 3) Lange Werte werden gekuerzt, Objekte mit id/name lesbar
    long_text = 'a' * 500
    member = FakeUser(uid=42, name='Gegner')
    _, f = command_log.build_entry(
        command='chat', user_id=1, user_name='u', guild_id=1, guild_name='g',
        channel_id=1, channel_name='c', options={'text': long_text, 'spieler': member},
        outcome='ok')
    opts = f.get('options', '')
    check('langer Wert gekuerzt', 'a' * 101 not in opts and '…' in opts, opts[:80])
    check('Objekt als name (id)', 'spieler=Gegner (42)' in opts, opts[-40:])

    # 4) Fehler-Ausgang steht in Nachricht + Feldern
    msg, f = command_log.build_entry(
        command='daily', user_id=1, user_name='u', guild_id=1, guild_name='g',
        channel_id=1, channel_name='c', options={}, outcome='denied', error='MissingPermissions')
    check('denied in Nachricht', '→ denied' in msg and 'MissingPermissions' in msg, msg)
    check('error-Feld', f.get('error') == 'MissingPermissions')

    # 5) outcome_for: Einordnung ueber die Klassennamen (auch Unterklassen)
    class CheckFailure(Exception):
        pass

    class CommandOnCooldown(CheckFailure):
        pass

    class MissingPermissions(CheckFailure):
        pass

    check('Cooldown → cooldown', command_log.outcome_for(CommandOnCooldown()) == 'cooldown')
    check('CheckFailure-Unterklasse → denied', command_log.outcome_for(MissingPermissions()) == 'denied')
    check('sonstiger Fehler → error', command_log.outcome_for(ValueError()) == 'error')

    # 6) log_command mit Interaction: ein Info-Record mit es_fields
    log, cap = _capture()
    try:
        ia = _interaction(wert=1650)
        command_log.log_command(ia, _Cmd('turnier sub'))
        recs = [r for r in cap.records if getattr(r, 'es_fields', {}).get('tags') == ['command']]
        check('genau ein Befehls-Record', len(recs) == 1, str(len(recs)))
        if recs:
            r = recs[0]
            check('Level INFO', r.levelno == logging.INFO)
            check('Unterbefehl mit vollem Namen', r.es_fields.get('command') == 'turnier sub')
            check('Parameter aus namespace', r.es_fields.get('options') == 'wert=1650')
            check('Dauer aus created_at', 150 <= r.es_fields.get('duration_ms', -1) <= 5000,
                  str(r.es_fields.get('duration_ms')))
            check('Server aus interaction.guild', r.es_fields.get('guild_name') == 'Schachclub')

        # 7) Ohne command-Argument: interaction.command
        cap.records.clear()
        command_log.log_command(_interaction(guild=False), outcome='cooldown', error='CommandOnCooldown')
        recs = [r for r in cap.records if getattr(r, 'es_fields', {}).get('tags') == ['command']]
        check('Fallback interaction.command', recs and recs[0].es_fields.get('command') == 'elo')
        check('DM-Interaction → location dm', recs and recs[0].es_fields.get('location') == 'dm')

        # 8) Kaputte Interaction darf nie werfen (Logging darf keinen Befehl stoeren)
        cap.records.clear()
        broken = MagicMock()
        type(broken).user = property(lambda self: (_ for _ in ()).throw(RuntimeError('kaputt')))
        try:
            command_log.log_command(broken, _Cmd('elo'))
            check('kaputte Interaction wirft nicht', True)
        except Exception as e:  # pragma: no cover
            check('kaputte Interaction wirft nicht', False, repr(e))

        # 9) Listener in bot.py loggt erfolgreiche Befehle
        cap.records.clear()
        listener = getattr(bot_mod, '_log_app_command', None)
        check('bot._log_app_command existiert', listener is not None)
        if listener is not None:
            run_async(listener(_interaction(), _Cmd('puzzle')))
            recs = [r for r in cap.records if getattr(r, 'es_fields', {}).get('tags') == ['command']]
            check('Listener → Befehls-Record', recs and recs[0].es_fields.get('command') == 'puzzle')
    finally:
        log.removeHandler(cap)

    # 10) End-to-end bis ins ES-Dokument: labels + tags
    from core import es_client
    from core.log_setup import _ESHandler
    orig_url = es_client._ES_URL
    es_client._ES_URL = 'http://test.invalid:9200'
    es_client._worker_started = True
    try:
        while not es_client._queue.empty():
            es_client._queue.get_nowait()
        handler = _ESHandler()
        handler.setFormatter(logging.Formatter('%(message)s'))
        log = logging.getLogger('schach-bot')
        log.addHandler(handler)
        try:
            command_log.log_command(_interaction(wert=1), _Cmd('elo'))
        finally:
            log.removeHandler(handler)
        docs = []
        while not es_client._queue.empty():
            docs.append(es_client._queue.get_nowait()[1])
        docs = [d for d in docs if d.get('tags') == ['command']]
        check('ES-Dokument mit tags=[command]', len(docs) == 1, str(len(docs)))
        if docs:
            labels = docs[0].get('labels', {})
            check('labels.command', labels.get('command') == 'elo', str(labels))
            check('labels.user_id', labels.get('user_id') == '728550010496745472')
    finally:
        es_client._ES_URL = orig_url
        es_client._worker_started = False
        while not es_client._queue.empty():
            es_client._queue.get_nowait()

    print()
