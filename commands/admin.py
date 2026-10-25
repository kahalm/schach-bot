"""Admin- und Info-Befehle aus dem Bot-Einstieg (frueher bot.py): /version, /greeted, /dm-log,
/announce, /stats, /log, /daily.

``setup(bot)`` registriert sie in dieser Reihenfolge (nach den uebrigen Modulen, wie bisher).
Begruessungsliste/-text: ``commands/welcome.py``; Tagespuzzle: ``puzzle/daily_task.py``.
"""

import asyncio
import io
import logging
from datetime import datetime

import discord

from commands import welcome
from core import dm_log, stats
from core.json_store import atomic_read
from core.permissions import display_name_cached, require_privileged
from core.version import EMBED_COLOR, GIT_SHA, START_TIME, VERSION
from puzzle import daily_task

log = logging.getLogger('schach-bot')

_bot = None


def setup(bot):
    """Befehle am Tree registrieren (Name, Beschreibung, Hilfe-Bereich wie bisher)."""
    global _bot
    _bot = bot
    tree = bot.tree

    def _register(name, description, area, callback):
        tree.command(name=name, description=description, extras={'help': area})(callback)

    _register('version', 'Aktuelle Bot-Version und Uptime anzeigen',
              'info', cmd_version)
    _register('greeted', 'Zeigt alle User, die die Begrüßungs-DM erhalten haben (Admin)',
              'admin', cmd_greeted)
    _register('dm-log', 'DM-Log anzeigen (Admin)',
              'admin', cmd_dm_log)
    _register('announce', 'Begrüßungsnachricht an einen User senden (Admin)',
              'admin', cmd_announce)
    _register('stats', 'Nutzungsstatistiken aller User anzeigen (Admin)',
              'admin', cmd_stats)
    _register('log', 'Letzte Log-Zeilen anzeigen (Admin)',
              'admin', cmd_log)
    _register('daily', 'Tägliches Puzzle manuell auslösen (Admin)',
              'admin', cmd_daily)


# --- Helpers ---

def _display_name_cached(uid, guild=None):
    return display_name_cached(_bot, uid, guild)


_MAX_EMBEDS = 10  # Discord-Limit pro Nachricht


def _paginate_lines(header: str, lines: list[str],
                    max_len: int = 4096) -> list[discord.Embed]:
    """Teilt Zeilen auf mehrere Embeds auf, wenn >max_len Zeichen."""
    embeds: list[discord.Embed] = []
    buf = header
    for line in lines:
        candidate = buf + line + '\n'
        if len(candidate) > max_len:
            embeds.append(discord.Embed(description=buf.rstrip(), color=EMBED_COLOR))
            if len(embeds) >= _MAX_EMBEDS:
                embeds[-1] = discord.Embed(
                    description=buf.rstrip() + '\n\n_(gekuerzt)_', color=EMBED_COLOR)
                return embeds
            buf = line + '\n'
        else:
            buf = candidate
    if buf.strip():
        if len(embeds) < _MAX_EMBEDS:
            embeds.append(discord.Embed(description=buf.rstrip(), color=EMBED_COLOR))
    return embeds or [discord.Embed(description=header.rstrip(), color=EMBED_COLOR)]


# --- Slash-Commands ---

async def cmd_version(interaction: discord.Interaction):
    ts = int(START_TIME.timestamp())
    sha_short = GIT_SHA[:7] if GIT_SHA != 'dev' else 'dev'
    await interaction.response.send_message(
        f'♟️ **Schach-Bot** v{VERSION} ({sha_short})\n'
        f'🔄 Letzter Restart: <t:{ts}:f> (<t:{ts}:R>)',
        ephemeral=True)


