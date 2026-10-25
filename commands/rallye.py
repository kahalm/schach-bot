"""Schachrallye-Befehle: /schachrallye, /schachrallye_add, _del, _sub, _unsub.

Je Befehl eine Funktion; Name, Beschreibung und Hilfe-Bereich registriert
``commands/schachrallye.py`` (``setup``). Daten: ``commands/turnier_store.py``.
"""

import logging
from datetime import date

import discord

from commands import termine, turnier_store
from core.datetime_utils import noon_utc_ts as _noon_utc_ts
from core.datetime_utils import parse_datum as _parse_datum
from core.permissions import is_privileged, require_privileged
from core.version import EMBED_COLOR

log = logging.getLogger('schach-bot')


async def cmd_schachrallye(interaction: discord.Interaction):
    data = turnier_store.read()
    if not data:
        data = turnier_store._fresh_default()
    events = data.get('events', [])
    subs = data.get('subscribers', {}).get('schachrallye', [])

    today = date.today()
    future = [e for e in events
              if 'schachrallye' in e.get('tags', [])
              and (termine._parse_stored(e['datum']) or date.min) >= today]
    future.sort(key=lambda e: e['datum'])

    if not future:
        await interaction.response.send_message(
            'Keine anstehenden Schachrallye-Termine vorhanden.',
            ephemeral=True)
        return

    lines = []
    for e in future:
        d = termine._parse_stored(e['datum'])
        ts = _noon_utc_ts(d)
        name = e.get('name', '')
        ort = termine._shorten_ort(e.get('ort', ''))
        if name:
            line = f"**#{e['id']}** \u2014 <t:{ts}:D> **{name}**"
        else:
            line = f"**#{e['id']}** \u2014 <t:{ts}:D>"
        if ort:
            line += f" \u00b7 {ort}"
        lines.append(line)

    desc = '\n'.join(lines)
    if subs:
        mentions = ', '.join(f'<@{uid}>' for uid in subs)
        desc += f'\n\n**Subscriber ({len(subs)}):** {mentions}'

    embed = discord.Embed(
        title='\U0001f3c7 Schachrallye \u2014 Termine',
        description=desc,
        color=EMBED_COLOR,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@discord.app_commands.describe(
    datum='Datum im Format TT.MM.JJJJ',
    ort='Ort des Turniers',
)
@discord.app_commands.default_permissions(administrator=True)
async def cmd_schachrallye_add(interaction: discord.Interaction,
                               datum: str, ort: str):
    if not await require_privileged(interaction):
        return
    d = _parse_datum(datum)
    if d is None:
        await interaction.response.send_message(
            '\u26a0\ufe0f Ungueltiges Datum. Format: `TT.MM.JJJJ` (z.B. 15.05.2026)',
            ephemeral=True)
        return
    if d < date.today():
        await interaction.response.send_message(
            '\u26a0\ufe0f Das Datum liegt in der Vergangenheit.',
            ephemeral=True)
        return

    result = {}

    def _add(data):
        if not isinstance(data, dict) or 'events' not in data:
            data = turnier_store._fresh_default()
        new_id = data.get('next_id', 1)
        data['events'].append({
            'id': new_id,
            'datum': d.strftime('%Y-%m-%d'),
            'datum_text': datum.strip(),
            'name': '',
            'ort': ort,
            'link': '',
            'tags': ['schachrallye'],
            'reminded': False,
        })
        data['next_id'] = new_id + 1
        result['id'] = new_id
        return data

    turnier_store.update(_add)
    ts = _noon_utc_ts(d)
    await interaction.response.send_message(
        f"\u2705 Termin #{result['id']} angelegt: <t:{ts}:D> in **{ort}**",
        ephemeral=True)


@discord.app_commands.describe(id='ID des Termins (aus /schachrallye)')
@discord.app_commands.default_permissions(administrator=True)
async def cmd_schachrallye_del(interaction: discord.Interaction, id: int):
    if not await require_privileged(interaction):
        return
    result = {'found': False}

    def _del(data):
        if not isinstance(data, dict) or 'events' not in data:
            return data
        before = len(data['events'])
        data['events'] = [e for e in data['events'] if e['id'] != id]
        if len(data['events']) < before:
            result['found'] = True
        return data

    turnier_store.update(_del)
    if result['found']:
        await interaction.response.send_message(
            f'\u2705 Termin #{id} geloescht.', ephemeral=True)
    else:
        await interaction.response.send_message(
            f'\u274c Termin #{id} nicht gefunden.', ephemeral=True)


@discord.app_commands.describe(
    user='Anderen User subscriben (nur Admin)')
async def cmd_schachrallye_sub(interaction: discord.Interaction,
                               user: discord.User = None):
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
        subs = data['subscribers'].setdefault('schachrallye', [])
        if target.id in subs:
            result['already'] = True
            return data
        subs.append(target.id)
        return data

    turnier_store.update(_sub)
    if result['already']:
        name = f'**{target.display_name}**' if user else 'Du bist'
        suffix = 'ist bereits subscribed.' if user else 'bereits subscribed.'
        await interaction.response.send_message(
            f'{name} {suffix}', ephemeral=True)
    else:
        if user:
            await interaction.response.send_message(
                f'\u2705 **{target.display_name}** fuer Schachrallye subscribed.',
                ephemeral=True)
        else:
            await interaction.response.send_message(
                '\u2705 Du bist jetzt fuer Schachrallye-Erinnerungen subscribed.\n'
                'Du wirst bei neuen Rallye-Turnieren gepingt und 7 Tage vorher erinnert.',
                ephemeral=True)
        # DM an den subscribten User
        try:
            dm = await target.create_dm()
            await dm.send(
                'Du wurdest fuer die **Schachrallye-Erinnerungen** angemeldet!\n'
                '\u2022 Bei neuen Rallye-Turnieren wirst du im Channel gepingt\n'
                '\u2022 7 Tage vor jedem Termin bekommst du eine Erinnerung\n'
                'Mit `/schachrallye` siehst du alle Termine. '
                'Mit `/schachrallye_unsub` kannst du dich jederzeit abmelden.'
            )
        except discord.Forbidden:
            log.warning('Rallye-Sub-DM an %s nicht moeglich (DMs deaktiviert).', target.id)
        except Exception:
            log.warning('Rallye-Sub-DM an %s fehlgeschlagen.', target.id)


@discord.app_commands.describe(
    user='Anderen User unsubscriben (nur Admin)')
async def cmd_schachrallye_unsub(interaction: discord.Interaction,
                                 user: discord.User = None):
    if user and not is_privileged(interaction):
        await interaction.response.send_message(
            '\u26a0\ufe0f Nur Admins koennen andere User unsubscriben.',
            ephemeral=True)
        return

    target = user or interaction.user
    result = {'was_subbed': False}

    def _unsub(data):
        if not isinstance(data, dict) or 'subscribers' not in data:
            return data
        subs = data['subscribers'].get('schachrallye', [])
        if target.id in subs:
            subs.remove(target.id)
            result['was_subbed'] = True
        return data

    turnier_store.update(_unsub)
    if result['was_subbed']:
        if user:
            await interaction.response.send_message(
                f'\u2705 **{target.display_name}** unsubscribed.',
                ephemeral=True)
        else:
            await interaction.response.send_message(
                '\u2705 Schachrallye-Erinnerungen abbestellt.',
                ephemeral=True)
    else:
        name = f'**{target.display_name}**' if user else 'Du'
        verb = 'war' if user else 'warst'
        await interaction.response.send_message(
            f'{name} {verb} nicht subscribed.', ephemeral=True)
