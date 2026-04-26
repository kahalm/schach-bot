"""
Slash-Command-Tests fuer alle Bot-Befehle.

Standalone-Script wie test_trim.py. Discord und alle Heavy-Deps werden
vor dem Import gemockt. Jeder Test benutzt ein eigenes temp-Verzeichnis
fuer JSON-State-Dateien.

Ausfuehren: python tests/test_commands.py
"""

import sys
import os
import json
import asyncio
import inspect
import tempfile
import shutil
import unittest.mock as _mock
from unittest.mock import MagicMock, AsyncMock
import logging
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# 0) Pfad-Setup
# ---------------------------------------------------------------------------

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# ---------------------------------------------------------------------------
# 1) Passthrough-Decorator: gibt die dekorierte Funktion unveraendert zurueck
# ---------------------------------------------------------------------------

def _passthrough_decorator(**kwargs):
    """Decorator-Factory die die Funktion unveraendert zurueckgibt."""
    def deco(func):
        return func
    return deco

def _passthrough_single(func):
    """Einfacher Decorator der die Funktion zurueckgibt."""
    return func


# ---------------------------------------------------------------------------
# 2) sys.modules stubben
# ---------------------------------------------------------------------------

for mod_name in (
    'discord', 'discord.ext', 'discord.ext.tasks', 'discord.ext.commands',
    'discord.ui', 'discord.app_commands',
    'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',
    'PIL.ImageChops', 'PIL.ImageOps',
    'svglib', 'svglib.svglib',
    'reportlab', 'reportlab.graphics', 'reportlab.graphics.renderPM',
    'requests',
    'dotenv',
):
    sys.modules.setdefault(mod_name, _mock.MagicMock())

# discord.Embed: minimale Implementierung
_discord = sys.modules['discord']

class FakeEmbed:
    def __init__(self, **kw):
        self.title = kw.get('title', '')
        self.description = kw.get('description', '')
        self.color = kw.get('color', kw.get('colour', 0))
        self.colour = self.color
        self.fields = []
        self._footer = {}
        self._image = None

    def add_field(self, **kw):
        self.fields.append(kw)

    def set_footer(self, **kw):
        self._footer = kw

    def set_image(self, **kw):
        self._image = kw


_discord.Embed = FakeEmbed
_discord.Color = MagicMock()
_discord.Color.blue = MagicMock(return_value=0x3498db)
_discord.File = MagicMock
_discord.Forbidden = type('Forbidden', (Exception,), {})
_discord.Member = type('Member', (), {})
_discord.User = type('User', (), {})
_discord.DMChannel = type('DMChannel', (), {'send': MagicMock()})
_discord.Message = type('Message', (), {})
_discord.Interaction = type('Interaction', (), {})
_discord.ButtonStyle = MagicMock()
_discord.SelectOption = MagicMock
_discord.Intents.default.return_value = MagicMock()

# app_commands: alle Decorators als passthrough
_app_commands = sys.modules['discord.app_commands']
_app_commands.describe = _passthrough_decorator
_app_commands.default_permissions = _passthrough_decorator
_app_commands.choices = _passthrough_decorator
_app_commands.Choice = MagicMock
# Muss auch auf discord.app_commands gesetzt werden
_discord.app_commands = _app_commands

# discord.ui
_ui = sys.modules['discord.ui']

class FakeView:
    def __init__(self, **kw):
        pass
    def add_item(self, item):
        pass

class FakeSelect(FakeView):
    pass

_ui.View = FakeView
_ui.Select = FakeSelect
_ui.Button = MagicMock
_ui.button = lambda **kw: _passthrough_single

# discord.ext.commands
_commands_mod = sys.modules['discord.ext.commands']

# discord.ext.tasks
_tasks_mod = sys.modules['discord.ext.tasks']
def _fake_tasks_loop(**kwargs):
    def deco(func):
        func.start = lambda: None
        func.is_running = lambda: False
        return func
    return deco
_tasks_mod.loop = _fake_tasks_loop

# dotenv
sys.modules['dotenv'].load_dotenv = lambda: None

# Submodul-Referenzen korrekt verknuepfen:
# `from discord.ext import commands` nutzt getattr(discord.ext, 'commands'),
# also muss discord.ext.commands auf unser Mock-Modul zeigen.
_discord_ext = sys.modules['discord.ext']
_discord_ext.commands = _commands_mod
_discord_ext.tasks = _tasks_mod

# Env-Variablen fuer bot.py
os.environ.setdefault('DISCORD_TOKEN', 'fake-token-for-tests')
os.environ.setdefault('CHANNEL_ID', '99999')


# ---------------------------------------------------------------------------
# 3) Capturing-Bot: faengt alle tree.command()-Registrierungen ab
# ---------------------------------------------------------------------------

_captured_commands = {}


class _CapturingTree:
    """tree.command(name=...) speichert die async function."""

    def command(self, **kwargs):
        cmd_name = kwargs.get('name', '')
        def decorator(func):
            _captured_commands[cmd_name] = func
            func.autocomplete = lambda name: _passthrough_single
            return func
        return decorator

    def __getattr__(self, name):
        return MagicMock()


class _CapturingBot:
    """Ersatz-Bot der Commands captured statt zu registrieren."""

    def __init__(self, **kwargs):
        self.tree = _CapturingTree()
        self._listeners = {}

    def event(self, func):
        return func

    def listen(self, event_name):
        return lambda f: f

    def run(self, *args, **kwargs):
        pass

    def add_view(self, v):
        pass

    def get_channel(self, cid):
        return FakeChannel(channel_id=cid) if cid else None

    async def fetch_user(self, uid):
        return FakeUser(uid=uid, name=f'User_{uid}')

    @property
    def guilds(self):
        return []

    @property
    def user(self):
        return FakeUser(uid=1, name='Bot')


# ---------------------------------------------------------------------------
# 4) Fake-Klassen fuer Interactions etc.
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self):
        self.calls = []

    async def send_message(self, content=None, **kwargs):
        self.calls.append({'type': 'send_message', 'content': content, **kwargs})

    async def defer(self, **kwargs):
        self.calls.append({'type': 'defer', **kwargs})

    async def edit_message(self, **kwargs):
        self.calls.append({'type': 'edit_message', **kwargs})


class FakeFollowup:
    def __init__(self):
        self.calls = []

    async def send(self, content=None, **kwargs):
        self.calls.append({'type': 'send', 'content': content, **kwargs})


class FakePermissions:
    def __init__(self, administrator=False):
        self.administrator = administrator


class FakeUser:
    def __init__(self, uid=12345, name='TestUser', admin=False):
        self.id = uid
        self.display_name = name
        self.name = name
        self.mention = f'<@{uid}>'
        self.guild_permissions = FakePermissions(administrator=admin)
        self.bot = False

    async def create_dm(self):
        return FakeChannel()


class FakeMember(FakeUser):
    pass


class _FakeGuild:
    """Fake-Guild fuer _display_name: liefert FakeUser per get_member/fetch_member."""

    def get_member(self, uid):
        return FakeUser(uid=uid, name=f'User_{uid}')

    async def fetch_member(self, uid):
        return FakeUser(uid=uid, name=f'User_{uid}')


class FakeChannel:
    def __init__(self, channel_id=99999):
        self.id = channel_id
        self.sent = []

    async def send(self, content=None, **kwargs):
        msg = FakeMessage(content=content, **kwargs)
        self.sent.append(msg)
        return msg


class FakeMessage:
    _counter = 0

    def __init__(self, content=None, **kwargs):
        FakeMessage._counter += 1
        self.id = FakeMessage._counter
        self.content = content
        self.kwargs = kwargs

    async def edit(self, **kwargs):
        pass


def make_interaction(user=None, admin=False):
    """Erstellt eine FakeInteraction."""
    if user is None:
        user = FakeMember(admin=admin)
    ia = MagicMock()
    ia.user = user
    ia.response = FakeResponse()
    ia.followup = FakeFollowup()
    ia.client = _CapturingBot()
    ia.guild = _FakeGuild()
    return ia


# ---------------------------------------------------------------------------
# 5) Temp-CONFIG_DIR pro Test
# ---------------------------------------------------------------------------

_original_config_dir = None


def setup_temp_config():
    global _original_config_dir
    tmpdir = tempfile.mkdtemp(prefix='schach_test_')

    import core.paths
    _original_config_dir = core.paths.CONFIG_DIR
    core.paths.CONFIG_DIR = tmpdir

    _patch_file_constant('commands.elo', 'ELO_FILE', tmpdir)
    # resourcen/youtube nutzen jetzt _collection._json_path() mit CONFIG_DIR zur Laufzeit
    _patch_file_constant('commands.wanted', 'WANTED_FILE', tmpdir)
    _patch_file_constant('commands.reminder', 'REMINDER_FILE', tmpdir)
    _patch_file_constant('commands.schachrallye', 'TURNIER_FILE', tmpdir)
    _patch_file_constant('core.stats', 'STATS_FILE', tmpdir)

    return tmpdir


def _patch_file_constant(module_path, attr_name, tmpdir):
    mod = sys.modules.get(module_path)
    if mod is None:
        __import__(module_path)
        mod = sys.modules[module_path]
    old = getattr(mod, attr_name, '')
    basename = os.path.basename(old) if old else attr_name.lower() + '.json'
    setattr(mod, attr_name, os.path.join(tmpdir, basename))


