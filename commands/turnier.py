"""Turnier-Befehle: /turnier, /turnier_sub, /turnier_unsub, /turnier_parse, /turnier_review,
/turnier_pending.

Je Befehl eine Funktion; Name, Beschreibung und Hilfe-Bereich registriert
``commands/schachrallye.py`` (``setup``). Import/Review-DMs: ``commands/turnier_loops.py``,
Daten: ``commands/turnier_store.py``.
"""

import logging
from datetime import date

import discord

from commands import termine, turnier_loops, turnier_store
from core.permissions import is_privileged, require_privileged
from core.version import EMBED_COLOR

log = logging.getLogger('schach-bot')


@discord.app_commands.describe(
    tag='Tag fuer den du gepingt werden willst (z.B. schnellschach, blitz, 960, klassisch, jugend, senioren)',
    user='Anderen User subscriben (nur Admin)')
async def cmd_turnier_sub(interaction: discord.Interaction,
                          tag: str = '', user: discord.User = None):
    tag = tag.strip().lower()

    # Ohne Tag: eigene Subs anzeigen
    if not tag:
        data = turnier_store.read()
        if not data:
            data = turnier_store._fresh_default()
        subs = data.get('subscribers', {})
        uid = interaction.user.id
        my_tags = sorted(t for t, uids in subs.items() if uid in uids)
        if my_tags:
            tag_list = ', '.join(f'`{t}`' for t in my_tags)
            await interaction.response.send_message(
                f'Deine Turnier-Abos: {tag_list}', ephemeral=True)
        else:
            await interaction.response.send_message(
                'Du hast noch keine Turnier-Tags abonniert.\n'
                'Nutze `/turnier_sub tag:schnellschach` um einen Tag zu abonnieren.',
                ephemeral=True)
        return

    if user and not is_privileged(interaction):
        await interaction.response.send_message(
            '\u26a0\ufe0f Nur Admins koennen andere User subscriben.',
            ephemeral=True)
        return

    target = user or interaction.user
    result = {'already': False}

    def _sub(data):
        if not isinstance(data, dict) or 'subscribers' not in data:
            data = turnier_store._fresh_default()
        subs = data['subscribers'].setdefault(tag, [])
        if target.id in subs:
            result['already'] = True
            return data
        subs.append(target.id)
        return data

    turnier_store.update(_sub)
    if result['already']:
        name = f'**{target.display_name}**' if user else 'Du bist'
        suffix = f'ist bereits fuer `{tag}` subscribed.' if user else f'bereits fuer `{tag}` subscribed.'
        await interaction.response.send_message(
            f'{name} {suffix}', ephemeral=True)
    else:
        if user:
            await interaction.response.send_message(
                f'\u2705 **{target.display_name}** fuer Tag `{tag}` subscribed.',
                ephemeral=True)
        else:
            await interaction.response.send_message(
                f'\u2705 Du wirst bei neuen Turnieren mit Tag `{tag}` gepingt.',
                ephemeral=True)
        # DM an den subscribten User
        try:
            dm = await target.create_dm()
            await dm.send(
                f'Du wurdest fuer den Turnier-Tag **{tag}** angemeldet! '
                f'Bei neuen Turnieren mit diesem Tag wirst du im Channel gepingt.\n'
                f'Mit `/turnier_unsub tag:{tag}` kannst du dich jederzeit abmelden.'
            )
        except discord.Forbidden:
            log.warning('Turnier-Sub-DM an %s nicht moeglich (DMs deaktiviert).', target.id)
        except Exception:
            log.warning('Turnier-Sub-DM an %s fehlgeschlagen.', target.id)


@discord.app_commands.describe(
    tag='Tag den du abbestellen willst (z.B. schnellschach, blitz, 960, schachrallye)',
    user='Anderen User unsubscriben (nur Admin)')
async def cmd_turnier_unsub(interaction: discord.Interaction,
                            tag: str, user: discord.User = None):
    if user and not is_privileged(interaction):
        await interaction.response.send_message(
            '\u26a0\ufe0f Nur Admins koennen andere User unsubscriben.',
            ephemeral=True)
        return

    tag = tag.strip().lower()
    target = user or interaction.user
    result = {'was_subbed': False}

    def _unsub(data):
        if not isinstance(data, dict) or 'subscribers' not in data:
            return data
        subs = data['subscribers'].get(tag, [])
        if target.id in subs:
            subs.remove(target.id)
            result['was_subbed'] = True
        return data

    turnier_store.update(_unsub)
    if result['was_subbed']:
        if user:
            await interaction.response.send_message(
                f'\u2705 **{target.display_name}** von Tag `{tag}` unsubscribed.',
                ephemeral=True)
        else:
            await interaction.response.send_message(
                f'\u2705 Tag `{tag}` abbestellt.',
                ephemeral=True)
    else:
        name = f'**{target.display_name}**' if user else 'Du'
        verb = 'war' if user else 'warst'
        await interaction.response.send_message(
            f'{name} {verb} nicht fuer `{tag}` subscribed.', ephemeral=True)


