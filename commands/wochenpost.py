"""Wochenpost-Verwaltung: woechentliche Link/PDF-Posts als Thread.

Freitags 18:00 UTC wird pro geplantem Eintrag ein Thread im
konfigurierten Channel erstellt (Thread-Name = dd.mm.yyyy).

/wochenpost           — Alle geplanten + vergangenen Posts anzeigen
/wochenpost_add       — Neuen Eintrag anlegen (Admin)
/wochenpost_del       — Eintrag loeschen (Admin)
"""

import asyncio
import io
import json
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlparse

import discord
import requests
from discord.ext import tasks

from commands.wochenpost_buttons import fresh_view as _fresh_button_view
from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR
from core.permissions import is_privileged
from core.version import EMBED_COLOR

log = logging.getLogger('schach-bot')

WOCHENPOST_FILE = os.path.join(CONFIG_DIR, 'wochenpost.json')
WOCHENPOST_SUB_FILE = os.path.join(CONFIG_DIR, 'wochenpost_sub.json')


def _sub_default():
    return {"subscribers": {}, "resolved": {}}


_bot = None
_wochenpost_channel_id = 0


def _is_admin(interaction: discord.Interaction) -> bool:
    return is_privileged(interaction)


def _parse_datum(text: str) -> date | None:
    """Parst TT.MM.JJJJ zu date, gibt None bei Fehler."""
    try:
        return datetime.strptime(text.strip(), '%d.%m.%Y').date()
    except ValueError:
        return None


def _next_id(entries: list) -> int:
    """Gibt die naechste freie ID zurueck."""
    if not entries:
        return 1
    return max(e.get('id', 0) for e in entries) + 1


def _next_free_friday(entries: list) -> date:
    """Gibt den naechsten Freitag zurueck, der noch nicht belegt ist."""
    today = date.today()
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7  # heute ist Freitag → naechste Woche
    friday = today + timedelta(days=days_until_friday)

    used = {e.get('datum') for e in entries if isinstance(e, dict)}
    while friday.strftime('%Y-%m-%d') in used:
        friday += timedelta(days=7)
    return friday


def _parse_utc(ts: str) -> datetime:
    """Parsed ISO-Timestamp und stellt UTC sicher."""
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _get_latest_posted():
    """Juengster geposteter Eintrag (nach Datum sortiert)."""
    entries = atomic_read(WOCHENPOST_FILE, default=list)
    if not isinstance(entries, list):
        return None
    posted = [e for e in entries if e.get('posted')]
    if not posted:
        return None
    return max(posted, key=lambda e: e.get('datum', ''))


def _entry_id_for_msg(msg_id):
    """Entry-ID anhand msg_id finden."""
    entries = atomic_read(WOCHENPOST_FILE, default=list)
    if not isinstance(entries, list):
        return None
    for e in entries:
        if e.get('msg_id') == msg_id:
            return e.get('id')
    return None


