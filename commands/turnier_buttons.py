"""Persistente Button-View fuer Turnier-Review-DMs.

Admins/Mods subscriben sich als Reviewer (/turnier_review).
Neue Turniere werden per DM mit Approve/Reject-Buttons vorgelegt.
"""

import asyncio
import logging

import discord
from discord import ui

from core.json_store import atomic_read, atomic_update

log = logging.getLogger('schach-bot')

# Wird von schachrallye.setup() gesetzt
_bot = None
_tournament_channel_id = 0


def configure(bot, tournament_channel_id: int):
    global _bot, _tournament_channel_id
    _bot = bot
    _tournament_channel_id = tournament_channel_id


def _make_callback(action: str):
    async def cb(interaction: discord.Interaction):
        await _handle_review(interaction, action)
    return cb


class TurnierReviewView(ui.View):
    """Persistente View mit Approve/Reject fuer Review-DMs."""

    def __init__(self):
        super().__init__(timeout=None)
        approve = ui.Button(
            style=discord.ButtonStyle.success,
            label='Freigeben',
            custom_id='turnier_review:approve',
            row=0,
        )
        approve.callback = _make_callback('approve')
        self.add_item(approve)

        reject = ui.Button(
            style=discord.ButtonStyle.danger,
            label='Ablehnen',
            custom_id='turnier_review:reject',
            row=0,
        )
        reject.callback = _make_callback('reject')
        self.add_item(reject)


def _disabled_view() -> TurnierReviewView:
    """View mit deaktivierten Buttons (nach Entscheidung)."""
    view = TurnierReviewView()
    for child in view.children:
        if isinstance(child, ui.Button):
            child.disabled = True
    return view


async def _handle_review(interaction: discord.Interaction, action: str):
    """Callback fuer Approve/Reject-Buttons."""
    # Permission-Check: nur konfigurierte Reviewer duerfen handeln
    from commands.schachrallye import TURNIER_FILE, _fresh_default
    data = atomic_read(TURNIER_FILE, default=dict)
    reviewers = data.get('reviewers', [])
    if reviewers and interaction.user.id not in reviewers:
        await interaction.response.send_message(
            'Du bist kein konfigurierter Reviewer.', ephemeral=True)
        return

    # Event-ID aus Embed-Footer parsen
    msg = interaction.message
    if not msg or not msg.embeds:
        await interaction.response.send_message(
            'Fehler: Nachricht nicht lesbar.', ephemeral=True)
        return

    footer_text = msg.embeds[0].footer.text if msg.embeds[0].footer else ''
    if not footer_text or not footer_text.startswith('Event #'):
        await interaction.response.send_message(
            'Fehler: Event-ID nicht gefunden.', ephemeral=True)
        return

    try:
        event_id = int(footer_text.replace('Event #', ''))
    except ValueError:
        await interaction.response.send_message(
            'Fehler: Event-ID ungueltig.', ephemeral=True)
        return

    await interaction.response.defer()

    if action == 'approve':
        event_data = [None]

        def _approve(data):
            if not isinstance(data, dict) or 'events' not in data:
                data = _fresh_default()
            for e in data['events']:
                if e['id'] == event_id:
                    e['approved'] = True
                    event_data[0] = dict(e)
                    return data
            return data

        atomic_update(TURNIER_FILE, _approve)

        if event_data[0] is None:
            embed = msg.embeds[0]
            embed.colour = 0x95a5a6
            embed.title = (embed.title or '') + ' — bereits bearbeitet'
            await interaction.edit_original_response(
                embed=embed, view=_disabled_view())
            return

        # Channel-Post
        try:
            from commands.schachrallye import _post_approved_event
            await _post_approved_event(event_data[0])
        except Exception:
            log.exception('Channel-Post nach Approve fehlgeschlagen (Event #%d)', event_id)

        # DM editieren
        embed = msg.embeds[0]
        embed.colour = 0x2ecc71
        embed.title = (embed.title or '') + ' — freigegeben'
        await interaction.edit_original_response(
            embed=embed, view=_disabled_view())

    elif action == 'reject':
        found = [False]

        def _reject(data):
            if not isinstance(data, dict) or 'events' not in data:
                return _fresh_default()
            before = len(data['events'])
            data['events'] = [e for e in data['events'] if e['id'] != event_id]
            found[0] = len(data['events']) < before
            return data

        atomic_update(TURNIER_FILE, _reject)

        if not found[0]:
            embed = msg.embeds[0]
            embed.colour = 0x95a5a6
            embed.title = (embed.title or '') + ' — bereits bearbeitet'
            await interaction.edit_original_response(
                embed=embed, view=_disabled_view())
            return

        embed = msg.embeds[0]
        embed.colour = 0xe74c3c
        embed.title = (embed.title or '') + ' — abgelehnt'
        await interaction.edit_original_response(
            embed=embed, view=_disabled_view())