@discord.app_commands.default_permissions(administrator=True)
async def cmd_greeted(interaction: discord.Interaction):
    if not await require_privileged(interaction):
        return
    data = await asyncio.to_thread(atomic_read, welcome.DM_STATE_FILE, dict)
    greeted = data.get('greeted', [])
    if not greeted:
        await interaction.response.send_message('Noch niemand begrüßt.', ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    lines = []
    for uid in greeted:
        name = _display_name_cached(uid, interaction.guild)
        lines.append(f'• **{name}** (`{uid}`)')
    header = f'**Begrüßte User ({len(greeted)}):**\n'
    embeds = _paginate_lines(header, lines)
    await interaction.followup.send(embeds=embeds, ephemeral=True)


@discord.app_commands.describe(user='Nur DMs dieses Users anzeigen')
@discord.app_commands.default_permissions(administrator=True)
async def cmd_dm_log(interaction: discord.Interaction, user: discord.User = None):
    if not await require_privileged(interaction):
        return
    await interaction.response.defer(ephemeral=True)
    data = await asyncio.to_thread(atomic_read, dm_log.DM_LOG_FILE, dict)

    if user:
        subset = {str(user.id): data.get(str(user.id), [])}
        subset = {k: v for k, v in subset.items() if v}
    else:
        subset = {k: v for k, v in data.items() if v}

    if not subset:
        await interaction.followup.send('Noch keine DMs protokolliert.', ephemeral=True)
        return

    names = {uid: _display_name_cached(uid, interaction.guild)
             for uid in subset}

    def _last_ts(entries):
        try:
            return entries[-1].get('ts', '') if entries else ''
        except Exception:
            return ''

    sorted_items = sorted(subset.items(), key=lambda kv: _last_ts(kv[1]), reverse=True)

    lines = []
    for uid, entries in sorted_items:
        name = names.get(uid, f'User {uid}')
        if user:
            # Detailansicht: letzte 10 DMs mit Inhalt
            lines.append(f'**{name}** ({len(entries)} DMs):')
            for entry in entries[-10:]:
                ts = entry.get('ts', '')
                text = entry.get('text', '')
                try:
                    dt = datetime.fromisoformat(ts)
                    unix = int(dt.timestamp())
                    lines.append(f'  <t:{unix}:f> {text}')
                except (ValueError, TypeError):
                    lines.append(f'  {ts} {text}')
        else:
            # Uebersicht: eine Zeile pro User
            last = entries[-1]
            try:
                dt = datetime.fromisoformat(last.get('ts', ''))
                unix = int(dt.timestamp())
                ts_fmt = f'<t:{unix}:f>'
            except (ValueError, TypeError):
                ts_fmt = last.get('ts', '?')
            lines.append(f'**{name}** — {len(entries)} DMs · Letzte: {ts_fmt}')

    embeds = _paginate_lines('', lines)
    await interaction.followup.send(embeds=embeds, ephemeral=True)


@discord.app_commands.describe(user='Der User, der die Nachricht erhalten soll')
@discord.app_commands.default_permissions(administrator=True)
async def cmd_announce(interaction: discord.Interaction, user: discord.User):
    if not await require_privileged(interaction):
        return
    try:
        dm = await user.create_dm()
        await dm.send(welcome.welcome_message_for(user))
        await interaction.response.send_message(
            f'✅ Begrüßungsnachricht an **{user.display_name}** gesendet.',
            ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            f'❌ Kann keine DM an **{user.display_name}** senden (DMs deaktiviert).',
            ephemeral=True)
    except Exception as e:
        log.exception('cmd_announce fehlgeschlagen für %s', user)
        await interaction.response.send_message('❌ Ein Fehler ist aufgetreten.', ephemeral=True)


@discord.app_commands.default_permissions(administrator=True)
async def cmd_stats(interaction: discord.Interaction):
    if not await require_privileged(interaction):
        return
    all_stats = await asyncio.to_thread(stats.get_all)
    if not all_stats:
        await interaction.response.send_message('Noch keine Statistiken vorhanden.', ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    names = {uid: _display_name_cached(uid, interaction.guild)
             for uid in all_stats}

    lines = []
    for uid, data in all_stats.items():
        puzzles = data.get('puzzles', 0)
        downloads = data.get('downloads', 0)
        solved = data.get('reaction_✅', 0)
        failed = data.get('reaction_❌', 0)
        liked = data.get('reaction_👍', 0)
        disliked = data.get('reaction_👎', 0)
        trashed = data.get('reaction_🚮', 0)
        name = names.get(uid, f'User {uid}')
        line = f'**{name}** — 🧩 {puzzles} · 📥 {downloads}'
        if solved or failed:
            line += f' · ✅ {solved} · ❌ {failed}'
        if liked or disliked:
            line += f' · 👍 {liked} · 👎 {disliked}'
        if trashed:
            line += f' · 🚮 {trashed}'
        lines.append(line)

    embeds = _paginate_lines('📊 **Statistiken**\n', lines)
    await interaction.followup.send(embeds=embeds, ephemeral=True)


def _read_log_tail(n: int) -> str:
    """Liest die letzten n Zeilen aus bot.log (speicherschonend via deque)."""
    from collections import deque
    try:
        with open('bot.log', encoding='utf-8', errors='replace') as f:
            tail = deque(f, maxlen=n)
        return ''.join(tail).rstrip() or '(leer)'
    except FileNotFoundError:
        return '(leer)'


@discord.app_commands.describe(zeilen='Anzahl Zeilen (Standard: 50, Max: 200)')
@discord.app_commands.default_permissions(administrator=True)
async def cmd_log(interaction: discord.Interaction, zeilen: int = 50):
    if not await require_privileged(interaction):
        return
    await interaction.response.defer(ephemeral=True)
    zeilen = max(1, min(zeilen, 200))
    text = await asyncio.to_thread(_read_log_tail, zeilen)
    if len(text) <= 1900:
        await interaction.followup.send(f'```\n{text}\n```', ephemeral=True)
    else:
        buf = io.BytesIO(text.encode('utf-8'))
        await interaction.followup.send(
            file=discord.File(buf, filename='bot.log'), ephemeral=True)


@discord.app_commands.default_permissions(administrator=True)
async def cmd_daily(interaction: discord.Interaction):
    if not await require_privileged(interaction):
        return
    if not daily_task.DAILY_CHANNEL_IDS:
        await interaction.response.send_message('Kein Daily-Channel konfiguriert.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        results = await daily_task._post_daily_to_all()
        ok = [f'<#{c}>' for c, good in results if good]
        bad = [f'<#{c}>' for c, good in results if not good]
        msg = f'Daily Puzzle gepostet in: {", ".join(ok)}.' if ok else 'Daily Puzzle konnte nirgends gepostet werden.'
        if bad:
            msg += f'\n⚠️ Fehlgeschlagen: {", ".join(bad)}.'
        await interaction.followup.send(msg, ephemeral=True)
    except Exception as e:
        log.exception('Fehler bei /daily')
        await interaction.followup.send('Fehler beim Posten des Daily Puzzles.', ephemeral=True)