def teardown_temp_config(tmpdir):
    global _original_config_dir
    if _original_config_dir is not None:
        import core.paths
        core.paths.CONFIG_DIR = _original_config_dir
        _original_config_dir = None
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 6) Test-Runner
# ---------------------------------------------------------------------------

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


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 7) Module importieren (NACH dem Mocking!)
# ---------------------------------------------------------------------------

# commands.Bot patchen BEVOR bot.py importiert wird
_commands_mod.Bot = _CapturingBot
_commands_mod.when_mentioned = 'when_mentioned'

import core.paths
import core.version
from core.json_store import atomic_read, atomic_write

# Command-Module importieren — setup() wird spaeter aufgerufen
import commands.elo as elo_mod
import commands.resourcen as resourcen_mod
import commands.youtube as youtube_mod
import commands.wanted as wanted_mod
import commands.release_notes as release_notes_mod
import commands.reminder as reminder_mod
import commands.schachrallye as schachrallye_mod

# bot.py importieren (ruft am Ende bot.run() auf, was jetzt ein no-op ist)
import bot as bot_mod

# setup() fuer alle Command-Module nochmal ausfuehren, damit die Commands
# im _captured_commands Dict landen (bot.py hat sie schon mit dem
# _CapturingTree registriert)
_cap_bot = _CapturingBot()
for mod in (elo_mod, resourcen_mod, youtube_mod, wanted_mod,
            release_notes_mod, reminder_mod, schachrallye_mod):
    if mod is schachrallye_mod:
        mod.setup(_cap_bot, tournament_channel_id=0)
    else:
        mod.setup(_cap_bot)

# bot.py-interne Helper merken
_help_fields_fn = bot_mod._help_fields


# ===================================================================
# TESTS
# ===================================================================


