"""Button-basierte Reaktionen für Puzzle-Nachrichten.

Jede Puzzle-Nachricht bekommt eine ``PuzzleView`` mit 5 Buttons
(✅ ❌ 👍 👎 🚮). Counter starten bei 0 und zählen pro User einmalig.

Wechselseitig exklusiv pro User:
* ✅ ↔ ❌  (Lösung: korrekt vs falsch)
* 👍 ↔ 👎  (Bewertung: gut vs schlecht)

Klick auf den Partner schaltet den eigenen Vorgänger automatisch ab.
Erneuter Klick auf dasselbe Emoji nimmt die eigene Stimme wieder zurück.

Die Counter sind in-memory; nach einem Restart starten sie wieder bei 0.
Die vollständige Historie liegt im Append-Only-Log
``config/reaction_log.jsonl`` (siehe ``core/event_log``).

WICHTIG: Button-Interaktionen müssen innerhalb von 3 Sekunden bestätigt
werden, sonst zeigt Discord den Spinner ewig. Wir bestätigen daher SOFORT
via ``edit_message`` und schieben jede File-I/O / langsame Side-Effect-
Arbeit in einen Background-Task (mit ``asyncio.to_thread`` für sync I/O).
"""

import asyncio
import logging

import discord
from discord import ui

log = logging.getLogger('schach-bot')

# Alle 5 Buttons in einer Reihe (Discord-Maximum)
_BUTTONS: list[tuple[str, discord.ButtonStyle, int]] = [
    ('✅', discord.ButtonStyle.success,   0),
    ('❌', discord.ButtonStyle.danger,    0),
    ('👍', discord.ButtonStyle.secondary, 0),
    ('👎', discord.ButtonStyle.secondary, 0),
    ('🚮', discord.ButtonStyle.danger,    0),
]

# Wechselseitig exklusive Paare – Klick auf einen entfernt automatisch den anderen
_MUTEX_PAIRS = {'✅': '❌', '❌': '✅', '👍': '👎', '👎': '👍'}

# msg_id → emoji → set[user_id]
_clicks: dict[int, dict[str, set[int]]] = {}


def _count(msg_id: int, emoji: str) -> int:
    return len(_clicks.get(msg_id, {}).get(emoji, set()))


def _apply_click(msg_id: int, emoji: str, user_id: int
                 ) -> tuple[int, str | None]:
    """Wendet einen Klick an.

    Gibt ``(delta, removed_partner)`` zurück:
    * ``delta`` = +1 wenn die Stimme hinzugefügt, -1 wenn entfernt wurde
    * ``removed_partner`` = das mutex-Partner-Emoji, falls dem User dabei
      die Gegenstimme entzogen wurde, sonst ``None``
    """
    by_emoji = _clicks.setdefault(msg_id, {})

    # Mutex: hat der User die Gegenstimme bereits abgegeben? → entfernen
    removed: str | None = None
    partner = _MUTEX_PAIRS.get(emoji)
    if partner:
        partner_users = by_emoji.get(partner)
        if partner_users and user_id in partner_users:
            partner_users.remove(user_id)
            removed = partner

    # Eigentlicher Toggle
    users = by_emoji.setdefault(emoji, set())
    if user_id in users:
        users.remove(user_id)
        return -1, removed
    users.add(user_id)
    return +1, removed


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

    msg_id   = interaction.message.id
    user_id  = interaction.user.id
    line_id  = _legacy.get_puzzle_line_id(msg_id)
    mode     = _legacy.get_puzzle_mode(msg_id) or 'normal'

    delta, removed = _apply_click(msg_id, emoji, user_id)

    # 1) SOFORT mit defer() bestätigen. Das ist die billigste Quittung und
    #    nutzt NICHT den Message-Edit-Rate-Limit-Bucket – sonst hängt nach
    #    ein paar schnellen Klicks der nächste Klick 30 s an Discord-RL.
    try:
        await interaction.response.defer()
    except discord.errors.InteractionResponded:
        pass  # Race-Edge-Case: schon beantwortet, egal

    # 2) Alles andere (Counter-Edit, Logging, Stats, Endless) als Background-
    #    Task – Klicks bleiben dadurch flüssig.
    asyncio.create_task(_run_side_effects(
        interaction, msg_id, user_id, line_id, mode, emoji, delta, removed))


async def _run_side_effects(interaction: discord.Interaction,
                            msg_id: int, user_id: int,
                            line_id: str | None, mode: str,
                            emoji: str, delta: int, removed: str | None):
    """Side-Effects nach einem Button-Klick – läuft losgelöst vom Handler."""
    from puzzle import legacy as _legacy
    from core import event_log, stats

    bot = interaction.client

    try:
        # Counter-Labels visuell nachziehen (best-effort – darf langsam sein,
        # blockiert nicht den nächsten Klick)
        try:
            new_view = _build_view(msg_id)
            await interaction.edit_original_response(view=new_view)
        except Exception as e:
            log.warning('View-Update fehlgeschlagen: %s', e)

        # Logging + Stats (sync File-I/O → in Thread, blockt sonst Loop)
        if removed:
            await asyncio.to_thread(event_log.log_reaction,
                                    user_id, line_id, mode, removed, -1)
            await asyncio.to_thread(stats.inc,
                                    user_id, f'reaction_{removed}', -1)
        await asyncio.to_thread(event_log.log_reaction,
                                user_id, line_id, mode, emoji, delta)
        await asyncio.to_thread(stats.inc,
                                user_id, f'reaction_{emoji}', delta)

        # 🚮 Puzzle ignorieren / wieder aktivieren
        if emoji == '🚮' and line_id:
            try:
                dm = await interaction.user.create_dm()
                if delta > 0:
                    await asyncio.to_thread(_legacy.ignore_puzzle, line_id)
                    await dm.send(f'🚮 Puzzle ignoriert und wird nicht mehr erscheinen:\n`{line_id}`')
                else:
                    await asyncio.to_thread(_legacy.unignore_puzzle, line_id)
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

        # Endless: nach ✅/❌ nächstes Puzzle senden (nur beim Hinzufügen)
        if delta > 0 and emoji in ('✅', '❌') and _legacy.is_endless(user_id):
            try:
                await _legacy.post_next_endless(bot, user_id)
            except Exception as e:
                log.warning('Endless-Next fehlgeschlagen: %s', e)
    except Exception:
        log.exception('Side-effect crash nach Button-Klick')


def _make_callback(emoji: str):
    async def cb(interaction: discord.Interaction):
        await _handle_click(interaction, emoji)
    return cb


class PuzzleView(ui.View):
    """Persistente View mit den 5 Reaktions-Buttons."""

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
