"""Button-basierte Reaktionen fuer Wochenpost-Nachrichten.

4 Buttons: geschafft/nicht geschafft + gut/schlecht.
Mutex-Paare wie beim Puzzle: nur eins pro Paar, Toggle bei erneutem Klick.
Jeder Klick wird in config/wochenpost_log.jsonl geloggt.
"""

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone

import discord
from discord import ui

from core.button_tracker import ClickTracker
from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

WOCHENPOST_LOG_FILE = os.path.join(CONFIG_DIR, 'wochenpost_log.jsonl')
_log_lock = threading.Lock()

_BUTTONS: list[tuple[str, discord.ButtonStyle]] = [
    ('\u2705', discord.ButtonStyle.success),    # geschafft
    ('\u274c', discord.ButtonStyle.danger),      # nicht geschafft
    ('\U0001f44d', discord.ButtonStyle.secondary),  # gut
    ('\U0001f44e', discord.ButtonStyle.secondary),  # schlecht
]

_MUTEX_PAIRS = {
    '\u2705': '\u274c', '\u274c': '\u2705',
    '\U0001f44d': '\U0001f44e', '\U0001f44e': '\U0001f44d',
}

_CLICKS_CAP = 500
_tracker = ClickTracker(_MUTEX_PAIRS, cap=_CLICKS_CAP)

# Abwaertskompatible Aliases fuer Tests und externe Zugriffe
_clicks = _tracker._clicks
_count = _tracker.count
_apply_click = _tracker.apply_click


def _log_click(user_id: int, post_id: int, emoji: str, delta: int):
    """Schreibt einen Klick ins JSONL-Log."""
    entry = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'user': user_id,
        'post_id': post_id,
        'emoji': emoji,
        'delta': delta,
    }
    try:
        os.makedirs(os.path.dirname(WOCHENPOST_LOG_FILE), exist_ok=True)
        with _log_lock:
            with open(WOCHENPOST_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError as e:
        log.warning('Wochenpost-Log Schreibfehler: %s', e)


def _build_view(msg_id: int | None = None) -> 'WochenpostView':
    view = WochenpostView()
    for child in view.children:
        if isinstance(child, ui.Button) and child.emoji is not None:
            emoji_str = str(child.emoji)
            n = _count(msg_id, emoji_str) if msg_id else 0
            child.label = str(n)
    return view


def fresh_view() -> 'WochenpostView':
    """Frische View mit Countern auf 0 — fuers Posten neuer Wochenposts."""
    return _build_view(None)


async def _handle_click(interaction: discord.Interaction, emoji: str):
    msg_id = interaction.message.id
    user_id = interaction.user.id

    delta, removed = _apply_click(msg_id, emoji, user_id)

    try:
        await interaction.response.defer()
    except discord.errors.InteractionResponded:
        pass

    asyncio.create_task(_run_side_effects(
        interaction, msg_id, user_id, emoji, delta, removed))


async def _run_side_effects(interaction: discord.Interaction,
                            msg_id: int, user_id: int,
                            emoji: str, delta: int, removed: str | None):
    try:
        try:
            new_view = _build_view(msg_id)
            await interaction.edit_original_response(view=new_view)
        except Exception as e:
            log.warning('Wochenpost-View-Update fehlgeschlagen: %s', e)

        if removed:
            await asyncio.to_thread(_log_click, user_id, msg_id, removed, -1)
        await asyncio.to_thread(_log_click, user_id, msg_id, emoji, delta)

        # Resolution-Tracking fuer Wochenpost-Abo
        if emoji in ('\u2705', '\u274c'):
            try:
                from commands.wochenpost import _entry_id_for_msg, update_resolution
                entry_id = await asyncio.to_thread(_entry_id_for_msg, msg_id)
                if entry_id is not None:
                    by_emoji = _clicks.get(msg_id, {})
                    is_resolved = (user_id in by_emoji.get('\u2705', set())
                                   or user_id in by_emoji.get('\u274c', set()))
                    await asyncio.to_thread(
                        update_resolution, entry_id, user_id, is_resolved)
            except Exception:
                log.warning('Wochenpost resolution-tracking fehlgeschlagen '
                            '(user=%s, msg=%s)', user_id, msg_id)
    except Exception:
        log.exception('Wochenpost-Button side-effect crash (user=%s, emoji=%s)',
                      user_id, emoji)


def _make_callback(emoji: str):
    async def cb(interaction: discord.Interaction):
        await _handle_click(interaction, emoji)
    return cb


class WochenpostView(ui.View):
    """Persistente View mit 4 Reaktions-Buttons."""

    def __init__(self):
        super().__init__(timeout=None)
        for emoji, style in _BUTTONS:
            btn = ui.Button(
                style=style,
                emoji=emoji,
                label='0',
                custom_id=f'wochenpost:{emoji}',
                row=0,
            )
            btn.callback = _make_callback(emoji)
            self.add_item(btn)
