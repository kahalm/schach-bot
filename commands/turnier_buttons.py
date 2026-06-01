"""Persistente Button-View fuer Turnier-Review-DMs.

Admins/Mods subscriben sich als Reviewer (/turnier_review).
Neue Turniere werden per DM mit Approve/Reject-Buttons vorgelegt.
Bei Freigabe kann optional ein Spieler-Tagging-Feld ausgefuellt werden.
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


def _resolve_player_names(bot, names: list[str]) -> tuple[list[int], list[str]]:
    """Loest Spielernamen zu Guild-Member-IDs auf (case-insensitive display_name).

    Returns: (gefundene_user_ids, nicht_gefundene_namen)
    """
    # Member-Index einmal aufbauen (display_name.lower -> id), statt pro Name linear
    # ueber alle Guilds/Member zu iterieren (O(Namen * Mitglieder) im Approve-Hotpath).
    # setdefault bewahrt die First-Match-Semantik (erste Guild/erstes Member gewinnt).
    index: dict[str, int] = {}
    for guild in bot.guilds:
        for member in guild.members:
            index.setdefault(member.display_name.lower(), member.id)

    found_ids: list[int] = []
    not_found: list[str] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        mid = index.get(name.lower())
        if mid is not None:
            if mid not in found_ids:
                found_ids.append(mid)
        else:
            not_found.append(name)
    return found_ids, not_found


class TurnierApproveModal(ui.Modal):
    """Modal zum Freigeben eines Turniers mit optionalem Spieler-Tagging."""

    def __init__(self, interaction_message, event_id: int):
        super().__init__(title='Turnier freigeben')
        self._interaction_message = interaction_message
        self._event_id = event_id
        self.players_input = ui.TextInput(
            label='Spieler taggen (optional)',
            placeholder='Max, Lisa, Thomas',
            required=False,
            style=discord.TextStyle.short,
        )
        self.add_item(self.players_input)

    async def on_submit(self, interaction: discord.Interaction):
        await _execute_approve(
            interaction, self._interaction_message, self._event_id,
            self.players_input.value or '')


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

    if action == 'approve':
        # Modal oeffnen statt direkt freizugeben
        modal = TurnierApproveModal(msg, event_id)
        await interaction.response.send_modal(modal)
        return

    # --- Reject ---
    await interaction.response.defer()

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


async def _execute_approve(interaction: discord.Interaction, msg,
                           event_id: int, players_text: str):
    """Fuehrt die Approve-Logik nach Modal-Submit aus."""
    from commands.schachrallye import TURNIER_FILE, _fresh_default

    await interaction.response.defer()

    event_data = [None]

    def _approve(data):
        if not isinstance(data, dict) or 'events' not in data:
            data = _fresh_default()
        for e in data['events']:
            if e['id'] == event_id:
                if e.get('approved') is True:
                    event_data[0] = 'already'  # schon freigegeben -> nicht erneut posten
                    return data
                e['approved'] = True
                event_data[0] = dict(e)
                return data
        return data

    atomic_update(TURNIER_FILE, _approve)

    if event_data[0] is None or event_data[0] == 'already':
        embed = msg.embeds[0]
        embed.colour = 0x95a5a6
        embed.title = (embed.title or '') + ' — bereits bearbeitet'
        await interaction.edit_original_response(
            embed=embed, view=_disabled_view())
        return

    # Spielernamen aufloesen
    extra_ids: set[int] = set()
    not_found: list[str] = []
    player_names: list[str] = []
    if players_text.strip():
        player_names = [n.strip() for n in players_text.split(',') if n.strip()]
        found_ids, not_found = _resolve_player_names(_bot, player_names)
        extra_ids = set(found_ids)

    # Channel-Post
    try:
        from commands.schachrallye import _post_approved_event
        await _post_approved_event(event_data[0],
                                   extra_mention_ids=extra_ids or None)
    except Exception:
        log.exception('Channel-Post nach Approve fehlgeschlagen (Event #%d)', event_id)

    # DM editieren
    embed = msg.embeds[0]
    embed.colour = 0x2ecc71
    title_suffix = ' — freigegeben'
    if player_names:
        resolved = [n for n in player_names if n not in not_found]
        if resolved:
            title_suffix += f' (Spieler: {", ".join(resolved)})'
    embed.title = (embed.title or '') + title_suffix
    if not_found:
        desc = embed.description or ''
        desc += f'\n\u26a0\ufe0f Nicht gefunden: {", ".join(not_found)}'
        embed.description = desc
    await interaction.edit_original_response(
        embed=embed, view=_disabled_view())
