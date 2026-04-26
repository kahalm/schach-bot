"""Zentrale Berechtigungspruefung: Admin oder Moderator-Rolle."""

import discord

_MODERATOR_ROLE = 'moderator'


def is_privileged(interaction: discord.Interaction) -> bool:
    """True wenn der User Server-Admin ist oder die Moderator-Rolle hat.

    Im DM-Kontext immer False.
    """
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    return any(r.name.lower() == _MODERATOR_ROLE for r in member.roles)
