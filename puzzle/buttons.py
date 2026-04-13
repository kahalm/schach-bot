"""Button-basierte Reaktionen für Puzzle-Nachrichten.

Jede Puzzle-Nachricht bekommt eine ``PuzzleView`` mit 6 Buttons
(✅ ❌ 👍 👎 🚮 ☠️). Counter starten bei 0 und zählen pro User
*einmalig* hoch (Toggle: zweiter Klick desselben Users entfernt seine
Stimme wieder). ☠️ ist Admin-only.

Die Button-Counter sind in-memory; nach einem Restart starten sie wieder
bei 0. Die vollständige Historie liegt im Append-Only-Log
``config/reaction_log.jsonl`` (siehe ``core/event_log``).

Persistente View: ``bot.add_view(PuzzleView())`` in ``on_ready`` sorgt
dafür, dass Klicks auf bereits existierende Puzzle-Nachrichten auch nach
einem Restart funktionieren.
"""

import logging

import discord
from discord import ui

log = logging.getLogger('schach-bot')

# Button-Reihen (Discord erlaubt max. 5 Buttons pro Reihe)
_BUTTONS: list[tuple[str, discord.ButtonStyle, int]] = [
    ('✅', discord.ButtonStyle.success,   0),
    ('❌', discord.ButtonStyle.danger,    0),
    ('👍', discord.ButtonStyle.secondary, 0),
    ('👎', discord.ButtonStyle.secondary, 0),
    ('🚮', discord.ButtonStyle.danger,    1),
    ('☠️', discord.ButtonStyle.danger,    1),
]

# msg_id → emoji → set[user_id]
_clicks: dict[int, dict[str, set[int]]] = {}


def _is_admin(bot: discord.Client, user_id: int) -> bool:
    """Prüft, ob der User in irgendeinem Guild Administrator ist."""
    for guild in bot.guilds:
        member = guild.get_member(user_id)
        if member and member.guild_permissions.administrator:
            return True
    return False


def _count(msg_id: int, emoji: str) -> int:
    return len(_clicks.get(msg_id, {}).get(emoji, set()))


def _toggle(msg_id: int, emoji: str, user_id: int) -> int:
    """Toggle: gibt +1 zurück wenn hinzugefügt, -1 wenn entfernt."""
    by_emoji = _clicks.setdefault(msg_id, {})
    users    = by_emoji.setdefault(emoji, set())
    if user_id in users:
        users.remove(user_id)
        return -1
    users.add(user_id)
    return +1


def _build_view(msg_id: int | None = None) -> 'PuzzleView':
    """Erzeugt eine View mit aktuellen Counter-Labels für msg_id (oder leer)."""
    view = PuzzleView()
    for child in view.children:
        if isinstance(child, ui.Button) and child.emoji is not None:
            emoji_str = str(child.emoji)
            n = _count(msg_id, emoji_str) if msg_id else 0
            child.label = str(n)
    return view


def fresh_view() -> 'PuzzleView':
    """Frische View mit allen Countern auf 0 – fürs Posten neuer Puzzles."""
    return _build_view(None)


async def _handle_click(interaction: discord.Interaction, emoji: str):
    # Lazy-Import um Zirkular-Imports zu vermeiden
    from puzzle import legacy as _legacy
    from core import event_log, stats

    bot      = interaction.client
    msg_id   = interaction.message.id
    user_id  = interaction.user.id
    line_id  = _legacy.get_puzzle_line_id(msg_id)
    mode     = _legacy.get_puzzle_mode(msg_id) or 'normal'

    # Admin-Gate für ☠️
    if emoji == '☠️' and not _is_admin(bot, user_id):
        await interaction.response.send_message(
            '🔒 Nur Admins können ganze Kapitel ignorieren.', ephemeral=True)
        return

    delta = _toggle(msg_id, emoji, user_id)

    event_log.log_reaction(user_id, line_id, mode, emoji, delta=delta)
    stats.inc(user_id, f'reaction_{emoji}', delta)

    # View mit aktualisierten Labels zurücksenden
    new_view = _build_view(msg_id)
    await interaction.response.edit_message(view=new_view)

    # --- Side Effects ---

    # 🚮 Puzzle ignorieren / wieder aktivieren
    if emoji == '🚮' and line_id:
        try:
            dm = await interaction.user.create_dm()
            if delta > 0:
                _legacy.ignore_puzzle(line_id)
                await dm.send(f'🚮 Puzzle ignoriert und wird nicht mehr erscheinen:\n`{line_id}`')
            else:
                _legacy.unignore_puzzle(line_id)
                await dm.send(f'♻️ Puzzle wieder aktiviert:\n`{line_id}`')
        except Exception as e:
            log.warning('🚮-DM fehlgeschlagen: %s', e)
        # Im Thread: Ersatz-Puzzle posten (nur beim Hinzufügen)
        if delta > 0 and isinstance(interaction.channel, discord.Thread):
            try:
                await interaction.channel.send('🚮 Sorry für das schlechte Puzzle! Hier kommt ein neues:')
                await _legacy.post_puzzle(interaction.channel)
            except Exception as e:
                log.warning('Ersatz-Puzzle fehlgeschlagen: %s', e)

    # ☠️ Ganzes Kapitel ignorieren / wieder aktivieren
    if emoji == '☠️' and line_id:
        chap = _legacy.get_chapter_from_line_id(line_id)
        if chap:
            book_filename, prefix = chap
            try:
                dm = await interaction.user.create_dm()
                name = book_filename.removesuffix('_firstkey.pgn').removesuffix('.pgn')
                if delta > 0:
                    _legacy.ignore_chapter(book_filename, prefix)
                    await dm.send(
                        f'☠️ Kapitel **{prefix}** in **{name}** ignoriert. '
                        'Alle Linien dieses Kapitels werden nicht mehr gepostet.')
                else:
                    _legacy.unignore_chapter(book_filename, prefix)
                    await dm.send(f'♻️ Kapitel **{prefix}** in **{name}** wieder aktiviert.')
            except Exception as e:
                log.warning('☠️-DM fehlgeschlagen: %s', e)

    # Endless: nach ✅/❌ nächstes Puzzle senden (nur beim Hinzufügen)
    if delta > 0 and emoji in ('✅', '❌') and _legacy.is_endless(user_id):
        try:
            await _legacy.post_next_endless(bot, user_id)
        except Exception as e:
            log.warning('Endless-Next fehlgeschlagen: %s', e)


def _make_callback(emoji: str):
    async def cb(interaction: discord.Interaction):
        await _handle_click(interaction, emoji)
    return cb


class PuzzleView(ui.View):
    """Persistente View mit den 6 Reaktions-Buttons."""

    def __init__(self):
        super().__init__(timeout=None)
        for emoji, style, row in _BUTTONS:
            btn = ui.Button(
                style=style,
                emoji=emoji,
                label='0',
                custom_id=f'puzzle:{emoji}',
                row=row,
            )
            btn.callback = _make_callback(emoji)
            self.add_item(btn)
