"""
Shared infrastructure for all command tests.

Stubs sys.modules for Discord and heavy dependencies, provides fake classes,
capturing bot, temp-config helpers, and check/run_async utilities.

Wird von allen test_cmd_*.py Dateien importiert.
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
from datetime import date, datetime, timezone, timedelta

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
    'anthropic',
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
_discord.ChannelType = MagicMock()
_discord.Attachment = type('Attachment', (), {'url': '', 'filename': ''})

# app_commands: alle Decorators als passthrough
_app_commands = sys.modules['discord.app_commands']
_app_commands.describe = _passthrough_decorator
_app_commands.default_permissions = _passthrough_decorator
_app_commands.choices = _passthrough_decorator
_app_commands.Choice = MagicMock
_app_commands.checks.cooldown = lambda *a, **kw: (lambda fn: fn)
# Muss auch auf discord.app_commands gesetzt werden
_discord.app_commands = _app_commands

# discord.ui
_ui = sys.modules['discord.ui']
_discord.ui = _ui

class FakeView:
    def __init__(self, **kw):
        self.children = []
    def add_item(self, item):
        self.children.append(item)

class FakeSelect(FakeView):
    pass

class FakeButton:
    def __init__(self, **kw):
        self.style = kw.get('style')
        self.emoji = kw.get('emoji')
        self.label = kw.get('label', '')
        self.custom_id = kw.get('custom_id', '')
        self.row = kw.get('row')
        self.callback = None

_ui.View = FakeView
_ui.Select = FakeSelect
_ui.Button = FakeButton
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

    def get_user(self, uid):
        return FakeUser(uid=uid, name=f'User_{uid}')

    async def fetch_user(self, uid):
        return FakeUser(uid=uid, name=f'User_{uid}')

    latency = 0.0

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


class FakeRole:
    def __init__(self, name='member'):
        self.name = name


class FakeUser:
    def __init__(self, uid=12345, name='TestUser', admin=False, roles=None):
        self.id = uid
        self.display_name = name
        self.name = name
        self.mention = f'<@{uid}>'
        self.guild_permissions = FakePermissions(administrator=admin)
        self.roles = roles or []
        self.bot = False

    async def create_dm(self):
        return FakeChannel()


class FakeMember(FakeUser, _discord.Member):
    pass


class _FakeGuild:
    """Fake-Guild fuer _display_name: liefert FakeUser per get_member/fetch_member."""

    def get_member(self, uid):
        return FakeUser(uid=uid, name=f'User_{uid}')

    async def fetch_member(self, uid):
        return FakeUser(uid=uid, name=f'User_{uid}')


class FakeThread:
    """Fake-Thread fuer create_thread (Wochenpost etc.)."""
    _counter = 0
    def __init__(self, name='thread'):
        FakeThread._counter += 1
        self.id = 100000 + FakeThread._counter
        self.name = name
        self.sent = []

    async def send(self, content=None, **kwargs):
        msg = FakeMessage(content=content, **kwargs)
        self.sent.append(msg)
        return msg


class FakeChannel:
    def __init__(self, channel_id=99999):
        self.id = channel_id
        self.sent = []
        self.threads = []

    async def send(self, content=None, **kwargs):
        msg = FakeMessage(content=content, **kwargs)
        self.sent.append(msg)
        return msg

    async def create_thread(self, name='thread', **kwargs):
        thread = FakeThread(name=name)
        self.threads.append(thread)
        return thread


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
    _patch_file_constant('commands.wochenpost', 'WOCHENPOST_FILE', tmpdir)
    _patch_file_constant('commands.wochenpost', 'WOCHENPOST_SUB_FILE', tmpdir)
    _patch_file_constant('commands.chat', 'CHAT_FILE', tmpdir)
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
import commands.wochenpost as wochenpost_mod
import commands.wochenpost_buttons as wp_buttons_mod
import commands.turnier_buttons as turnier_buttons_mod
import commands.chat as chat_mod

# bot.py importieren (ruft am Ende bot.run() auf, was jetzt ein no-op ist)
import bot as bot_mod

# setup() fuer alle Command-Module nochmal ausfuehren, damit die Commands
# im _captured_commands Dict landen (bot.py hat sie schon mit dem
# _CapturingTree registriert)
_cap_bot = _CapturingBot()
for mod in (elo_mod, resourcen_mod, youtube_mod, wanted_mod,
            release_notes_mod, reminder_mod, schachrallye_mod, wochenpost_mod,
            chat_mod):
    if mod is schachrallye_mod:
        mod.setup(_cap_bot, tournament_channel_id=0)
    elif mod is wochenpost_mod:
        mod.setup(_cap_bot, wochenpost_channel_id=0)
    else:
        mod.setup(_cap_bot)

# bot.py-interne Helper merken
_help_fields_fn = bot_mod._help_fields
