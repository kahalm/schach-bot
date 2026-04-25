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
    _patch_file_constant('commands.resourcen', 'RESOURCEN_FILE', tmpdir)
    _patch_file_constant('commands.youtube', 'YOUTUBE_FILE', tmpdir)
    _patch_file_constant('commands.wanted', 'WANTED_FILE', tmpdir)
    _patch_file_constant('commands.reminder', 'REMINDER_FILE', tmpdir)
    _patch_file_constant('core.stats', 'STATS_FILE', tmpdir)

    return tmpdir


def _patch_file_constant(module_path, attr_name, tmpdir):
    try:
        mod = sys.modules.get(module_path)
        if mod is None:
            __import__(module_path)
            mod = sys.modules[module_path]
        old = getattr(mod, attr_name, '')
        basename = os.path.basename(old) if old else attr_name.lower() + '.json'
        setattr(mod, attr_name, os.path.join(tmpdir, basename))
    except Exception:
        pass


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

# bot.py importieren (ruft am Ende bot.run() auf, was jetzt ein no-op ist)
import bot as bot_mod

# setup() fuer alle Command-Module nochmal ausfuehren, damit die Commands
# im _captured_commands Dict landen (bot.py hat sie schon mit dem
# _CapturingTree registriert)
_cap_bot = _CapturingBot()
for mod in (elo_mod, resourcen_mod, youtube_mod, wanted_mod,
            release_notes_mod, reminder_mod):
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
# MAIN
# ===================================================================

def main():
    print(f'Slash-Command-Tests\n')

    test_help()
    test_version()
    test_elo()
    test_resourcen()
    test_youtube()
    test_wanted()
    test_release_notes()

    print(f'---\n{total - failed}/{total} checks passed.')
    if failed:
        print(f'{failed} FAILED')
        sys.exit(1)
    else:
        print('Alle Tests OK.')


if __name__ == '__main__':
    main()