def update_resolution(entry_id, user_id, is_resolved):
    """resolved-Dict in wochenpost_sub.json atomar updaten."""
    eid_str = str(entry_id)

    def _update(data):
        if not isinstance(data, dict):
            data = _sub_default()
        resolved = data.setdefault('resolved', {})
        users = resolved.setdefault(eid_str, [])
        if is_resolved:
            if user_id not in users:
                users.append(user_id)
        else:
            if user_id in users:
                users.remove(user_id)
            if not users:
                del resolved[eid_str]
        return data

    atomic_update(WOCHENPOST_SUB_FILE, _update, default=_sub_default)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup(bot, wochenpost_channel_id: int = 0):
    global _bot, _wochenpost_channel_id
    _bot = bot
    _wochenpost_channel_id = wochenpost_channel_id
    tree = bot.tree

    _NO_CHANNEL_HINT = ('\n\u26a0\ufe0f `WOCHENPOST_CHANNEL_ID` nicht gesetzt '
                        '\u2014 Posts werden nicht gesendet!')

    # --- /wochenpost (Liste) ------------------------------------------------

    @tree.command(name='wochenpost',
                  description='Alle geplanten und vergangenen Wochenposts anzeigen')
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_wochenpost(interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur fuer Admins.', ephemeral=True)
            return

        entries = atomic_read(WOCHENPOST_FILE, default=list)
        if not entries:
            await interaction.response.send_message(
                'Noch keine Wochenposts geplant.\n'
                'Erstelle einen mit `/wochenpost_add`.', ephemeral=True)
            return

        entries_sorted = sorted(entries, key=lambda e: e.get('datum', ''))
        lines = []
        for e in entries_sorted:
            status = '\u2705' if e.get('posted') else '\u23f3'
            d = e.get('datum', '')
            try:
                d_fmt = datetime.strptime(d, '%Y-%m-%d').strftime('%d.%m.%Y')
            except ValueError:
                d_fmt = d
            titel = e.get('titel', '')
            lines.append(f"**#{e['id']}** \u2014 {d_fmt} \u00b7 {titel} \u00b7 {status}")

        desc = '\n'.join(lines)
        if len(desc) > 4096:
            desc = desc[:4093] + '...'

        if not _wochenpost_channel_id:
            desc += _NO_CHANNEL_HINT

        embed = discord.Embed(
            title='\U0001f4e8 Wochenposts',
            description=desc,
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- /wochenpost_add ----------------------------------------------------

    @tree.command(name='wochenpost_add',
                  description='Neuen Wochenpost anlegen (Admin)')
    @discord.app_commands.describe(
        datum='Datum TT.MM.JJJJ (Freitag). Ohne Angabe: naechster freier Freitag',
        text='Optionaler Beschreibungstext',
        url='Optionaler Link',
        pdf='Optionale PDF-Datei als Attachment',
        json_input='JSON-Array: [{"datum":"TT.MM.JJJJ","text":"...","url":"..."},...]',
    )
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_wochenpost_add(interaction: discord.Interaction,
                                  datum: str = '',
                                  text: str = '',
                                  url: str = '',
                                  pdf: discord.Attachment = None,
                                  json_input: str = ''):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur fuer Admins.', ephemeral=True)
            return

        if json_input:
            await _batch_add(interaction, json_input)
            return

        if datum:
            d = _parse_datum(datum)
            if d is None:
                await interaction.response.send_message(
                    '\u26a0\ufe0f Ungueltiges Datum. Format: `TT.MM.JJJJ` (z.B. 02.05.2026)',
                    ephemeral=True)
                return
            if d.weekday() != 4:
                await interaction.response.send_message(
                    '\u26a0\ufe0f Das Datum muss ein Freitag sein.',
                    ephemeral=True)
                return
        else:
            entries = atomic_read(WOCHENPOST_FILE, default=list)
            if not isinstance(entries, list):
                entries = []
            d = _next_free_friday(entries)

        # URL validieren falls angegeben
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                await interaction.response.send_message(
                    '\u26a0\ufe0f Bitte eine gueltige URL angeben (http:// oder https://).',
                    ephemeral=True)
                return

        pdf_url = ''
        pdf_name = ''
        if pdf is not None:
            pdf_url = pdf.url
            pdf_name = pdf.filename

        d_fmt = d.strftime('%d.%m.%Y')

        entry = {
            'id': 0,  # wird in _add gesetzt
            'datum': d.strftime('%Y-%m-%d'),
            'titel': d_fmt,
            'text': text[:2000],
            'url': url[:500],
            'pdf_url': pdf_url,
            'pdf_name': pdf_name,
            'posted': False,
            'user': interaction.user.display_name,
        }

        result = {}

        def _add(entries):
            if not isinstance(entries, list):
                entries = []
            entry['id'] = _next_id(entries)
            entries.append(entry)
            result['id'] = entry['id']
            return entries

        atomic_update(WOCHENPOST_FILE, _add, default=list)

        # Vergangenes oder heutiges Datum → sofort posten
        today = date.today()
        if d <= today and _wochenpost_channel_id:
            channel = _bot.get_channel(_wochenpost_channel_id)
            if channel:
                try:
                    await interaction.response.defer(ephemeral=True)
                    await _post_entry(channel, entry)
                    msg = f"\u2705 Wochenpost #{result['id']} (**{d_fmt}**) sofort gepostet."
                    await interaction.followup.send(msg, ephemeral=True)
                    return
                except Exception:
                    log.exception('Sofort-Post fehlgeschlagen fuer #%d', result['id'])
                    await interaction.followup.send(
                        f"\u2705 Wochenpost #{result['id']} angelegt fuer **{d_fmt}** "
                        f"(Sofort-Post fehlgeschlagen, wird beim naechsten Freitag nachgeholt).",
                        ephemeral=True)
                    return

        msg = f"\u2705 Wochenpost #{result['id']} angelegt fuer **{d_fmt}**"
        if url:
            msg += f'\n{url}'
        if pdf_name:
            msg += f'\nPDF: {pdf_name}'
        if not _wochenpost_channel_id:
            msg += _NO_CHANNEL_HINT
        await interaction.response.send_message(msg, ephemeral=True)

    # --- Batch-Add Logik -----------------------------------------------------

    _BATCH_LIMIT = 52  # max 1 Jahr Freitage

    async def _batch_add(interaction: discord.Interaction, raw_json: str):
        """Legt mehrere Wochenposts aus einem JSON-Array an."""
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, ValueError):
            await interaction.response.send_message(
                '\u26a0\ufe0f JSON-Syntaxfehler. Erwartet: '
                '`[{"datum":"TT.MM.JJJJ","text":"...","url":"..."},...]`',
                ephemeral=True)
            return

        if not isinstance(data, list):
            await interaction.response.send_message(
                '\u26a0\ufe0f JSON muss ein Array sein.',
                ephemeral=True)
            return

        if len(data) == 0:
            await interaction.response.send_message(
                '\u26a0\ufe0f Leeres Array — keine Eintraege zum Anlegen.',
                ephemeral=True)
            return

        if len(data) > _BATCH_LIMIT:
            await interaction.response.send_message(
                f'\u26a0\ufe0f Maximal {_BATCH_LIMIT} Eintraege pro Batch.',
                ephemeral=True)
            return

        # Validierung aller Eintraege
        errors = []
        parsed_entries = []
        for i, item in enumerate(data, 1):
            if not isinstance(item, dict):
                errors.append(f'#{i}: Kein Objekt')
                continue
            raw_datum = item.get('datum', '')
            if not raw_datum:
                errors.append(f'#{i}: `datum` fehlt')
                continue
            d = _parse_datum(str(raw_datum))
            if d is None:
                errors.append(f'#{i}: Ungueltiges Datum `{raw_datum}`')
                continue
            if d.weekday() != 4:
                errors.append(f'#{i}: `{raw_datum}` ist kein Freitag')
                continue
            entry_url = str(item.get('url', ''))[:500]
            if entry_url:
                p = urlparse(entry_url)
                if p.scheme not in ('http', 'https') or not p.netloc:
                    errors.append(f'#{i}: Ungueltige URL `{entry_url}`')
                    continue
            parsed_entries.append({
                'datum': d.strftime('%Y-%m-%d'),
                'titel': d.strftime('%d.%m.%Y'),
                'text': str(item.get('text', ''))[:2000],
                'url': entry_url,
                'pdf_url': '',
                'pdf_name': '',
                'posted': False,
                'user': interaction.user.display_name,
            })

        if errors:
            msg = '\u26a0\ufe0f Validierungsfehler:\n' + '\n'.join(errors)
            if len(msg) > 2000:
                msg = msg[:1997] + '...'
            await interaction.response.send_message(msg, ephemeral=True)
            return

        # Atomar alle Eintraege auf einmal speichern
        ids = []

        def _add_batch(entries):
            if not isinstance(entries, list):
                entries = []
            next_id = _next_id(entries)
            for pe in parsed_entries:
                pe['id'] = next_id
                ids.append(next_id)
                next_id += 1
                entries.append(pe)
            return entries

        atomic_update(WOCHENPOST_FILE, _add_batch, default=list)

        id_list = ', '.join(f'#{eid}' for eid in ids)
        msg = f'\u2705 {len(ids)} Wochenposts angelegt: {id_list}'
        if not _wochenpost_channel_id:
            msg += _NO_CHANNEL_HINT
        await interaction.response.send_message(msg, ephemeral=True)

    # --- /wochenpost_del ----------------------------------------------------

    @tree.command(name='wochenpost_del',
                  description='Wochenpost loeschen (Admin)')
    @discord.app_commands.describe(id='ID des Posts (aus /wochenpost)')
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_wochenpost_del(interaction: discord.Interaction, id: int):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur fuer Admins.', ephemeral=True)
            return

        result = {'found': False}

        def _del(entries):
            if not isinstance(entries, list):
                return entries
            before = len(entries)
            entries[:] = [e for e in entries if e.get('id') != id]
            if len(entries) < before:
                result['found'] = True
            return entries

        atomic_update(WOCHENPOST_FILE, _del, default=list)

        if result['found']:
            msg = f'\u2705 Wochenpost #{id} geloescht.'
            if not _wochenpost_channel_id:
                msg += _NO_CHANNEL_HINT
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.response.send_message(
                f'\u274c Wochenpost #{id} nicht gefunden.', ephemeral=True)

    # --- /wochenpost_sub + /wochenpost_unsub --------------------------------

    @tree.command(name='wochenpost_sub',
                  description='Taeglich DM-Erinnerung an den aktuellen Wochenpost')
    @discord.app_commands.describe(
        zeit='Uhrzeit UTC (0-23, Standard: 17)',
        user='Anderen User subscriben (Admin/Mod)')
    async def cmd_wochenpost_sub(interaction: discord.Interaction,
                                  zeit: int = 17,
                                  user: discord.User = None):
        if user and not _is_admin(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur Admins/Moderatoren koennen andere User subscriben.',
                ephemeral=True)
            return

        if not 0 <= zeit <= 23:
            await interaction.response.send_message(
                '\u26a0\ufe0f Ungueltige Uhrzeit. Bitte 0-23 angeben.',
                ephemeral=True)
            return

        target = user or interaction.user
        uid = str(target.id)
        now = datetime.now(timezone.utc)
        next_dt = now.replace(hour=zeit, minute=0, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += timedelta(days=1)

        result = {'updated': False}

        def _sub(data):
            if not isinstance(data, dict):
                data = _sub_default()
            subs = data.setdefault('subscribers', {})
            data.setdefault('resolved', {})
            result['updated'] = uid in subs
            subs[uid] = {'hour': zeit, 'next': next_dt.isoformat()}
            return data

        await asyncio.to_thread(atomic_update, WOCHENPOST_SUB_FILE,
                                _sub, _sub_default)

        name = f'**{target.display_name}**' if user else 'Wochenpost-Erinnerung'
        if result['updated']:
            if user:
                await interaction.response.send_message(
                    f'\u2705 {name} aktualisiert: '
                    f'taeglich um **{zeit}:00 UTC**.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    f'\u2705 {name} aktualisiert: '
                    f'taeglich um **{zeit}:00 UTC**.',
                    ephemeral=True)
        else:
            if user:
                await interaction.response.send_message(
                    f'\u2705 {name} fuer Wochenpost-Erinnerungen subscribed: '
                    f'taeglich um **{zeit}:00 UTC**.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    f'\u2705 Wochenpost-Erinnerung abonniert: '
                    f'taeglich um **{zeit}:00 UTC**.\n'
                    f'Du bekommst eine DM, bis du den aktuellen '
                    f'Wochenpost als erledigt markierst.',
                    ephemeral=True)

    @tree.command(name='wochenpost_unsub',
                  description='Wochenpost-Erinnerungen abbestellen')
    @discord.app_commands.describe(
        user='Anderen User unsubscriben (Admin/Mod)')
    async def cmd_wochenpost_unsub(interaction: discord.Interaction,
                                    user: discord.User = None):
        if user and not _is_admin(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur Admins/Moderatoren koennen andere User unsubscriben.',
                ephemeral=True)
            return

        target = user or interaction.user
        uid = str(target.id)
        result = {'found': False}

        def _unsub(data):
            if not isinstance(data, dict):
                data = _sub_default()
            subs = data.setdefault('subscribers', {})
            if uid in subs:
                del subs[uid]
                result['found'] = True
            return data

        await asyncio.to_thread(atomic_update, WOCHENPOST_SUB_FILE,
                                _unsub, _sub_default)

        if result['found']:
            if user:
                await interaction.response.send_message(
                    f'\u2705 **{target.display_name}** unsubscribed.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    '\u2705 Wochenpost-Erinnerungen abbestellt.',
                    ephemeral=True)
        else:
            if user:
                await interaction.response.send_message(
                    f'\u26a0\ufe0f **{target.display_name}** hat kein Wochenpost-Abo.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    '\u26a0\ufe0f Du hast kein Wochenpost-Abo.',
                    ephemeral=True)

    # --- Scheduled Loop (taeglich 18:00 UTC, postet nur freitags) -----------

    @tasks.loop(time=time(hour=18, minute=0))
    async def _wochenpost_loop():
        await run_wochenpost()

    @tasks.loop(minutes=30)
    async def _wochenpost_sub_loop():
        await _run_wochenpost_reminders()

    @bot.listen('on_ready')
    async def _start_wochenpost_loop():
        if not _wochenpost_loop.is_running():
            _wochenpost_loop.start()
        if not _wochenpost_sub_loop.is_running():
            _wochenpost_sub_loop.start()
        # Verpasste Posts der letzten 7 Tage nachholen
        await _catchup_missed()


_CATCHUP_DAYS = 7


async def _catchup_missed():
    """Postet verpasste Wochenposts der letzten _CATCHUP_DAYS Tage beim Start."""
    if not _wochenpost_channel_id:
        return
    channel = _bot.get_channel(_wochenpost_channel_id)
    if not channel:
        return

    today = date.today()
    cutoff = (today - timedelta(days=_CATCHUP_DAYS)).strftime('%Y-%m-%d')
    today_str = today.strftime('%Y-%m-%d')

    entries = atomic_read(WOCHENPOST_FILE, default=list)
    if not isinstance(entries, list):
        return

    missed = [
        e for e in entries
        if not e.get('posted')
        and cutoff <= e.get('datum', '') <= today_str
    ]
    missed.sort(key=lambda e: e.get('datum', ''))

    for entry in missed:
        try:
            await _post_entry(channel, entry)
            log.info('Wochenpost #%d nachgeholt (Datum: %s)',
                     entry.get('id', 0), entry.get('datum', ''))
        except Exception:
            log.exception('Wochenpost-Catchup #%d fehlgeschlagen', entry.get('id', 0))


async def _post_entry(channel, entry: dict):
    """Postet einen einzelnen Wochenpost-Eintrag als Thread."""
    thread_name = entry.get('titel', entry.get('datum', 'Wochenpost'))

    thread = await channel.create_thread(
        name=thread_name,
        type=discord.ChannelType.public_thread,
    )

    # Embed bauen
    embed = discord.Embed(
        title=entry.get('titel', ''),
        color=EMBED_COLOR,
    )
    desc_parts = []
    if entry.get('text'):
        desc_parts.append(entry['text'])
    if entry.get('url'):
        desc_parts.append(entry['url'])
    if desc_parts:
        embed.description = '\n\n'.join(desc_parts)

    # PDF runterladen falls vorhanden
    file = None
    if entry.get('pdf_url'):
        try:
            resp = await asyncio.to_thread(
                requests.get, entry['pdf_url'], timeout=30)
            resp.raise_for_status()
            file = discord.File(
                io.BytesIO(resp.content),
                filename=entry.get('pdf_name', 'datei.pdf'),
            )
        except Exception as e:
            log.warning('Wochenpost PDF-Download fehlgeschlagen: %s', e)

    kwargs = {'embed': embed, 'view': _fresh_button_view()}
    if file:
        kwargs['file'] = file
    msg = await thread.send(**kwargs)

    # posted = true setzen + msg_id/thread_id speichern
    def _mark_posted(entries, eid=entry['id'], mid=msg.id, tid=thread.id):
        if not isinstance(entries, list):
            return entries
        for e in entries:
            if e.get('id') == eid:
                e['posted'] = True
                e['msg_id'] = mid
                e['thread_id'] = tid
        return entries

    await asyncio.to_thread(atomic_update, WOCHENPOST_FILE,
                            _mark_posted, list)
    log.info('Wochenpost #%d gepostet: %s', entry['id'], entry.get('titel', ''))


async def run_wochenpost():
    """Prueft ob heute Freitag ist und postet faellige Wochenposts."""
    today = date.today()
    if today.weekday() != 4:  # 4 = Freitag
        return

    if not _wochenpost_channel_id:
        return
    channel = _bot.get_channel(_wochenpost_channel_id)
    if not channel:
        log.warning('Wochenpost-Channel %s nicht gefunden.', _wochenpost_channel_id)
        return

    today_str = today.strftime('%Y-%m-%d')
    entries = atomic_read(WOCHENPOST_FILE, default=list)
    if not isinstance(entries, list):
        return

    pending = [e for e in entries if e.get('datum') == today_str and not e.get('posted')]
    if not pending:
        return

    for entry in pending:
        try:
            await _post_entry(channel, entry)
        except Exception:
            log.exception('Wochenpost #%d fehlgeschlagen', entry.get('id', 0))


async def _run_wochenpost_reminders():
    """Sendet DM-Erinnerungen an Wochenpost-Abonnenten."""
    if not _wochenpost_channel_id:
        return

    entry = _get_latest_posted()
    if entry is None or 'msg_id' not in entry:
        return

    entry_id = str(entry['id'])
    entry_date = entry.get('datum', '')
    thread_id = entry.get('thread_id')
    titel = entry.get('titel', '')

    # Guild-ID fuer Thread-Link
    channel = _bot.get_channel(_wochenpost_channel_id)
    if not channel:
        return
    guild_id = getattr(getattr(channel, 'guild', None), 'id', None)

    thread_url = ''
    if guild_id and thread_id:
        thread_url = f'https://discord.com/channels/{guild_id}/{thread_id}'

    now = datetime.now(timezone.utc)
    today_str = date.today().strftime('%Y-%m-%d')

    sub_data = atomic_read(WOCHENPOST_SUB_FILE, default=_sub_default)
    subscribers = sub_data.get('subscribers', {})
    resolved = sub_data.get('resolved', {})
    resolved_users = set(resolved.get(entry_id, []))

    updates = {}

    for uid_str, info in subscribers.items():
        next_time = _parse_utc(info['next'])
        if now < next_time:
            continue

        hour = info.get('hour', 17)
        tomorrow = (now + timedelta(days=1)).replace(
            hour=hour, minute=0, second=0, microsecond=0)

        # Veroeffentlichungstag → skip
        if entry_date == today_str:
            updates[uid_str] = tomorrow.isoformat()
            continue

        # Bereits resolved → skip
        if int(uid_str) in resolved_users:
            updates[uid_str] = tomorrow.isoformat()
            continue

        # DM senden
        try:
            user = await _bot.fetch_user(int(uid_str))
            dm = await user.create_dm()
            msg_text = f'\U0001f4ec Wochenpost-Erinnerung: **{titel}**'
            if thread_url:
                msg_text += f'\n{thread_url}'
            await dm.send(msg_text)
        except Exception:
            log.warning('Wochenpost-DM an User %s fehlgeschlagen', uid_str)

        updates[uid_str] = tomorrow.isoformat()

    if updates:
        def _advance(data):
            if not isinstance(data, dict):
                data = _sub_default()
            subs = data.setdefault('subscribers', {})
            for uid_str, iso in updates.items():
                if uid_str in subs:
                    subs[uid_str]['next'] = iso
            return data

        await asyncio.to_thread(
            atomic_update, WOCHENPOST_SUB_FILE, _advance, _sub_default)
