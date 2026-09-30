"""/help: Befehlsübersicht, generiert aus den registrierten Slash-Befehlen.

Name, Beschreibung und Parameter kommen aus der Registrierung selbst (``description=`` und
``@describe``) – dieselben Texte, die Discord im Befehlsmenü zeigt. Es gibt keine zweite,
händisch gepflegte Liste mehr, die vom Befehlsbestand abdriften kann.

Den Bereich legt jeder Befehl bei der Registrierung fest: ``extras={'help': '<bereich>'}``
mit einem Schlüssel aus ``BEREICHE``; ``None`` blendet ihn aus (abgelöste Hinweis-Stubs).
``tests/test_cmd_info.py`` prüft, dass jeder registrierte Befehl einen gültigen Bereich trägt.

Gezeigt wird nur, was der Aufrufer wirklich ausführen kann (``core.permissions.can_run``):
Admin-Befehle tragen ``default_permissions(administrator=True)`` – Discord bietet sie Moderatoren
ohne Administrator-Recht gar nicht an, also listet sie die Hilfe dort auch nicht.
"""

import discord

from core.permissions import can_run
from core.version import VERSION, EMBED_COLOR

HELP_KEY = 'help'
ADMIN = 'admin'
# Reihenfolge = Reihenfolge in der Übersicht.
BEREICHE = {
    'puzzle': '🧩 Puzzles',
    'bibliothek': '📚 Bibliothek',
    'community': '🌐 Community',
    'info': 'ℹ️ Info',
    ADMIN: '🔧 Admin',
}

_FIELD_MAX = 1024  # Discord-Limit je Embed-Feld

_tree = None
_guild_id = 0


def area_of(cmd):
    """Bereich eines Befehls aus ``extras['help']`` (``None`` = nicht in /help)."""
    return (getattr(cmd, 'extras', None) or {}).get(HELP_KEY)


def registered_commands(tree=None, guild_id=None) -> list:
    """Alle registrierten Slash-Befehle, nach Name sortiert.

    Nach ``_sync_commands`` liegen die Befehle der Heim-Guild nur noch in deren Guild-Kopie,
    global bleibt nur ``/puzzle`` – deshalb werden globale und Guild-Befehle vereinigt."""
    tree = _tree if tree is None else tree
    if tree is None:
        return []
    gid = _guild_id if guild_id is None else guild_id
    cmds = list(tree.get_commands())
    if gid:
        cmds += list(tree.get_commands(guild=discord.Object(id=gid)))
    by_name = {}
    for c in cmds:
        # Nur Slash-Befehle (Kontextmenüs/Gruppen haben keine eigene Parameterliste).
        if getattr(c, 'name', None) and hasattr(c, 'parameters'):
            by_name.setdefault(c.name, c)
    return [by_name[n] for n in sorted(by_name)]


def _signature(cmd) -> str:
    parts = [f'/{cmd.name}']
    for p in cmd.parameters:
        name = getattr(p, 'display_name', None) or p.name
        parts.append(f'<{name}>' if p.required else f'[{name}]')
    return ' '.join(parts)


def _body(cmd) -> str:
    lines = [cmd.description or '']
    for p in cmd.parameters:
        desc = (p.description or '').strip()
        if desc and desc != '…':  # discord.py-Platzhalter für Parameter ohne @describe
            name = getattr(p, 'display_name', None) or p.name
            lines.append(f'`{name}` — {desc}')
    return '\n'.join(lines)[:_FIELD_MAX]


def everyone_can_run(cmd) -> bool:
    """Sicht eines Mitglieds ohne besondere Rechte: kein Admin-Bereich, keine Rechte-Sperre."""
    required = getattr(cmd, 'default_permissions', None)
    return area_of(cmd) != ADMIN and not getattr(required, 'value', 0)


def viewer_filter(interaction):
    """Filter „darf der Aufrufer diesen Befehl ausführen?“ für /help."""
    return lambda cmd: can_run(interaction, cmd, privileged_only=area_of(cmd) == ADMIN)


def visible_areas(allowed=None, commands=None) -> list[str]:
    """Bereiche, die für den Aufrufer mindestens einen Befehl enthalten."""
    return [b for b in BEREICHE if help_fields(b, allowed, commands)[1]]


def help_fields(bereich: str, allowed=None,
                commands=None) -> tuple[str, list[tuple[str, str]]]:
    """(Titel, [(Signatur, Beschreibung), ...]) für einen Bereich; unbekannt/leer → ('', []).

    ``allowed(cmd) -> bool`` filtert auf die Befehle, die der Aufrufer ausführen darf
    (Standard: ``everyone_can_run``)."""
    bereich = (bereich or '').lower().strip()
    if bereich not in BEREICHE:
        return '', []
    allowed = allowed or everyone_can_run
    cmds = registered_commands() if commands is None else commands
    fields = [(_signature(c), _body(c)) for c in cmds if area_of(c) == bereich and allowed(c)]
    return (BEREICHE[bereich], fields) if fields else ('', [])


def build_help_embed(bereich: str, allowed=None, commands=None):
    """Embed für /help (Übersicht ohne Bereich) oder ``None`` bei unbekanntem Bereich."""
    bereich = (bereich or '').lower().strip()
    cmds = registered_commands() if commands is None else commands
    if bereich:
        title, fields = help_fields(bereich, allowed, cmds)
        if not fields:
            return None
        embed = discord.Embed(title=title, color=EMBED_COLOR)
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)
    else:
        embed = discord.Embed(title='♟️ Schach-Bot — Hilfe', color=EMBED_COLOR,
                              description='Nutze `/help bereich:…` für Details.')
        for b in BEREICHE:
            _title, fields = help_fields(b, allowed, cmds)
            if fields:
                names = ' '.join(f'`{sig.split()[0]}`' for sig, _ in fields)
                embed.add_field(name=f'{BEREICHE[b].split()[0]} {b}', value=names[:_FIELD_MAX],
                                inline=False)
    embed.set_footer(text=f'Schach-Bot v{VERSION}')
    return embed


def setup(bot, guild_id: int = 0):
    """Registriert /help; merkt sich den Befehlsbaum für die generierte Übersicht."""
    global _tree, _guild_id
    _tree = bot.tree
    _guild_id = guild_id

    @bot.tree.command(name='help', description='Verfügbare Befehle anzeigen',
                      extras={HELP_KEY: 'info'})
    @discord.app_commands.describe(bereich='Bereich: puzzle, bibliothek, community, info, admin')
    async def cmd_help(interaction: discord.Interaction, bereich: str = ''):
        allowed = viewer_filter(interaction)
        embed = build_help_embed(bereich, allowed)
        if embed is None:
            verfuegbar = ' · '.join(f'`{b}`' for b in visible_areas(allowed))
            await interaction.response.send_message(
                f'Unbekannter Bereich `{bereich.lower().strip()}`. Verfügbar: {verfuegbar}',
                ephemeral=True)
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)
