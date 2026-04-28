"""Wochenpost-Verwaltung: woechentliche Link/PDF-Posts als Thread.

Taeglich 18:00 UTC wird pro geplantem Eintrag ein Thread im
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
import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import discord
import requests
from discord.ext import tasks

from commands.wochenpost_buttons import fresh_view as _fresh_button_view
from core.datetime_utils import parse_datum as _parse_datum, parse_utc as _parse_utc
from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR
from core.permissions import is_privileged
from core.version import EMBED_COLOR

log = logging.getLogger('schach-bot')

# ---------------------------------------------------------------------------
# Zufalls-Sprueche fuer DM-Erinnerungen
# ---------------------------------------------------------------------------

_sprueche_cache = None


def _random_spruch() -> str:
    """Gibt einen zufaelligen Spruch als formatierten String zurueck."""
    global _sprueche_cache
    if _sprueche_cache is None:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'assets', 'sprueche.json')
        try:
            with open(path, encoding='utf-8') as f:
                _sprueche_cache = json.load(f)
        except Exception:
            _sprueche_cache = []
    if not _sprueche_cache:
        return ''
    s = random.choice(_sprueche_cache)
    text = s.get('text', '')
    autor = s.get('autor')
    if autor:
        return f'_"{text}"_ — {autor}'
    return f'_"{text}"_'

async def _try_chat_spark(uid: int, spruch: str, titel: str) -> str | None:
    """Generiert sarkastische Claude-Antwort fuer whitelisted Chat-User.

    Gibt None zurueck wenn User nicht whitelisted oder kein API-Client.
    """
    from commands.chat import (
        _client, _is_whitelisted, _chat_response,
        CHAT_FILE as _CHAT_FILE,
    )
    from core.json_store import atomic_read as _ar
    if _client is None:
        return None
    if not await asyncio.to_thread(_is_whitelisted, uid):
        return None
    try:
        # Eskalationsstufe aus bisheriger History ableiten
        data = await asyncio.to_thread(_ar, _CHAT_FILE, dict)
        msgs = data.get('history', {}).get(str(uid), [])
        spark_count = sum(1 for m in msgs if m.get('role') == 'assistant')

        if spark_count < 3:
            tone = 'leicht sarkastisch, mit einem Augenzwinkern'
        elif spark_count < 7:
            tone = 'deutlich sarkastischer, fast schon frech'
        elif spark_count < 12:
            tone = ('richtig bissig und provokant — du bist ein '
                    'drill-sergeant der Schach-Armee')
        else:
            tone = ('komplett ungebremst, absolut gnadenlos, theatralisch '
                    'uebertrieben — als waere das Schicksal der Menschheit '
                    'davon abhaengig, dass dieser User seine Uebungen macht')

        prompt = (
            f'Hier ist dein taeglicher Schach-Spruch:\n\n'
            f'{spruch}\n\n'
            f'Die aktuelle Wochenpost heisst: "{titel}".\n\n'
            f'Reagiere darauf — {tone}. '
            f'Motiviere den User trotzdem, seine Uebungen zu machen. '
            f'Maximal 2-3 Saetze.'
        )
        return await _chat_response(uid, prompt)
    except Exception:
        log.warning('Chat-Spark fuer User %s fehlgeschlagen', uid)
        return None


async def _build_reminder_text(uid: int, titel: str, thread_url: str = '') -> str:
    """Baut den DM-Text fuer einen Wochenpost-Reminder.

    Wird sowohl vom produktiven Loop als auch von /test verwendet.
    """
    spruch = _random_spruch()
    chat_reply = await _try_chat_spark(uid, spruch, titel)
    if chat_reply:
        msg = f'{chat_reply}\n\n'
    else:
        msg = f'{spruch}\n\n' if spruch else ''
    msg += f'\U0001f4ec Mache deine \u00dcbungen! \u2192 **{titel}**'
    if thread_url:
        msg += f'\n{thread_url}'
    return msg


WOCHENPOST_FILE = os.path.join(CONFIG_DIR, 'wochenpost.json')
WOCHENPOST_SUB_FILE = os.path.join(CONFIG_DIR, 'wochenpost_sub.json')

_VIENNA = ZoneInfo('Europe/Vienna')


def _sub_default():
    return {"subscribers": {}, "resolved": {}}


_bot = None
_wochenpost_channel_id = 0


def _resolve_display_name(uid_int, guild=None):
    """Server-Nickname aus Cache, Fallback auf globalen User-Cache."""
    guilds = [guild] if guild else list(_bot.guilds)
    for g in guilds:
        if g is None:
            continue
        member = g.get_member(uid_int)
        if member:
            return member.display_name
    u = _bot.get_user(uid_int)
    return u.display_name if u else f'User {uid_int}'


def _parse_zeit(raw: str) -> tuple[int, int] | None:
    """Parst Uhrzeit in verschiedenen Formaten zu (hour, minute).

    Akzeptiert: '17', '1730', '17:30', '17 30'.
    Gibt None bei ungueltigem Format oder Werten zurueck.
    """
    s = raw.strip()
    if not s:
        return None
    # "17:30" oder "17 30"
    for sep in (':', ' '):
        if sep in s:
            parts = s.split(sep, 1)
            try:
                h, m = int(parts[0]), int(parts[1])
            except ValueError:
                return None
            if 0 <= h <= 23 and 0 <= m <= 59:
                return (h, m)
            return None
    # Reine Zahl: "17" (1-2 Stellen) oder "1730" (3-4 Stellen)
    try:
        val = int(s)
    except ValueError:
        return None
    if len(s) <= 2:
        if 0 <= val <= 23:
            return (val, 0)
        return None
    if len(s) in (3, 4):
        h, m = divmod(val, 100)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return (h, m)
        return None
    return None


def _next_id(entries: list) -> int:
    """Gibt die naechste freie ID zurueck."""
    if not entries:
        return 1
    return max(e.get('id', 0) for e in entries) + 1


def _next_free_day(entries: list) -> date:
    """Gibt den naechsten Tag zurueck, der noch nicht belegt ist."""
    day = date.today() + timedelta(days=1)
    used = {e.get('datum') for e in entries if isinstance(e, dict)}
    while day.strftime('%Y-%m-%d') in used:
        day += timedelta(days=1)
    return day


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
        if not is_privileged(interaction):
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
        datum='Datum TT.MM.JJJJ. Ohne Angabe: naechster freier Tag',
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
        if not is_privileged(interaction):
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
        else:
            entries = atomic_read(WOCHENPOST_FILE, default=list)
            if not isinstance(entries, list):
                entries = []
            d = _next_free_day(entries)

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
                        f"(Sofort-Post fehlgeschlagen, wird zum geplanten Datum nachgeholt).",
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

    _BATCH_LIMIT = 52

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
        if not is_privileged(interaction):
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
        zeit='Uhrzeit MEZ/MESZ (z.B. 17, 17:30, 1730)',
        user='Anderen User subscriben (Admin/Mod)')
    async def cmd_wochenpost_sub(interaction: discord.Interaction,
                                  zeit: str = None,
                                  user: discord.User = None):
        # Status-Anzeige ohne Parameter
        if zeit is None and user is None:
            sub_data = await asyncio.to_thread(
                atomic_read, WOCHENPOST_SUB_FILE, _sub_default)
            subs = sub_data.get('subscribers', {})
            uid = str(interaction.user.id)

            if is_privileged(interaction):
                # Admin: alle aktiven Abos auflisten
                if not subs:
                    await interaction.response.send_message(
                        'Keine aktiven Wochenpost-Abos.', ephemeral=True)
                    return
                lines = []
                for sub_uid, info in subs.items():
                    h = info.get('hour', 17)
                    m = info.get('minute', 0)
                    name = _resolve_display_name(int(sub_uid), interaction.guild)
                    lines.append(f'- **{name}** \u2014 {h}:{m:02d} MEZ/MESZ')
                desc = '\n'.join(lines)
                await interaction.response.send_message(
                    f'**{len(subs)} aktive(s) Wochenpost-Abo(s):**\n{desc}',
                    ephemeral=True)
            else:
                # Normaler User: eigenen Status
                if uid in subs:
                    info = subs[uid]
                    h = info.get('hour', 17)
                    m = info.get('minute', 0)
                    await interaction.response.send_message(
                        f'Dein Wochenpost-Abo ist **aktiv** \u2014 '
                        f'taeglich um **{h}:{m:02d} MEZ/MESZ**.\n'
                        f'Abbestellen: `/wochenpost_unsub`',
                        ephemeral=True)
                else:
                    await interaction.response.send_message(
                        'Du hast kein aktives Wochenpost-Abo.\n'
                        'Abonnieren: `/wochenpost_sub zeit:17`',
                        ephemeral=True)
            return

        if user and not is_privileged(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur Admins/Moderatoren koennen andere User subscriben.',
                ephemeral=True)
            return

        parsed = _parse_zeit(zeit)
        if parsed is None:
            await interaction.response.send_message(
                '\u26a0\ufe0f Ungueltige Uhrzeit. '
                'Beispiele: `17`, `17:30`, `1730`, `17 30`.',
                ephemeral=True)
            return

        h, m = parsed
        target = user or interaction.user
        uid = str(target.id)
        now_vienna = datetime.now(_VIENNA)
        next_dt = now_vienna.replace(hour=h, minute=m, second=0, microsecond=0)
        if next_dt <= now_vienna:
            next_dt += timedelta(days=1)
        next_dt = next_dt.astimezone(timezone.utc)

        zeit_display = f'{h}:{m:02d} MEZ/MESZ'
        result = {'updated': False}

        def _sub(data):
            if not isinstance(data, dict):
                data = _sub_default()
            subs = data.setdefault('subscribers', {})
            data.setdefault('resolved', {})
            result['updated'] = uid in subs
            subs[uid] = {'hour': h, 'minute': m, 'next': next_dt.isoformat()}
            return data

        await asyncio.to_thread(atomic_update, WOCHENPOST_SUB_FILE,
                                _sub, _sub_default)

        name = f'**{target.display_name}**' if user else 'Wochenpost-Erinnerung'
        if result['updated']:
            if user:
                await interaction.response.send_message(
                    f'\u2705 {name} aktualisiert: '
                    f'taeglich um **{zeit_display}**.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    f'\u2705 {name} aktualisiert: '
                    f'taeglich um **{zeit_display}**.',
                    ephemeral=True)
        else:
            if user:
                await interaction.response.send_message(
                    f'\u2705 {name} fuer Wochenpost-Erinnerungen subscribed: '
                    f'taeglich um **{zeit_display}**.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    f'\u2705 Wochenpost-Erinnerung abonniert: '
                    f'taeglich um **{zeit_display}**.\n'
                    f'Du bekommst eine DM, bis du den aktuellen '
                    f'Wochenpost als erledigt markierst.',
                    ephemeral=True)

    @tree.command(name='wochenpost_unsub',
                  description='Wochenpost-Erinnerungen abbestellen')
    @discord.app_commands.describe(
        user='Anderen User unsubscriben (Admin/Mod)')
    async def cmd_wochenpost_unsub(interaction: discord.Interaction,
                                    user: discord.User = None):
        if user and not is_privileged(interaction):
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

    # --- Scheduled Loop (taeglich 18:00 UTC, postet faellige Eintraege) -----

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

    if hasattr(bot, '_task_loops'):
        bot._task_loops['wochenpost'] = _wochenpost_loop
        bot._task_loops['wochenpost_sub'] = _wochenpost_sub_loop


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

    # PDF runterladen falls vorhanden (max 25 MB)
    _PDF_MAX_BYTES = 25 * 1024 * 1024
    file = None
    if entry.get('pdf_url'):
        try:
            def _download_pdf(url):
                resp = requests.get(url, timeout=30, stream=True)
                resp.raise_for_status()
                chunks = []
                total = 0
                for chunk in resp.iter_content(chunk_size=8192):
                    total += len(chunk)
                    if total > _PDF_MAX_BYTES:
                        raise ValueError(f'PDF zu gross (>{_PDF_MAX_BYTES // (1024*1024)} MB)')
                    chunks.append(chunk)
                return b''.join(chunks)

            data = await asyncio.to_thread(_download_pdf, entry['pdf_url'])
            file = discord.File(
                io.BytesIO(data),
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
    """Postet faellige Wochenposts (Datum == heute)."""
    today = date.today()

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
    now_vienna = now.astimezone(_VIENNA)
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
        minute = info.get('minute', 0)
        tomorrow_vienna = (now_vienna + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        tomorrow = tomorrow_vienna.astimezone(timezone.utc)

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
            msg_text = await _build_reminder_text(int(uid_str), titel, thread_url)
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
