"""Wochenpost-Verwaltung: woechentliche Link/PDF-Posts als Thread.

Freitags 18:00 UTC wird pro geplantem Eintrag ein Thread im
konfigurierten Channel erstellt (Thread-Name = dd.mm.yyyy).

/wochenpost           — Alle geplanten + vergangenen Posts anzeigen
/wochenpost_add       — Neuen Eintrag anlegen (Admin)
/wochenpost_del       — Eintrag loeschen (Admin)
"""

import asyncio
import io
import logging
import os
from datetime import date, datetime, time, timezone

import discord
import requests
from discord.ext import tasks

from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR
from core.version import EMBED_COLOR

log = logging.getLogger('schach-bot')

WOCHENPOST_FILE = os.path.join(CONFIG_DIR, 'wochenpost.json')

_bot = None
_wochenpost_channel_id = 0


def _is_admin(interaction: discord.Interaction) -> bool:
    member = interaction.user
    return (
        isinstance(member, discord.Member)
        and member.guild_permissions.administrator
    )


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


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup(bot, wochenpost_channel_id: int = 0):
    global _bot, _wochenpost_channel_id
    _bot = bot
    _wochenpost_channel_id = wochenpost_channel_id
    tree = bot.tree

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
        datum='Datum im Format TT.MM.JJJJ (muss ein Freitag sein)',
        titel='Titel des Posts',
        text='Optionaler Beschreibungstext',
        url='Optionaler Link',
        pdf='Optionale PDF-Datei als Attachment',
    )
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_wochenpost_add(interaction: discord.Interaction,
                                  datum: str,
                                  titel: str,
                                  text: str = '',
                                  url: str = '',
                                  pdf: discord.Attachment = None):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur fuer Admins.', ephemeral=True)
            return

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

        # URL validieren falls angegeben
        if url:
            from urllib.parse import urlparse
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

        entry = {
            'id': 0,  # wird in _add gesetzt
            'datum': d.strftime('%Y-%m-%d'),
            'titel': titel[:500],
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

        d_fmt = d.strftime('%d.%m.%Y')
        msg = f"\u2705 Wochenpost #{result['id']} angelegt fuer **{d_fmt}**:\n**{titel}**"
        if url:
            msg += f'\n{url}'
        if pdf_name:
            msg += f'\nPDF: {pdf_name}'
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
            await interaction.response.send_message(
                f'\u2705 Wochenpost #{id} geloescht.', ephemeral=True)
        else:
            await interaction.response.send_message(
                f'\u274c Wochenpost #{id} nicht gefunden.', ephemeral=True)

    # --- Scheduled Loop (taeglich 18:00 UTC, postet nur freitags) -----------

    @tasks.loop(time=time(hour=18, minute=0))
    async def _wochenpost_loop():
        await run_wochenpost()

    @bot.listen('on_ready')
    async def _start_wochenpost_loop():
        if not _wochenpost_loop.is_running():
            _wochenpost_loop.start()


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

    thread_name = today.strftime('%d.%m.%Y')

    for entry in pending:
        try:
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

            kwargs = {'embed': embed}
            if file:
                kwargs['file'] = file
            await thread.send(**kwargs)

            # posted = true setzen
            def _mark_posted(entries, eid=entry['id']):
                if not isinstance(entries, list):
                    return entries
                for e in entries:
                    if e.get('id') == eid:
                        e['posted'] = True
                return entries

            await asyncio.to_thread(atomic_update, WOCHENPOST_FILE,
                                    _mark_posted, list)
            log.info('Wochenpost #%d gepostet: %s', entry['id'], entry.get('titel', ''))

        except Exception:
            log.exception('Wochenpost #%d fehlgeschlagen', entry.get('id', 0))
