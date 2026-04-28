"""Zentrale Berechtigungspruefung und User-Hilfsfunktionen."""

import discord

_MODERATOR_ROLE = 'moderator'
_guild_id = 0


def set_guild_id(gid: int):
    """Setzt die Heim-Server-ID fuer DM-Berechtigungen."""
    global _guild_id
    _guild_id = gid


def display_name_cached(bot, uid, guild=None):
    """Server-Nick aus Cache (kein API-Call), Fallback auf globalen User-Cache.

    Bevorzugt bei fehlender Guild den Heim-Server (GUILD_ID) fuer Namensaufloesung.
    """
    uid_int = int(uid)
    if guild:
        guilds = [guild]
    elif _guild_id:
        home = bot.get_guild(_guild_id)
        guilds = ([home] if home else []) + list(bot.guilds)
    else:
        guilds = bot.guilds
    for g in guilds:
        if g is None:
            continue
        member = g.get_member(uid_int)
        if member:
            return member.display_name
    u = bot.get_user(uid_int)
    return u.display_name if u else f'User {uid}'


def is_privileged(interaction: discord.Interaction) -> bool:
    """True wenn der User Server-Admin ist oder die Moderator-Rolle hat.

    Im DM-Kontext wird bei gesetzter GUILD_ID der Heim-Server nachgeschlagen.
    """
    member = interaction.user
    if not isinstance(member, discord.Member):
        guild = interaction.guild or (
            interaction.client.get_guild(_guild_id) if _guild_id else None)
        if guild:
            member = guild.get_member(interaction.user.id)
        if not isinstance(member, discord.Member):
            return False
    if member.guild_permissions.administrator:
        return True
    return any(r.name.lower() == _MODERATOR_ROLE for r in member.roles)