@discord.app_commands.default_permissions(administrator=True)
async def cmd_turnier_parse(interaction: discord.Interaction):
    if not await require_privileged(interaction):
        return
    await interaction.response.defer(ephemeral=True)
    try:
        added = await turnier_loops.parse_and_store()
    except Exception as e:
        log.exception('turnier_parse fehlgeschlagen')
        await interaction.followup.send(
            f'\u274c Fehler beim Laden von {turnier_loops.RALLYE_URL}: {e}', ephemeral=True)
        return

    if added:
        rallye_added = [a for a in added if 'schachrallye' in a.get('tags', [])]
        turnier_added = [a for a in added if 'schachrallye' not in a.get('tags', [])]
        parts = []
        if rallye_added:
            lines = [termine._format_turnier_line(a) for a in rallye_added]
            parts.append(f"**Rallye** \u2014 {len(rallye_added)} neu (pending):\n" + '\n'.join(lines))
        if turnier_added:
            lines = [termine._format_turnier_line(a) for a in turnier_added]
            parts.append(f"**Turniere** \u2014 {len(turnier_added)} neu (pending):\n" + '\n'.join(lines))
        desc = '\n\n'.join(parts)
        if len(desc) > 4096:
            desc = desc[:4093] + '...'
        embed = discord.Embed(
            title='\u2705 Import abgeschlossen',
            description=desc,
            color=EMBED_COLOR,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(
            'Alle Termine bereits vorhanden \u2014 keine neuen hinzugefuegt.',
            ephemeral=True)


async def cmd_turnier(interaction: discord.Interaction):
    data = turnier_store.read()
    if not data:
        data = turnier_store._fresh_default()
    events = data.get('events', [])

    today = date.today()
    future = [e for e in events
              if (termine._parse_stored(e['datum']) or date.min) >= today
              and e.get('approved', True) is not False]
    future.sort(key=lambda e: e['datum'])

    if not future:
        await interaction.response.send_message(
            'Keine anstehenden Turniere vorhanden. '
            'Ein Admin kann mit `/turnier_parse` Termine importieren.',
            ephemeral=True)
        return

    lines = [termine._format_turnier_line(e) for e in future]
    desc = '\n'.join(lines)
    if len(desc) > 4096:
        desc = desc[:4093] + '...'

    embed = discord.Embed(
        title='\U0001f3c6 Turniere \u2014 Tirol',
        description=desc,
        color=EMBED_COLOR,
    )
    embed.set_footer(text='Quelle: tirol.chess.at/termine/')
    await interaction.response.send_message(embed=embed, ephemeral=True)


@discord.app_commands.default_permissions(administrator=True)
async def cmd_turnier_review(interaction: discord.Interaction):
    if not await require_privileged(interaction):
        return

    uid = interaction.user.id
    result = {'action': ''}

    def _toggle(data):
        if not isinstance(data, dict) or 'events' not in data:
            data = turnier_store._fresh_default()
        reviewers = data.setdefault('reviewers', [])
        if uid in reviewers:
            reviewers.remove(uid)
            result['action'] = 'unsub'
        else:
            reviewers.append(uid)
            result['action'] = 'sub'
        return data

    turnier_store.update(_toggle)

    if result['action'] == 'sub':
        await interaction.response.send_message(
            '\u2705 Du bist jetzt Turnier-Reviewer. '
            'Neue Turniere muessen von dir freigegeben werden, '
            'bevor sie im Channel gepostet werden.',
            ephemeral=True)
    else:
        await interaction.response.send_message(
            '\u2705 Turnier-Review abbestellt.',
            ephemeral=True)


@discord.app_commands.default_permissions(administrator=True)
async def cmd_turnier_pending(interaction: discord.Interaction):
    if not await require_privileged(interaction):
        return

    data = turnier_store.read()
    if not data:
        data = turnier_store._fresh_default()
    events = data.get('events', [])
    pending = [e for e in events if e.get('approved') is False]

    if not pending:
        await interaction.response.send_message(
            'Keine ausstehenden Turniere.', ephemeral=True)
        return

    from commands.turnier_buttons import TurnierReviewView

    pending.sort(key=lambda e: e.get('datum', ''))
    await interaction.response.defer(ephemeral=True)
    for event in pending:
        embed = turnier_loops._build_pending_embed(event)
        view = TurnierReviewView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