def test_help():
    """Tests fuer /help Command."""
    print('[/help]')
    tmpdir = setup_temp_config()
    try:
        # Test: Uebersicht (kein Bereich)
        title, fields = _help_fields_fn('', False)
        check('kein Bereich → leerer Titel', title == '')
        check('kein Bereich → keine Felder', fields == [])

        # Test: Bereich puzzle
        title, fields = _help_fields_fn('puzzle', False)
        check('Bereich puzzle → Titel', 'Puzzles' in title)
        check('Bereich puzzle → hat Felder', len(fields) > 0)

        # Test: Bereich bibliothek
        title, fields = _help_fields_fn('bibliothek', False)
        check('Bereich bibliothek → Titel', 'Bibliothek' in title)

        # Test: Bereich community
        title, fields = _help_fields_fn('community', False)
        check('Bereich community → Titel', 'Community' in title)

        # Test: Bereich info
        title, fields = _help_fields_fn('info', False)
        check('Bereich info → Titel', 'Info' in title)

        # Test: unbekannter Bereich
        title, fields = _help_fields_fn('nonsense', False)
        check('unbekannter Bereich → leer', title == '' and fields == [])

        # Test: Admin-Bereich ohne Admin
        title, fields = _help_fields_fn('admin', False)
        check('admin ohne Admin → leer', title == '' and fields == [])

        # Test: Admin-Bereich mit Admin
        title, fields = _help_fields_fn('admin', True)
        check('admin mit Admin → Titel', 'Admin' in title)
        check('admin mit Admin → hat Felder', len(fields) > 0)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_version():
    """Tests fuer /version Command."""
    print('[/version]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('version')
        check('cmd_version gefunden', cmd is not None)
        if not cmd:
            return

        ia = make_interaction()
        run_async(cmd(ia))

        check('send_message aufgerufen', len(ia.response.calls) == 1)
        call = ia.response.calls[0]
        check('enthaelt Version',
              core.version.VERSION in (call.get('content') or ''))
        check('ephemeral', call.get('ephemeral') is True)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_elo():
    """Tests fuer /elo Command."""
    print('[/elo]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('elo')
        check('cmd_elo gefunden', cmd is not None)
        if not cmd:
            return

        # Test: ohne Wert, keine Historie
        ia = make_interaction()
        run_async(cmd(ia, wert=None))
        check('keine Elo → Hinweis',
              'noch keine elo' in (ia.response.calls[0].get('content') or '').lower())

        # Test: Wert setzen
        ia = make_interaction()
        run_async(cmd(ia, wert=1500))
        check('Elo setzen → Bestaetigung',
              '1500' in (ia.response.calls[0].get('content') or ''))

        # Test: Wert anzeigen (nach setzen)
        ia = make_interaction()
        run_async(cmd(ia, wert=None))
        check('Elo anzeigen → aktuelle Elo',
              '1500' in (ia.response.calls[0].get('content') or ''))

        # Test: Historie (zweiten Wert setzen)
        ia = make_interaction()
        run_async(cmd(ia, wert=1600))
        ia = make_interaction()
        run_async(cmd(ia, wert=None))
        check('Elo Historie → zeigt Historie',
              'Historie' in (ia.response.calls[0].get('content') or ''))

        # Test: Validierung < 100
        ia = make_interaction()
        run_async(cmd(ia, wert=50))
        check('Elo < 100 → Fehler',
              '100' in (ia.response.calls[0].get('content') or '') and
              '3500' in (ia.response.calls[0].get('content') or ''))

        # Test: Validierung > 3500
        ia = make_interaction()
        run_async(cmd(ia, wert=4000))
        check('Elo > 3500 → Fehler',
              '100' in (ia.response.calls[0].get('content') or '') and
              '3500' in (ia.response.calls[0].get('content') or ''))
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_resourcen():
    """Tests fuer /resourcen Command."""
    print('[/resourcen]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('resourcen')
        check('cmd_resourcen gefunden', cmd is not None)
        if not cmd:
            return

        # Test: Liste leer
        ia = make_interaction()
        run_async(cmd(ia, url=None, beschreibung=None))
        check('leere Liste → Hinweis',
              'keine Ressourcen' in (ia.response.calls[0].get('content') or '').lower()
              or 'keine ressourcen' in (ia.response.calls[0].get('content') or '').lower())

        # Test: hinzufuegen ohne Beschreibung
        ia = make_interaction()
        run_async(cmd(ia, url='https://example.com', beschreibung=None))
        check('ohne Beschreibung → Warnung',
              'beschreibung' in (ia.response.calls[0].get('content') or '').lower())

        # Test: hinzufuegen mit Beschreibung
        ia = make_interaction()
        run_async(cmd(ia, url='https://example.com', beschreibung='Test-Ressource'))
        check('hinzufuegen → Bestaetigung',
              'Test-Ressource' in (ia.response.calls[0].get('content') or ''))

        # Test: Liste mit Eintrag
        ia = make_interaction()
        run_async(cmd(ia, url=None, beschreibung=None))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('Liste → Embed mit Eintrag',
              embed is not None and len(embed.fields) > 0)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_youtube():
    """Tests fuer /youtube Command."""
    print('[/youtube]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('youtube')
        check('cmd_youtube gefunden', cmd is not None)
        if not cmd:
            return

        # Test: Liste leer
        ia = make_interaction()
        run_async(cmd(ia, url=None, beschreibung=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('leere Liste → Hinweis',
              'keine youtube' in content or 'keine youtube-links' in content)

        # Test: hinzufuegen ohne Beschreibung
        ia = make_interaction()
        run_async(cmd(ia, url='https://youtube.com/test', beschreibung=None))
        check('ohne Beschreibung → Warnung',
              'beschreibung' in (ia.response.calls[0].get('content') or '').lower())

        # Test: hinzufuegen mit Beschreibung
        ia = make_interaction()
        run_async(cmd(ia, url='https://youtube.com/test', beschreibung='Test-Kanal'))
        check('hinzufuegen → Bestaetigung',
              'Test-Kanal' in (ia.response.calls[0].get('content') or ''))

        # Test: Liste mit Eintrag
        ia = make_interaction()
        run_async(cmd(ia, url=None, beschreibung=None))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('Liste → Embed mit Eintrag',
              embed is not None and len(embed.fields) > 0)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_reminder():
    """Tests fuer /reminder Command."""
    print('[/reminder]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('reminder')
        check('cmd_reminder gefunden', cmd is not None)
        if not cmd:
            return

        # Test: Status ohne Reminder
        ia = make_interaction()
        run_async(cmd(ia, hours=None, puzzle_count=1, buch=0))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('kein Reminder → Hinweis',
              'keinen aktiven reminder' in content or 'kein' in content)

        # Test: Reminder aktivieren
        ia = make_interaction()
        run_async(cmd(ia, hours=4, puzzle_count=3, buch=0))
        content = ia.response.calls[0].get('content') or ''
        check('aktivieren → Bestaetigung', '4' in content and '3' in content)

        # Test: Status mit Reminder
        ia = make_interaction()
        run_async(cmd(ia, hours=None, puzzle_count=1, buch=0))
        content = ia.response.calls[0].get('content') or ''
        check('Status → zeigt Details', '4' in content)

        # Test: Reminder stoppen
        ia = make_interaction()
        run_async(cmd(ia, hours=0, puzzle_count=1, buch=0))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('stoppen → Bestaetigung', 'gestoppt' in content)

        # Test: Validierung hours
        ia = make_interaction()
        run_async(cmd(ia, hours=200, puzzle_count=1, buch=0))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('hours > 168 → Fehler', '168' in content)

        # Test: Validierung puzzle_count
        ia = make_interaction()
        run_async(cmd(ia, hours=4, puzzle_count=25, buch=0))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('puzzle_count > 20 → Fehler', '20' in content)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_announce():
    """Tests fuer /announce Command."""
    print('[/announce]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('announce')
        check('cmd_announce gefunden', cmd is not None)
        if not cmd:
            return

        # Test: Erfolg
        target = FakeUser(uid=54321, name='Empfaenger')
        ia = make_interaction(admin=True)
        run_async(cmd(ia, user=target))
        content = ia.response.calls[0].get('content') or ''
        check('Erfolg → Bestaetigung',
              'Empfaenger' in content and '✅' in content)

        # Test: Forbidden
        class ForbiddenUser:
            id = 99
            display_name = 'Gesperrt'
            name = 'Gesperrt'
            mention = '<@99>'
            bot = False
            async def create_dm(self):
                raise _discord.Forbidden(MagicMock(), 'DMs disabled')

        ia = make_interaction(admin=True)
        run_async(cmd(ia, user=ForbiddenUser()))
        content = ia.response.calls[0].get('content') or ''
        check('Forbidden → Fehlermeldung', '❌' in content)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_greeted():
    """Tests fuer /greeted Command."""
    print('[/greeted]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('greeted')
        check('cmd_greeted gefunden', cmd is not None)
        if not cmd:
            return

        # DM_STATE_FILE patchen
        import bot as bot_mod
        old_dm_state = bot_mod.DM_STATE_FILE
        bot_mod.DM_STATE_FILE = os.path.join(tmpdir, 'dm_state.json')

        # bot-Variable in bot_mod patchen (greeted nutzt bot.fetch_user)
        old_bot = bot_mod.bot
        bot_mod.bot = _CapturingBot()

        try:
            # Test: leer
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('leer → Hinweis', 'niemand' in content)

            # Test: mit Eintraegen
            atomic_write(bot_mod.DM_STATE_FILE,
                         {'greeted': [12345, 67890]})
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            # greeted defers, dann followup.send
            check('defer aufgerufen',
                  ia.response.calls[0].get('type') == 'defer')
            check('followup.send aufgerufen', len(ia.followup.calls) > 0)
            if ia.followup.calls:
                embeds = ia.followup.calls[0].get('embeds', [])
                embed = ia.followup.calls[0].get('embed') or (embeds[0] if embeds else None)
                check('mit Eintraegen → Embed',
                      embed is not None and '2' in (embed.description or ''))
        finally:
            bot_mod.DM_STATE_FILE = old_dm_state
            bot_mod.bot = old_bot
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_stats():
    """Tests fuer /stats Command."""
    print('[/stats]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('stats')
        check('cmd_stats gefunden', cmd is not None)
        if not cmd:
            return

        # bot-Variable patchen (stats nutzt bot.fetch_user)
        import bot as bot_mod
        old_bot = bot_mod.bot
        bot_mod.bot = _CapturingBot()

        try:
            # Test: leer
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('leer → Hinweis', 'keine statistiken' in content)

            # Test: mit Daten
            import core.stats as stats_mod
            atomic_write(stats_mod.STATS_FILE, {
                '12345': {'puzzles': 10, 'downloads': 5,
                          'reaction_✅': 8, 'reaction_❌': 2},
            })
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            check('defer aufgerufen',
                  ia.response.calls[0].get('type') == 'defer')
            check('followup.send aufgerufen', len(ia.followup.calls) > 0)
            if ia.followup.calls:
                embeds = ia.followup.calls[0].get('embeds', [])
                embed = ia.followup.calls[0].get('embed') or (embeds[0] if embeds else None)
                check('mit Daten → Embed mit Stats',
                      embed is not None and embed.description is not None
                      and '10' in embed.description)
        finally:
            bot_mod.bot = old_bot
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_puzzle():
    """Smoke-Tests fuer /puzzle Command."""
    print('[/puzzle]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('puzzle')
        check('cmd_puzzle gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        # Patch post_puzzle um IO zu vermeiden
        orig_post = leg.post_puzzle
        call_log = []

        async def fake_post_puzzle(channel, count=1, book_idx=0, user_id=None):
            call_log.append({'count': count, 'book_idx': book_idx, 'user_id': user_id})
            return count

        leg.post_puzzle = fake_post_puzzle

        try:
            # Test: Standard-Aufruf
            ia = make_interaction()
            run_async(cmd(ia, anzahl=2, buch=0, id='', user=None))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('post_puzzle aufgerufen', len(call_log) == 1)
            check('post_puzzle count=2', call_log[0]['count'] == 2)
            check('followup mit Bestaetigung',
                  len(ia.followup.calls) > 0 and
                  '2' in (ia.followup.calls[0].get('content') or ''))

            # Test: id nicht gefunden
            call_log.clear()
            orig_find = leg.find_line_by_id
            leg.find_line_by_id = lambda lid: None
            ia = make_interaction()
            run_async(cmd(ia, anzahl=1, buch=0, id='nonexistent.pgn:999', user=None))
            check('id nicht gefunden → Fehlermeldung',
                  len(ia.followup.calls) > 0 and
                  'nicht gefunden' in (ia.followup.calls[0].get('content') or '').lower())
            leg.find_line_by_id = orig_find
        finally:
            leg.post_puzzle = orig_post
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_kurs():
    """Smoke-Tests fuer /kurs Command."""
    print('[/kurs]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('kurs')
        check('cmd_kurs gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        # Patch load_all_lines
        orig_load = leg.load_all_lines
        orig_state = leg.load_puzzle_state
        orig_books = leg._load_books_config
        orig_list = leg._list_pgn_files

        leg.load_all_lines = lambda: []
        leg.load_puzzle_state = lambda: {'posted': []}
        leg._load_books_config = lambda: {}
        leg._list_pgn_files = lambda: []

        try:
            # Test: keine Buecher
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            # Bei leeren lines gibt es ein Embed ohne Felder oder Warnung
            check('followup gesendet', len(ia.followup.calls) > 0)

            # Test: mit Buechern
            leg.load_all_lines = lambda: [
                ('book1.pgn:001.001', MagicMock()),
                ('book1.pgn:001.002', MagicMock()),
            ]
            leg._list_pgn_files = lambda: ['book1.pgn']
            leg._load_books_config = lambda: {
                'book1.pgn': {'difficulty': 'Anfaenger', 'rating': 3,
                              'random': True, 'blind': False}
            }
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            check('mit Buch → followup', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('mit Buch → Embed hat Felder',
                  embed is not None and len(embed.fields) > 0)
        finally:
            leg.load_all_lines = orig_load
            leg.load_puzzle_state = orig_state
            leg._load_books_config = orig_books
            leg._list_pgn_files = orig_list
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_train():
    """Smoke-Tests fuer /train Command."""
    print('[/train]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('train')
        check('cmd_train gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        orig_get = leg._get_user_training
        orig_set = leg._set_user_training
        orig_clear = leg._clear_user_training
        orig_load = leg.load_all_lines
        orig_list = leg._list_pgn_files
        orig_books = leg._load_books_config

        _training = {}

        def fake_get(uid):
            return _training.get(uid)

        def fake_set(uid, book, pos):
            _training[uid] = {'book': book, 'position': pos}

        def fake_clear(uid):
            _training.pop(uid, None)

        leg._get_user_training = fake_get
        leg._set_user_training = fake_set
        leg._clear_user_training = fake_clear
        leg.load_all_lines = lambda: [
            ('book1.pgn:001.001', MagicMock()),
            ('book1.pgn:001.002', MagicMock()),
        ]
        leg._list_pgn_files = lambda: ['book1.pgn']
        leg._load_books_config = lambda: {
            'book1.pgn': {'difficulty': 'Anfaenger', 'rating': 3}
        }

        try:
            # Test: Status ohne Training
            ia = make_interaction()
            run_async(cmd(ia, buch=None))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('kein Training → Hinweis', 'kein training' in content)

            # Test: Buch waehlen
            ia = make_interaction()
            run_async(cmd(ia, buch=1))
            check('Buch waehlen → Embed',
                  len(ia.followup.calls) > 0 and
                  ia.followup.calls[0].get('embed') is not None)
            check('Training gesetzt', 12345 in _training)

            # Test: Buch 0 = stoppen
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('Buch 0 → beendet', 'beendet' in content)

            # Test: ungueliges Buch
            ia = make_interaction()
            run_async(cmd(ia, buch=99))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('ungültiges Buch → Fehler', 'nicht gefunden' in content)
        finally:
            leg._get_user_training = orig_get
            leg._set_user_training = orig_set
            leg._clear_user_training = orig_clear
            leg.load_all_lines = orig_load
            leg._list_pgn_files = orig_list
            leg._load_books_config = orig_books
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_next():
    """Smoke-Tests fuer /next Command."""
    print('[/next]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('next')
        check('cmd_next gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        orig_get = leg._get_user_training
        _training = {}
        leg._get_user_training = lambda uid: _training.get(uid)

        try:
            # Test: kein Training → Fehler
            ia = make_interaction()
            run_async(cmd(ia, anzahl=1))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('kein Training → Fehler', 'kein trainingsbuch' in content)
        finally:
            leg._get_user_training = orig_get
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_endless():
    """Smoke-Tests fuer /endless Command."""
    print('[/endless]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('endless')
        check('cmd_endless gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        orig_is = leg.is_endless
        orig_start = leg.start_endless
        orig_stop = leg.stop_endless
        orig_post = leg.post_next_endless
        orig_list = leg._list_pgn_files

        _sessions = {}

        def fake_is(uid):
            return uid in _sessions

        def fake_start(uid, book):
            _sessions[uid] = {'book': book, 'count': 0}

        def fake_stop(uid):
            count = _sessions.pop(uid, {}).get('count', 0)
            return count

        async def fake_post_next(bot, uid):
            if uid in _sessions:
                _sessions[uid]['count'] += 1

        leg.is_endless = fake_is
        leg.start_endless = fake_start
        leg.stop_endless = fake_stop
        leg.post_next_endless = fake_post_next
        leg._list_pgn_files = lambda: ['book1.pgn']

        try:
            # Test: starten (braucht den bot-Parameter)
            # endless-Command in bot.py ruft _cmd_endless(bot, interaction, buch)
            # aber der captured Command ist: async def cmd_endless(interaction, buch=0)
            # → _cmd_endless(bot, interaction, buch)
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            check('starten → defer + followup',
                  ia.response.calls[0].get('type') == 'defer' and
                  len(ia.followup.calls) > 0)

            # Test: stoppen (Toggle)
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            content = ia.response.calls[0].get('content') or ''
            check('stoppen-Toggle → beendet',
                  'beendet' in content.lower() or 'Endless' in content)
        finally:
            leg.is_endless = orig_is
            leg.start_endless = orig_start
            leg.stop_endless = orig_stop
            leg.post_next_endless = orig_post
            leg._list_pgn_files = orig_list
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_blind():
    """Smoke-Tests fuer /blind Command."""
    print('[/blind]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('blind')
        check('cmd_blind gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as puzzle_mod

        orig_post = puzzle_mod.post_blind_puzzle

        call_log = []
        async def fake_post_blind(channel, moves=4, count=1, book_idx=0, user_id=None):
            call_log.append({'moves': moves, 'count': count})

        puzzle_mod.post_blind_puzzle = fake_post_blind

        try:
            # Test: moves < 1 → Fehler
            ia = make_interaction()
            run_async(cmd(ia, moves=0, anzahl=1, buch=0, user=None))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('moves < 1 → Fehler', 'zwischen 1 und 50' in content)

            # Test: Standard-Aufruf
            ia = make_interaction()
            run_async(cmd(ia, moves=4, anzahl=2, buch=0, user=None))
            check('Standard → defer', ia.response.calls[0].get('type') == 'defer')
            check('post_blind_puzzle aufgerufen', len(call_log) > 0)
        finally:
            puzzle_mod.post_blind_puzzle = orig_post
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_daily():
    """Smoke-Tests fuer /daily Command."""
    print('[/daily]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('daily')
        check('cmd_daily gefunden', cmd is not None)
        if not cmd:
            return

        import bot as bot_mod
        import puzzle as puzzle_mod

        old_bot = bot_mod.bot
        old_channel_id = bot_mod.CHANNEL_ID
        orig_post = puzzle_mod.post_puzzle

        call_log = []
        async def fake_post(channel, **kw):
            call_log.append(True)
            return 1

        puzzle_mod.post_puzzle = fake_post

        try:
            # Test: Channel nicht gefunden
            bot_mod.CHANNEL_ID = 0

            class NullBot:
                def get_channel(self, cid):
                    return None

            bot_mod.bot = NullBot()
            ia = make_interaction()
            run_async(cmd(ia))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('Channel nicht gefunden → Fehler', 'nicht gefunden' in content)

            # Test: Erfolg
            bot_mod.CHANNEL_ID = 99999
            bot_mod.bot = _CapturingBot()
            ia = make_interaction()
            run_async(cmd(ia))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('post_puzzle aufgerufen', len(call_log) > 0)
            check('followup gesendet', len(ia.followup.calls) > 0)
        finally:
            bot_mod.bot = old_bot
            bot_mod.CHANNEL_ID = old_channel_id
            puzzle_mod.post_puzzle = orig_post
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_ignore_kapitel():
    """Smoke-Tests fuer /ignore_kapitel Command."""
    print('[/ignore_kapitel]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('ignore_kapitel')
        check('cmd_ignore_kapitel gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        orig_load_ign = leg._load_chapter_ignore_list
        orig_ignore = leg.ignore_chapter
        orig_unignore = leg.unignore_chapter
        orig_list = leg._list_pgn_files
        orig_find_prefix = leg._find_chapter_prefix
        orig_list_chapters = leg._list_chapters

        _ignored = set()

        leg._load_chapter_ignore_list = lambda: _ignored
        leg.ignore_chapter = lambda b, p: _ignored.add(f'{b}:{p}')
        leg.unignore_chapter = lambda b, p: _ignored.discard(f'{b}:{p}')
        leg._list_pgn_files = lambda: ['book1.pgn']
        leg._find_chapter_prefix = lambda b, k: str(k) if k <= 5 else None
        leg._list_chapters = lambda b: {'1': 10, '2': 8, '3': 5}
        leg._clean_book_name = lambda fn: fn.replace('.pgn', '')

        try:
            # Test: Liste leer
            ia = make_interaction(admin=True)
            run_async(cmd(ia, buch=0, kapitel=0, aktion=None))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('Liste leer → Hinweis', 'keine kapitel' in content)

            # Test: ignore
            ia = make_interaction(admin=True)
            run_async(cmd(ia, buch=1, kapitel=3, aktion=None))
            content = ia.followup.calls[0].get('content') or ''
            check('ignore → Bestaetigung', 'ignoriert' in content.lower())
            check('Kapitel in Liste', 'book1.pgn:3' in _ignored)

            # Test: unignore
            aktion_mock = MagicMock()
            aktion_mock.value = 'unignore'
            ia = make_interaction(admin=True)
            run_async(cmd(ia, buch=1, kapitel=3, aktion=aktion_mock))
            content = ia.followup.calls[0].get('content') or ''
            check('unignore → Bestaetigung', 'aktiviert' in content.lower())
        finally:
            leg._load_chapter_ignore_list = orig_load_ign
            leg.ignore_chapter = orig_ignore
            leg.unignore_chapter = orig_unignore
            leg._list_pgn_files = orig_list
            leg._find_chapter_prefix = orig_find_prefix
            leg._list_chapters = orig_list_chapters
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_test_cmd():
    """Smoke-Tests fuer /test Command."""
    print('[/test]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('test')
        check('cmd_test gefunden', cmd is not None)
        if not cmd:
            return

        import commands.test as test_mod

        orig_load = test_mod._load_snapshots
        orig_find = test_mod._find_game

        # Minimaler Snapshot
        fake_snap = {
            'filename': 'book1_firstkey.pgn',
            'round': '001.001',
            'trimmed': False,
            'fen': 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
            'side': 'w',
            'first_move_uci': 'e2e4',
        }
        test_mod._load_snapshots = lambda: [fake_snap]

        # _find_game muss ein Game-Objekt zurueckgeben
        import chess.pgn
        import io as _io

        def fake_find_game(filename, round_id):
            pgn = _io.StringIO('1. e4 e5 *')
            return chess.pgn.read_game(pgn)

        test_mod._find_game = fake_find_game

        # _trim_to_training_position muss importierbar sein
        try:
            ia = make_interaction(admin=True)
            run_async(cmd(ia, kurs=0, puzzle=0, lichess=0))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('followup gesendet', len(ia.followup.calls) > 0)
        finally:
            test_mod._load_snapshots = orig_load
            test_mod._find_game = orig_find
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_bibliothek():
    """Smoke-Tests fuer /bibliothek Command."""
    print('[/bibliothek]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('bibliothek')
        check('cmd_bibliothek gefunden', cmd is not None)
        if not cmd:
            return

        import library as lib_mod

        orig_pag = lib_mod.LibraryPaginationView
        lib_mod.LibraryPaginationView = lambda pages, query: FakeView()

        orig_search = lib_mod._search_library
        lib_mod._search_library = lambda q, limit=25: [
            {
                'id': 'test--testbook',
                'title': 'Testbook',
                'author': 'TestAutor',
                'year': 2020,
                'tags': ['Taktik'],
                'file_type': 'pdf',
                'files': [],
            },
        ]

        try:
            ia = make_interaction()
            run_async(cmd(ia, suche='test'))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('followup gesendet', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('Ergebnis → Embed mit Feld',
                  embed is not None and len(embed.fields) > 0)
        finally:
            lib_mod._search_library = orig_search
            lib_mod.LibraryPaginationView = orig_pag
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_tag():
    """Smoke-Tests fuer /tag Command."""
    print('[/tag]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('tag')
        check('cmd_tag gefunden', cmd is not None)
        if not cmd:
            return

        import library as lib_mod

        # LibraryPaginationView ist ein MagicMock → ersetzen
        orig_pag = lib_mod.LibraryPaginationView
        lib_mod.LibraryPaginationView = lambda pages, query: FakeView()

        orig_ensure = lib_mod._ensure_library
        lib_mod._ensure_library = lambda: [
            {
                'id': 'test--taktikbook',
                'title': 'Taktik Buch',
                'author': 'Autor',
                'year': 2021,
                'tags': ['Taktik'],
                'file_type': 'pdf',
                'files': [],
            },
        ]

        try:
            ia = make_interaction()
            run_async(cmd(ia, tag='Taktik'))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('followup gesendet', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('Tag-Ergebnis → Embed',
                  embed is not None and len(embed.fields) > 0)

            # Test: Tag nicht gefunden
            ia = make_interaction()
            run_async(cmd(ia, tag='Nonexistent'))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('Tag nicht gefunden', 'keine bücher' in content or 'keine b' in content)
        finally:
            lib_mod._ensure_library = orig_ensure
            lib_mod.LibraryPaginationView = orig_pag
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_autor():
    """Smoke-Tests fuer /autor Command."""
    print('[/autor]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('autor')
        check('cmd_autor gefunden', cmd is not None)
        if not cmd:
            return

        import library as lib_mod

        orig_pag = lib_mod.LibraryPaginationView
        lib_mod.LibraryPaginationView = lambda pages, query: FakeView()

        orig_ensure = lib_mod._ensure_library
        lib_mod._ensure_library = lambda: [
            {
                'id': 'kasparov--mygreat',
                'title': 'My Great Predecessors',
                'author': 'Kasparov',
                'year': 2003,
                'tags': [],
                'file_type': 'pdf',
                'files': [],
            },
        ]

        try:
            ia = make_interaction()
            run_async(cmd(ia, autor='Kasparov'))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('followup gesendet', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('Autor-Ergebnis → Embed',
                  embed is not None and len(embed.fields) > 0)

            # Test: Autor nicht gefunden
            ia = make_interaction()
            run_async(cmd(ia, autor='Unbekannt'))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('Autor nicht gefunden',
                  'keine bücher' in content or 'keine b' in content)
        finally:
            lib_mod._ensure_library = orig_ensure
            lib_mod.LibraryPaginationView = orig_pag
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_reindex():
    """Smoke-Tests fuer /reindex Command."""
    print('[/reindex]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('reindex')
        check('cmd_reindex gefunden', cmd is not None)
        if not cmd:
            return

        import library as lib_mod
        import puzzle.selection as sel_mod

        orig_build = lib_mod.build_library_catalog
        orig_reload = lib_mod._reload_library
        orig_clear = sel_mod.clear_lines_cache
        orig_load = sel_mod.load_all_lines

        lib_mod.build_library_catalog = lambda: (100, 50, 5, 3, 2)
        lib_mod._reload_library = lambda: None
        sel_mod.clear_lines_cache = lambda: None
        sel_mod.load_all_lines = lambda: [('a.pgn:1', None)] * 42

        # LIBRARY_INDEX muss gesetzt sein damit der Bibliotheks-Teil laeuft
        orig_index = lib_mod.LIBRARY_INDEX
        lib_mod.LIBRARY_INDEX = '/fake/index.txt'

        try:
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('followup gesendet', len(ia.followup.calls) > 0)
            content = ia.followup.calls[0].get('content') or ''
            check('Reindex-Ergebnis enthaelt Zahlen',
                  '50' in content and '42' in content)
        finally:
            lib_mod.build_library_catalog = orig_build
            lib_mod._reload_library = orig_reload
            sel_mod.clear_lines_cache = orig_clear
            sel_mod.load_all_lines = orig_load
            lib_mod.LIBRARY_INDEX = orig_index
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_wanted():
    """Tests fuer /wanted, /wanted_list, /wanted_vote, /wanted_delete."""
    print('[/wanted]')
    tmpdir = setup_temp_config()
    try:
        cmd_wanted = _captured_commands.get('wanted')
        cmd_wanted_list = _captured_commands.get('wanted_list')
        cmd_wanted_vote = _captured_commands.get('wanted_vote')
        cmd_wanted_delete = _captured_commands.get('wanted_delete')

        check('cmd_wanted gefunden', cmd_wanted is not None)
        check('cmd_wanted_list gefunden', cmd_wanted_list is not None)
        check('cmd_wanted_vote gefunden', cmd_wanted_vote is not None)
        check('cmd_wanted_delete gefunden', cmd_wanted_delete is not None)
        if not all([cmd_wanted, cmd_wanted_list, cmd_wanted_vote, cmd_wanted_delete]):
            return

        # Test: wanted ohne Beschreibung → zeigt leere Liste
        ia = make_interaction()
        run_async(cmd_wanted(ia, beschreibung=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('wanted leer → Hinweis',
              'keine feature' in content or 'keine feature-wünsche' in content
              or 'keine feature-w' in content)

        # Test: wanted_list leer
        ia = make_interaction()
        run_async(cmd_wanted_list(ia))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('wanted_list leer → Hinweis',
              'keine feature' in content or 'keine feature-w' in content)

        # Test: Feature einreichen
        ia = make_interaction()
        run_async(cmd_wanted(ia, beschreibung='Dark Mode'))
        content = ia.response.calls[0].get('content') or ''
        check('wanted einreichen → Bestaetigung',
              'Dark Mode' in content and '#1' in content)

        # Test: Zweites Feature einreichen
        ia = make_interaction(user=FakeMember(uid=99999, name='User2'))
        run_async(cmd_wanted(ia, beschreibung='Mobile App'))
        content = ia.response.calls[0].get('content') or ''
        check('wanted zweites Feature → #2',
              'Mobile App' in content and '#2' in content)

        # Test: wanted_list zeigt Eintraege
        ia = make_interaction()
        run_async(cmd_wanted_list(ia))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('wanted_list → Embed', embed is not None)
        check('wanted_list → hat Beschreibung',
              embed is not None and 'Dark Mode' in (embed.description or ''))

        # Test: wanted_vote +1
        ia = make_interaction(user=FakeMember(uid=99999, name='User2'))
        run_async(cmd_wanted_vote(ia, id=1))
        content = (ia.response.calls[0].get('content') or '')
        check('wanted_vote +1', '+1' in content or '✅' in content)

        # Test: wanted_vote Toggle (zuruecknehmen)
        ia = make_interaction(user=FakeMember(uid=99999, name='User2'))
        run_async(cmd_wanted_vote(ia, id=1))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('wanted_vote Toggle → zurueckgenommen',
              'zurück' in content or 'zuruck' in content or '↩' in content)

        # Test: wanted_vote nicht gefunden
        ia = make_interaction()
        run_async(cmd_wanted_vote(ia, id=999))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('wanted_vote nicht gefunden', 'nicht gefunden' in content)

        # Test: wanted_delete
        ia = make_interaction(admin=True)
        run_async(cmd_wanted_delete(ia, id=1))
        content = ia.response.calls[0].get('content') or ''
        check('wanted_delete → Bestaetigung', '#1' in content)

        # Test: wanted_delete nicht gefunden
        ia = make_interaction(admin=True)
        run_async(cmd_wanted_delete(ia, id=999))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('wanted_delete nicht gefunden', 'nicht gefunden' in content)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_release_notes():
    """Tests fuer /release-notes Command."""
    print('[/release-notes]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('release-notes')
        check('cmd_release_notes gefunden', cmd is not None)
        if not cmd:
            return

        # Test: Standard (letzte 3 Versionen)
        ia = make_interaction()
        run_async(cmd(ia, version=None, anzahl=3))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('Standard → Embed', embed is not None)
        check('Standard → hat Felder', embed is not None and len(embed.fields) > 0)
        check('Standard → max 3 Felder', embed is not None and len(embed.fields) <= 3)

        # Test: bestimmte Version
        ia = make_interaction()
        run_async(cmd(ia, version='1.0.0', anzahl=3))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('Version 1.0.0 → Embed', embed is not None)
        check('Version 1.0.0 → 1 Feld',
              embed is not None and len(embed.fields) == 1)

        # Test: nicht existierende Version
        ia = make_interaction()
        run_async(cmd(ia, version='99.99.99', anzahl=3))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('Version nicht gefunden', 'nicht im changelog' in content)
    finally:
        teardown_temp_config(tmpdir)
    print()


# ===================================================================
# 8) Library-Unit-Tests (parse, auto-tag, catalog)
# ===================================================================

def test_parse_index_entry():
    """Tests fuer _parse_index_entry (library.py)."""
    print('[_parse_index_entry]')
    from library import _parse_index_entry

    # Normaler Eintrag
    result = _parse_index_entry('/data/schach/Kasparov/My Great Predecessors (2003).pdf')
    check('normaler Eintrag', result is not None)
    check('Autor', result[0] == 'Kasparov')
    check('Jahr extrahiert', result[2] == 2003)
    check('Extension', result[3] == 'pdf')

    # Eintrag mit Bracket-Jahr
    result = _parse_index_entry('/data/schach/Author/Title [Other, 1999].epub')
    check('Bracket-Jahr', result is not None and result[2] == 1999)

    # Leere Zeile
    check('leere Zeile → None', _parse_index_entry('') is None)

    # Kein /schach/ Pfad
    check('ohne schach → None', _parse_index_entry('/data/music/file.mp3') is None)

    # Zu wenig Pfadteile
    check('zu kurz → None', _parse_index_entry('/data/schach/file.pdf') is None)

    # Ohne Extension
    check('ohne Ext → None', _parse_index_entry('/data/schach/Author/NoExt') is None)
    print()


def test_auto_tag():
    """Tests fuer _auto_tag (library.py)."""
    print('[_auto_tag]')
    from library import _auto_tag

    # Taktik-Buch
    tags = _auto_tag('1001 Tactical Puzzles', 'Author', 'pdf')
    check('Taktik-Tag', 'Taktik' in tags)
    check('eBook-Tag', 'eBook' in tags)

    # Eroeffnungsbuch
    tags = _auto_tag('The Sicilian Defense', 'Kasparov', 'pgn')
    check('Sizilianisch-Tag', 'Sizilianisch' in tags)
    check('PGN-Tag', 'PGN' in tags)

    # Endspiel (Regex \bendgame\b matcht Singular)
    tags = _auto_tag('Endgame Strategy', 'Mueller', 'epub')
    check('Endspiel-Tag', 'Endspiel' in tags)

    # Ohne Matches
    tags = _auto_tag('Untitled', 'Nobody', 'xyz')
    check('Keine Tags', len(tags) == 0)

    # Deutsche Sprach-Erkennung
    tags = _auto_tag('Chess Book (german)', 'Author', 'pdf')
    check('Deutsch-Tag', 'Deutsch' in tags)
    print()


def test_build_library_catalog():
    """Tests fuer build_library_catalog (library.py)."""
    print('[build_library_catalog]')
    import library

    tmpdir = tempfile.mkdtemp(prefix='lib_test_')
    try:
        index_file = os.path.join(tmpdir, 'index.txt')
        lib_file = os.path.join(tmpdir, 'library.json')

        # Speichere original-Werte
        orig_index = library.LIBRARY_INDEX
        orig_file = library.LIBRARY_FILE

        library.LIBRARY_INDEX = index_file
        library.LIBRARY_FILE = lib_file

        # Ohne index.txt → (0,0,0,0,0)
        library.LIBRARY_INDEX = ''
        result = library.build_library_catalog()
        check('ohne Index → alles 0', result == (0, 0, 0, 0, 0))

        # Mit index.txt
        library.LIBRARY_INDEX = index_file
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write('/data/schach/Kasparov/My Great Predecessors (2003).pdf\n')
            f.write('/data/schach/Mueller/Basic Endgames.epub\n')

        result = library.build_library_catalog()
        check('Dateien gezaehlt', result[0] == 2)
        check('Buecher erstellt', result[1] == 2)
        check('Neue Eintraege', result[2] == 2)

        # Nochmal aufrufen → updates statt neu
        result2 = library.build_library_catalog()
        check('Wiederholung → 0 neue', result2[2] == 0)
        check('Wiederholung → 2 aktualisiert', result2[3] == 2)

    finally:
        library.LIBRARY_INDEX = orig_index
        library.LIBRARY_FILE = orig_file
        shutil.rmtree(tmpdir, ignore_errors=True)
    print()


def test_dm_log():
    """Tests fuer /dm-log Command."""
    print('[/dm-log]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('dm-log')
        check('cmd_dm_log gefunden', cmd is not None)
        if not cmd:
            return

        # DM_LOG_FILE patchen
        import core.dm_log as dm_log_mod
        import bot as bot_mod
        old_dm_log_file = dm_log_mod.DM_LOG_FILE
        dm_log_mod.DM_LOG_FILE = os.path.join(tmpdir, 'dm_log.json')
        old_bot = bot_mod.bot
        bot_mod.bot = _CapturingBot()

        try:
            # Test: leer
            ia = make_interaction(admin=True)
            run_async(cmd(ia, user=None))
            check('defer aufgerufen (leer)',
                  ia.response.calls[0].get('type') == 'defer')
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('leer → Hinweis', 'keine dms' in content)

            # Test: mit Eintraegen
            atomic_write(dm_log_mod.DM_LOG_FILE, {
                '12345': [
                    {'ts': '2026-04-25T18:00:00+00:00', 'text': 'Hallo!'},
                    {'ts': '2026-04-25T19:00:00+00:00', 'text': 'Puzzle gesendet'},
                ],
                '67890': [
                    {'ts': '2026-04-26T10:00:00+00:00', 'text': 'Willkommen'},
                ],
            })
            ia = make_interaction(admin=True)
            run_async(cmd(ia, user=None))
            check('defer aufgerufen (Daten)',
                  ia.response.calls[0].get('type') == 'defer')
            check('followup.send aufgerufen', len(ia.followup.calls) > 0)
            if ia.followup.calls:
                embeds = ia.followup.calls[0].get('embeds', [])
                embed = embeds[0] if embeds else None
                desc = embed.description if embed else ''
                # Uebersicht: eine Zeile pro User, kein DM-Inhalt
                check('Uebersicht enthaelt DM-Anzahl', '2 DMs' in desc)
                check('Uebersicht enthaelt Letzte', 'Letzte:' in desc)
                check('Uebersicht enthaelt KEINEN Inhalt', 'Hallo' not in desc)
        finally:
            dm_log_mod.DM_LOG_FILE = old_dm_log_file
            bot_mod.bot = old_bot
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_schachrallye():
    """Tests fuer /schachrallye, /schachrallye_add, _del, _sub, _unsub."""
    print('[/schachrallye]')
    tmpdir = setup_temp_config()
    try:
        cmd_rallye = _captured_commands.get('schachrallye')
        cmd_add = _captured_commands.get('schachrallye_add')
        cmd_del = _captured_commands.get('schachrallye_del')
        cmd_sub = _captured_commands.get('schachrallye_sub')
        cmd_unsub = _captured_commands.get('schachrallye_unsub')

        check('cmd_schachrallye gefunden', cmd_rallye is not None)
        check('cmd_schachrallye_add gefunden', cmd_add is not None)
        check('cmd_schachrallye_del gefunden', cmd_del is not None)
        check('cmd_schachrallye_sub gefunden', cmd_sub is not None)
        check('cmd_schachrallye_unsub gefunden', cmd_unsub is not None)
        if not all([cmd_rallye, cmd_add, cmd_del, cmd_sub, cmd_unsub]):
            return

        # Test: Leere Liste → Hinweis
        ia = make_interaction()
        run_async(cmd_rallye(ia))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('leere Liste → Hinweis', 'keine' in content)

        # Test: Termin anlegen (Zukunftsdatum)
        from datetime import date, timedelta
        future = date.today() + timedelta(days=30)
        datum_str = future.strftime('%d.%m.%Y')
        ia = make_interaction(admin=True)
        run_async(cmd_add(ia, datum=datum_str, ort='Berlin'))
        content = ia.response.calls[0].get('content') or ''
        check('Termin anlegen → Bestaetigung',
              '#1' in content and 'Berlin' in content)

        # Test: Termin in JSON gespeichert (mit schachrallye-Tag)
        tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
        check('Termin in JSON', len(tdata.get('events', [])) == 1)
        check('Termin hat schachrallye-Tag',
              'schachrallye' in tdata['events'][0].get('tags', []))

        # Test: Termine anzeigen → Embed mit Termin
        ia = make_interaction()
        run_async(cmd_rallye(ia))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('Termine anzeigen → Embed', embed is not None)
        check('Embed enthaelt Berlin',
              embed is not None and 'Berlin' in (embed.description or ''))

        # Test: Subscriben
        sub_user = FakeMember(uid=55555, name='SubUser')
        sub_dm_channel = FakeChannel()
        sub_user.create_dm = AsyncMock(return_value=sub_dm_channel)
        ia = make_interaction(user=sub_user)
        run_async(cmd_sub(ia, user=None))
        content = ia.response.calls[0].get('content') or ''
        check('Subscriben → Bestaetigung', 'subscribed' in content.lower())
        check('Subscriben → DM gesendet', len(sub_dm_channel.sent) == 1)
        dm_text = sub_dm_channel.sent[0].content or ''
        check('Subscriben → DM enthaelt unsub-Hinweis', '/schachrallye_unsub' in dm_text)

        # Test: DM fehlgeschlagen (Forbidden) → kein Crash, Warning geloggt
        forbidden_user = FakeMember(uid=66666, name='NoDM')

        async def _raise_forbidden():
            raise discord.Forbidden(MagicMock(status=403), 'Cannot send DM')
        forbidden_user.create_dm = _raise_forbidden
        # Erst unsubscriben falls vorhanden, dann sub mit Forbidden-User
        ia = make_interaction(user=forbidden_user)
        with _mock.patch('logging.Logger.warning') as mock_warn:
            run_async(cmd_sub(ia, user=None))
            content = ia.response.calls[0].get('content') or ''
            check('Sub trotz DM-Fehler → Bestaetigung', 'subscribed' in content.lower())
            check('DM-Fehler → Warning geloggt',
                  any('66666' in str(c) for c in mock_warn.call_args_list))
        # User wieder unsubscriben fuer sauberen State
        ia = make_interaction(user=forbidden_user)
        run_async(cmd_unsub(ia, user=None))

        # Test: Doppelt subscriben
        ia = make_interaction(user=sub_user)
        run_async(cmd_sub(ia, user=None))
        content = ia.response.calls[0].get('content') or ''
        check('Doppelt sub → bereits', 'bereits' in content.lower())

        # Test: Unsubscriben (gleicher User der vorher subscribed hat)
        ia = make_interaction(user=sub_user)
        run_async(cmd_unsub(ia, user=None))
        content = ia.response.calls[0].get('content') or ''
        check('Unsub → Bestaetigung', 'abbestellt' in content.lower())

        # Test: Unsub wenn nicht subscribed
        ia = make_interaction(user=sub_user)
        run_async(cmd_unsub(ia, user=None))
        content = ia.response.calls[0].get('content') or ''
        check('Unsub nicht subscribed', 'nicht subscribed' in content.lower())

        # Test: Termin loeschen
        ia = make_interaction(admin=True)
        run_async(cmd_del(ia, id=1))
        content = ia.response.calls[0].get('content') or ''
        check('Termin loeschen → Bestaetigung', '#1' in content)

        # Test: Termin loeschen nicht gefunden
        ia = make_interaction(admin=True)
        run_async(cmd_del(ia, id=999))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('Termin loeschen nicht gefunden', 'nicht gefunden' in content)

        # Test: Datum-Validierung falsches Format
        ia = make_interaction(admin=True)
        run_async(cmd_add(ia, datum='2026-05-15', ort='Test'))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('Falsches Datumsformat → Fehler', 'ungueltig' in content or 'format' in content)

        # Test: Datum in der Vergangenheit
        ia = make_interaction(admin=True)
        run_async(cmd_add(ia, datum='01.01.2020', ort='Test'))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('Vergangenheit → Fehler', 'vergangenheit' in content)

        # Test: Sub mit user-Param als Nicht-Admin
        other = FakeMember(uid=99999, name='Other')
        ia = make_interaction(admin=False)
        run_async(cmd_sub(ia, user=other))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('Sub user ohne Admin → Fehler', 'admin' in content)

        # --- /turnier_parse + /turnier Tests ---
        cmd_parse = _captured_commands.get('turnier_parse')
        cmd_turnier = _captured_commands.get('turnier')
        check('cmd_turnier_parse gefunden', cmd_parse is not None)
        check('cmd_turnier gefunden', cmd_turnier is not None)
        if cmd_parse and cmd_turnier:
            # Fake-HTML mit Rallye, Turnier+Link, Training, OeM (letzte 2 = rausgefiltert)
            future2 = (date.today() + timedelta(days=60)).strftime('%d.%m.%Y')
            future3 = (date.today() + timedelta(days=90)).strftime('%d.%m.%Y')
            fake_html = (
                '<table>'
                '<tr><th>Datum</th><th>Veranstaltung</th><th>Ort</th></tr>'
                f'<tr><td>{future2}</td><td>5. Jugendschachrallye</td>'
                '<td>SK Jenbach</td></tr>'
                '<tr><td>14.05.2026</td>'
                '<td><a href="https://example.com/ausschreibung.pdf">'
                'Staatsmeisterschaft Schnellschach</a></td>'
                '<td>PlusCity Linz</td></tr>'
                '<tr><td>20.-24.05.2026</td><td>Mannschaftsturnier</td>'
                '<td>Leutasch</td></tr>'
                f'<tr><td>{future3}</td><td>Offenes Blitzturnier</td>'
                '<td>Innsbruck</td></tr>'
                f'<tr><td>{future3}</td><td>Chess960 Open</td>'
                '<td>Schwaz</td></tr>'
                f'<tr><td>{future3}</td><td>Tiroler Senioren Einzelmeisterschaft</td>'
                '<td>Schwaz</td></tr>'
                f'<tr><td>{future2}</td><td>Blitzschach-Einzelmeisterschaft U08-U18</td>'
                '<td>Innsbruck</td></tr>'
                '<tr><td>26.04.2026</td><td>Kadertraining Gruppe Bauer</td>'
                '<td>Kufstein</td></tr>'
                '<tr><td>22.05.-25.05.2026</td>'
                '<td>Österreichische Meisterschaften U08/ U10</td>'
                '<td>Fuerstenfeld</td></tr>'
                '</table>'
            )
            fake_resp = MagicMock()
            fake_resp.text = fake_html
            fake_resp.raise_for_status = MagicMock()
            old_fetch = schachrallye_mod.requests.get
            schachrallye_mod.requests.get = MagicMock(return_value=fake_resp)
            try:
                # Parse: importiert Rallye + Turniere, filtert Training
                ia = make_interaction(admin=True)
                run_async(cmd_parse(ia))
                check('parse → defer', any(c['type'] == 'defer' for c in ia.response.calls))
                fu_call = ia.followup.calls[0]
                fu_embed = fu_call.get('embed')
                fu_desc = fu_embed.description if fu_embed else ''
                # Fallback auf content (z.B. bei "bereits vorhanden")
                if not fu_desc:
                    fu_desc = fu_call.get('content') or ''
                check('parse → Rallye importiert', 'Jugendschachrallye' in fu_desc)
                check('parse → Turniere importiert', 'Staatsmeisterschaft' in fu_desc)
                check('parse → Training gefiltert', 'Kadertraining' not in fu_desc)
                check('parse → OeM gefiltert', 'Meisterschaften U08' not in fu_desc)

                # Alles in einer turnier.json?
                tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
                all_events = tdata.get('events', [])
                # Rallye (1) + manueller Termin von oben (1, bereits geloescht) + 2 Turniere = 3
                # Aber der manuell angelegte wurde geloescht → Rallye(1) + Turniere(2) = 3
                rallye_events = [e for e in all_events if 'schachrallye' in e.get('tags', [])]
                turnier_events = [e for e in all_events if 'schachrallye' not in e.get('tags', [])]
                check('parse → Rallye in JSON', len(rallye_events) >= 1)
                check('parse → Turniere in JSON', len(turnier_events) == 6)
                check('parse → Tags korrekt',
                      all('schachrallye' in e.get('tags', []) for e in rallye_events))

                # Schnellschach/Blitz/960 Tags
                staats_tags = [e for e in all_events if 'Staatsmeisterschaft' in e.get('name', '')]
                check('parse → Schnellschach-Tag',
                      len(staats_tags) == 1 and 'schnellschach' in staats_tags[0].get('tags', []))
                blitz_evts = [e for e in all_events if 'Blitz' in e.get('name', '')]
                check('parse → Blitz-Tag',
                      len(blitz_evts) >= 1 and all('blitz' in e.get('tags', []) for e in blitz_evts))
                c960_evts = [e for e in all_events if '960' in e.get('name', '')]
                check('parse → 960-Tag',
                      len(c960_evts) == 1 and '960' in c960_evts[0].get('tags', []))

                # Jugend-Tag
                jugend_rallye = [e for e in all_events if 'Jugendschachrallye' in e.get('name', '')]
                check('parse → Jugend-Tag auf Rallye',
                      len(jugend_rallye) >= 1 and 'jugend' in jugend_rallye[0].get('tags', []))
                jugend_u18 = [e for e in all_events if 'U08-U18' in e.get('name', '')]
                check('parse → Jugend-Tag auf U08-U18',
                      len(jugend_u18) == 1 and 'jugend' in jugend_u18[0].get('tags', []))
                # Senioren-Tag
                senior_evts = [e for e in all_events if 'Senioren' in e.get('name', '')]
                check('parse → Senioren-Tag',
                      len(senior_evts) == 1 and 'senioren' in senior_evts[0].get('tags', []))
                # Klassisch-Tag (Open)
                open_evts = [e for e in all_events if 'Open' in e.get('name', '')]
                check('parse → Klassisch-Tag',
                      len(open_evts) >= 1 and all('klassisch' in e.get('tags', []) for e in open_evts))
                # URL-Validierung: ungueltige URLs nicht als Embed-URL
                check('_is_valid_url gueltig',
                      schachrallye_mod._is_valid_url('https://example.com/foo.pdf'))
                check('_is_valid_url ungueltig (Leerzeichen)',
                      not schachrallye_mod._is_valid_url('http://Rallye Jenbach: https://foo.com'))
                check('_is_valid_url ungueltig (leer)',
                      not schachrallye_mod._is_valid_url(''))

                # Link korrekt erfasst?
                staats = [e for e in all_events if 'Staatsmeisterschaft' in e.get('name', '')]
                check('parse → Link erfasst',
                      len(staats) == 1 and staats[0].get('link') == 'https://example.com/ausschreibung.pdf')

                # Datumsbereich korrekt geparst?
                mannschaft = [e for e in all_events if 'Mannschaft' in e.get('name', '')]
                check('parse → Datumsbereich geparst',
                      len(mannschaft) == 1 and mannschaft[0].get('datum_text') == '20.-24.05.2026')
                check('parse → kein Link wenn keiner da',
                      len(mannschaft) == 1 and mannschaft[0].get('link', '') == '')

                # Nochmal parsen → keine Duplikate
                ia = make_interaction(admin=True)
                run_async(cmd_parse(ia))
                fu_content = (ia.followup.calls[0].get('content') or '').lower()
                check('parse erneut → keine Duplikate', 'bereits vorhanden' in fu_content)

                # /turnier zeigt Turniere mit Link
                ia = make_interaction()
                run_async(cmd_turnier(ia))
                call = ia.response.calls[0]
                embed = call.get('embed')
                check('/turnier → Embed', embed is not None)
                desc = embed.description if embed else ''
                check('/turnier → enthaelt Turnier', 'Staatsmeisterschaft' in desc)
                check('/turnier → Link im Embed', 'example.com/ausschreibung.pdf' in desc)
                check('/turnier → kein Training', 'Kadertraining' not in desc)
                check('/turnier → keine OeM', 'Meisterschaften U08' not in desc)

                # /turnier leer
                atomic_write(schachrallye_mod.TURNIER_FILE, {"events": [], "subscribers": {}, "next_id": 1})
                ia = make_interaction()
                run_async(cmd_turnier(ia))
                content = (ia.response.calls[0].get('content') or '').lower()
                check('/turnier leer → Hinweis', 'keine' in content)
            finally:
                schachrallye_mod.requests.get = old_fetch
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_turnier_sub():
    """Tests fuer /turnier_sub und /turnier_unsub."""
    print('[/turnier_sub]')
    tmpdir = setup_temp_config()
    try:
        cmd_sub = _captured_commands.get('turnier_sub')
        cmd_unsub = _captured_commands.get('turnier_unsub')
        check('cmd_turnier_sub gefunden', cmd_sub is not None)
        check('cmd_turnier_unsub gefunden', cmd_unsub is not None)
        if not cmd_sub or not cmd_unsub:
            return

        # Sub fuer Tag → Bestaetigung + in JSON
        sub_user = FakeMember(uid=77777, name='TagUser')
        sub_dm_channel = FakeChannel()
        sub_user.create_dm = AsyncMock(return_value=sub_dm_channel)
        ia = make_interaction(user=sub_user)
        run_async(cmd_sub(ia, tag='blitz', user=None))
        content = ia.response.calls[0].get('content') or ''
        check('turnier_sub → Bestaetigung', 'blitz' in content.lower() and 'gepingt' in content.lower())

        # DM gesendet?
        check('turnier_sub → DM gesendet', len(sub_dm_channel.sent) == 1)
        dm_text = sub_dm_channel.sent[0].content or ''
        check('turnier_sub → DM enthaelt unsub-Hinweis', '/turnier_unsub' in dm_text)

        # In JSON gespeichert?
        tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
        blitz_subs = tdata.get('subscribers', {}).get('blitz', [])
        check('turnier_sub → in JSON unter subscribers.blitz', 77777 in blitz_subs)

        # Doppelt sub → bereits
        ia = make_interaction(user=sub_user)
        run_async(cmd_sub(ia, tag='blitz', user=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_sub doppelt → bereits', 'bereits' in content)

        # Unsub → Bestaetigung + entfernt
        ia = make_interaction(user=sub_user)
        run_async(cmd_unsub(ia, tag='blitz', user=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_unsub → Bestaetigung', 'abbestellt' in content)

        tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
        blitz_subs = tdata.get('subscribers', {}).get('blitz', [])
        check('turnier_unsub → aus JSON entfernt', 77777 not in blitz_subs)

        # Unsub wenn nicht subscribed
        ia = make_interaction(user=sub_user)
        run_async(cmd_unsub(ia, tag='blitz', user=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_unsub nicht subscribed → Hinweis', 'nicht' in content)

        # Ohne Tag → eigene Subs anzeigen (leer)
        ia = make_interaction(user=sub_user)
        run_async(cmd_sub(ia, tag='', user=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_sub ohne tag leer → Hinweis', 'keine' in content)

        # Sub fuer 2 Tags, dann ohne Tag → Liste
        sub_user2 = FakeMember(uid=77777, name='TagUser')
        sub_user2.create_dm = AsyncMock(return_value=FakeChannel())
        ia = make_interaction(user=sub_user2)
        run_async(cmd_sub(ia, tag='blitz', user=None))
        ia = make_interaction(user=sub_user2)
        run_async(cmd_sub(ia, tag='960', user=None))
        ia = make_interaction(user=sub_user2)
        run_async(cmd_sub(ia, tag='', user=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_sub ohne tag → zeigt Tags', '`blitz`' in content and '`960`' in content)

        # Aufraumen
        ia = make_interaction(user=sub_user2)
        run_async(cmd_unsub(ia, tag='blitz', user=None))
        ia = make_interaction(user=sub_user2)
        run_async(cmd_unsub(ia, tag='960', user=None))

        # Nicht-Admin mit user → Fehler
        other = FakeMember(uid=88888, name='Other')
        ia = make_interaction(admin=False)
        run_async(cmd_sub(ia, tag='blitz', user=other))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_sub user ohne Admin → Fehler', 'admin' in content)

        ia = make_interaction(admin=False)
        run_async(cmd_unsub(ia, tag='blitz', user=other))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_unsub user ohne Admin → Fehler', 'admin' in content)

    finally:
        teardown_temp_config(tmpdir)

    # schachrallye_sub Message erwaehnt Ping-Feature
    tmpdir = setup_temp_config()
    try:
        cmd_rallye_sub = _captured_commands.get('schachrallye_sub')
        if cmd_rallye_sub:
            ping_user = FakeMember(uid=44444, name='PingCheck')
            ping_dm = FakeChannel()
            ping_user.create_dm = AsyncMock(return_value=ping_dm)
            ia = make_interaction(user=ping_user)
            run_async(cmd_rallye_sub(ia, user=None))
            content = ia.response.calls[0].get('content') or ''
            check('schachrallye_sub → erwaehnt Ping', 'gepingt' in content.lower())
            check('schachrallye_sub → erwaehnt 7 Tage', '7 tage' in content.lower())
            dm_text = ping_dm.sent[0].content or '' if ping_dm.sent else ''
            check('schachrallye_sub DM → erwaehnt Ping', 'gepingt' in dm_text.lower())
        else:
            check('schachrallye_sub Ping-Feature', False, 'cmd nicht gefunden')
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_admin_enforcement():
    """Tests dass Admin-Commands von Nicht-Admins abgelehnt werden."""
    print('[Admin-Enforcement]')

    # /puzzle user:@X als Nicht-Admin
    tmpdir = setup_temp_config()
    try:
        import puzzle.commands
        cmd = getattr(puzzle.commands, '_cmd_puzzle', None)
        if cmd is None:
            for attr in dir(puzzle.commands):
                obj = getattr(puzzle.commands, attr)
                if callable(obj) and getattr(obj, '__name__', '') == '_cmd_puzzle':
                    cmd = obj
                    break

        if cmd:
            other_user = FakeMember(admin=False)
            other_user.id = 999
            other_user.mention = '<@999>'
            ia = make_interaction(admin=False)
            ia.user.id = 111
            run_async(cmd(ia, anzahl=1, buch=0, id=None, user=other_user))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('/puzzle user:@X non-admin → Fehler', 'admin' in content)
        else:
            check('/puzzle user:@X non-admin → Fehler', False, 'cmd nicht gefunden')
    finally:
        teardown_temp_config(tmpdir)

    # /blind Validierungen (anzahl, buch)
    cmd = _captured_commands.get('blind')
    if cmd:
        tmpdir = setup_temp_config()
        try:
            ia = make_interaction()
            run_async(cmd(ia, moves=4, anzahl=25, buch=0, user=None))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('/blind anzahl > 20 → Fehler', 'zwischen 1 und 20' in content)

            ia = make_interaction()
            run_async(cmd(ia, moves=4, anzahl=1, buch=-1, user=None))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('/blind buch:-1 → Fehler', 'negativ' in content)
        finally:
            teardown_temp_config(tmpdir)
    else:
        check('/blind Validierungen', False, 'cmd nicht gefunden')

    # /reminder buch:-1 → Fehler
    cmd = _captured_commands.get('reminder')
    if cmd:
        tmpdir = setup_temp_config()
        try:
            ia = make_interaction()
            run_async(cmd(ia, hours=4, puzzle_count=1, buch=-1))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('/reminder buch:-1 → Fehler', 'negativ' in content)
        finally:
            teardown_temp_config(tmpdir)
    else:
        check('/reminder buch:-1', False, 'cmd nicht gefunden')
    print()


# ===================================================================
# MAIN
# ===================================================================

def main():
    print(f'Slash-Command-Tests\n')

    test_help()
    test_version()
    test_elo()
    test_resourcen()
    test_youtube()
    test_puzzle()
    test_kurs()
    test_train()
    test_next()
    test_endless()
    test_blind()
    test_daily()
    test_ignore_kapitel()
    test_test_cmd()
    test_bibliothek()
    test_tag()
    test_autor()
    test_reindex()
    test_reminder()
    test_announce()
    test_greeted()
    test_stats()
    test_wanted()
    test_release_notes()
    test_parse_index_entry()
    test_auto_tag()
    test_build_library_catalog()
    test_dm_log()
    test_schachrallye()
    test_turnier_sub()
    test_admin_enforcement()

    print(f'---\n{total - failed}/{total} checks passed.')
    if failed:
        print(f'{failed} FAILED')
        sys.exit(1)
    else:
        print('Alle Tests OK.')


if __name__ == '__main__':
    main()
