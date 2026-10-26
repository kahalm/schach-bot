"""Zentrale Berechtigungspruefung und User-Hilfsfunktionen."""

import discord

_MODERATOR_ROLE = 'moderator'
_guild_id = 0
_moderator_role_id = 0


def set_guild_id(gid: int):
    """Setzt die Heim-Server-ID: Privilegien zaehlen nur dort (auch im DM-Kontext)."""
    global _guild_id
    _guild_id = gid


def set_moderator_role_id(rid: int):
    """Moderator-Rolle per ID (``MODERATOR_ROLE_ID``); 0 = Rueckfall auf den Rollennamen ``moderator``."""
    global _moderator_role_id
    _moderator_role_id = int(rid or 0)


def iter_guilds_home_first(bot, home_only: bool = False):
    """Die EINE Reihenfolge fuer Mitglieder-/Namensaufloesung ueber Guilds.

    Heim-Server (GUILD_ID) zuerst, dann die uebrigen ``bot.guilds`` in deren Reihenfolge,
    jede Guild nur einmal. ``home_only=True``: bei gesetzter GUILD_ID nur der Heim-Server
    (nicht im Cache → nichts); ohne GUILD_ID gibt es keinen Heim-Server, dann alle Guilds.
    """
    home = bot.get_guild(_guild_id) if _guild_id else None
    if home is not None:
        yield home
    if home_only and _guild_id:
        return
    for g in bot.guilds:
        if g is not None and g is not home:
            yield g


def display_name_cached(bot, uid, guild=None):
    """Server-Nick aus Cache (kein API-Call), Fallback auf globalen User-Cache.

    Bevorzugt bei fehlender Guild den Heim-Server (GUILD_ID) fuer Namensaufloesung.
    """
    uid_int = int(uid)
    guilds = [guild] if guild else iter_guilds_home_first(bot)
    for g in guilds:
        if g is None:
            continue
        member = g.get_member(uid_int)
        if member:
            return member.display_name
    u = bot.get_user(uid_int)
    return u.display_name if u else f'User {uid}'


def _member(interaction: discord.Interaction):
    """Der Aufrufer als Guild-Member (im DM-Kontext aus dem Heim-Server) oder ``None``."""
    member = interaction.user
    if not isinstance(member, discord.Member):
        guild = interaction.guild or (
            interaction.client.get_guild(_guild_id) if _guild_id else None)
        if guild:
            member = guild.get_member(interaction.user.id)
        if not isinstance(member, discord.Member):
            return None
    return member


def _home_member(interaction: discord.Interaction):
    """Der Aufrufer als Member des HEIM-Servers (S4-006) oder ``None``.

    Bei gesetzter GUILD_ID zaehlen nur Rechte und Rollen im Heim-Server — auch wenn der Befehl
    in einer anderen Guild laeuft (``/puzzle`` ist global registriert); dort koennte sich jeder
    selbst Admin oder eine Rolle „moderator“ geben. Ohne GUILD_ID wie ``_member``.
    """
    if not _guild_id:
        return _member(interaction)
    user = interaction.user
    if isinstance(user, discord.Member) and getattr(interaction.guild, 'id', None) == _guild_id:
        return user
    home = interaction.client.get_guild(_guild_id)
    member = home.get_member(user.id) if home else None
    return member if isinstance(member, discord.Member) else None


def _is_moderator_role(role) -> bool:
    if _moderator_role_id:
        return getattr(role, 'id', None) == _moderator_role_id
    return role.name.lower() == _MODERATOR_ROLE


def is_privileged(interaction: discord.Interaction) -> bool:
    """True wenn der User Server-Admin ist oder die Moderator-Rolle hat.

    Bei gesetzter GUILD_ID immer am Member des Heim-Servers geprueft (auch im DM-Kontext und
    in fremden Guilds). Moderator-Rolle per ``MODERATOR_ROLE_ID``, sonst per Name ``moderator``.
    """
    member = _home_member(interaction)
    if member is None:
        return False
    if member.guild_permissions.administrator:
        return True
    return any(_is_moderator_role(r) for r in member.roles)


# Die EINE Ablehnung fuer Admin-Befehle (vorher vier Schreibweisen an 13 Stellen).
DENIED_TEXT = '⚠️ Nur für Admins/Moderatoren.'


async def require_privileged(interaction: discord.Interaction) -> bool:
    """Laufzeit-Pruefung fuer Admin-Befehle: True bei Admin/Moderator, sonst ephemere
    Ablehnung (``DENIED_TEXT``) und False. Aufruf: ``if not await require_privileged(i): return``."""
    if is_privileged(interaction):
        return True
    if interaction.response.is_done():
        await interaction.followup.send(DENIED_TEXT, ephemeral=True)
    else:
        await interaction.response.send_message(DENIED_TEXT, ephemeral=True)
    return False


def meets_default_permissions(interaction: discord.Interaction, command) -> bool:
    """True, wenn Discord dem Aufrufer den Befehl anbietet: seine Server-Rechte decken
    ``default_permissions`` des Befehls (Admins immer). Freigaben unter Servereinstellungen →
    Integrationen sieht der Bot nicht – dort geht diese Pruefung vom Standard aus."""
    required = getattr(command, 'default_permissions', None)
    if required is None or not getattr(required, 'value', 0):
        return True
    member = _member(interaction)
    if member is None:
        return False
    perms = member.guild_permissions
    if perms.administrator:
        return True
    return (required.value & ~getattr(perms, 'value', 0)) == 0


def can_run(interaction: discord.Interaction, command, privileged_only: bool = False) -> bool:
    """Darf der Aufrufer ``command`` wirklich ausfuehren? Discord-Sperre
    (``default_permissions``) und – bei ``privileged_only`` – die Laufzeit-Pruefung
    ``is_privileged`` muessen beide durchlassen. Keine Rechteaenderung, nur die Anzeige."""
    if privileged_only and not is_privileged(interaction):
        return False
    return meets_default_permissions(interaction, command)
