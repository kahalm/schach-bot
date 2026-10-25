"""Slash-Command-Sync: Haupt-Guild bekommt alle Befehle, global nur die ``PUBLIC_COMMANDS``.

Aufgerufen aus ``bot.on_ready`` (mit Wiederholungen); frueher ``bot._sync_commands``.
"""

import discord

# Commands, die in JEDER Guild verfuegbar sein sollen (global registriert). Alle uebrigen
# Commands werden nur in der Haupt-Guild (GUILD_ID) registriert — so bietet der Bot in
# zusaetzlichen Guilds (2. Server fuer gespiegelte Daily-Posts) nur das Tagespuzzle (Auto-Post)
# und `/puzzle` an, sonst nichts.
PUBLIC_COMMANDS = {'puzzle'}


async def sync_commands(tree, guild_id: int):
    """Synchronisiert die Slash-Commands gemaess PUBLIC_COMMANDS.

    Ist GUILD_ID gesetzt: Haupt-Guild bekommt ALLE Commands (guild-scoped, sofort sichtbar),
    global bleiben nur die PUBLIC_COMMANDS → in allen anderen Guilds ist nur `/puzzle` da
    (plus die Daily-Auto-Posts). `/puzzle` wird aus der Guild-Kopie entfernt, damit es in der
    Haupt-Guild nicht doppelt (global + guild) erscheint.
    Ohne GUILD_ID: globaler Sync aller Commands (wie bisher)."""
    if not guild_id:
        await tree.sync()
        return
    guild = discord.Object(id=guild_id)
    tree.copy_global_to(guild=guild)
    for name in PUBLIC_COMMANDS:
        tree.remove_command(name, guild=guild)  # bleibt global → kein Duplikat in der Haupt-Guild
    await tree.sync(guild=guild)
    # Global nur die PUBLIC_COMMANDS behalten und pushen (entfernt die uebrigen aus Zusatz-Guilds).
    for cmd in list(tree.get_commands()):
        if cmd.name not in PUBLIC_COMMANDS:
            tree.remove_command(cmd.name)
    await tree.sync()
