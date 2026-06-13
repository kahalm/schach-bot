"""Tagespuzzle-Bestenlisten auf Discord: Monats-Ladder + all-time Hall of Fame.

`/bestenliste [monat]` zeigt die aktuelle (oder gewählte) Monats-Wertung + Hall of Fame.
Zusätzlich postet ein täglicher Loop am 1. jedes Monats automatisch die Endabrechnung des
Vormonats in den Puzzle-Channel (einmalig, dedupliziert via `config/leaderboard_state.json`).

RookHub ist Source of Truth (Wertung serverseitig berechnet); der Bot holt sie via
`puzzle.rookhub.get_daily_leaderboard` / `get_daily_hall_of_fame` und rendert sie. Reine
Formatierungs-/Termin-Logik liegt in `puzzle.daily_leaderboard` (eigenständig testbar).
"""

import logging
import os
from datetime import datetime, time, timezone

import discord
from discord.ext import tasks

from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR
from core.version import EMBED_COLOR
from puzzle import daily_leaderboard as dlb
from puzzle import rookhub

log = logging.getLogger('schach-bot')

STATE_FILE = os.path.join(CONFIG_DIR, 'leaderboard_state.json')
# Täglicher Check; postet nur am 1. UTC (Vormonats-Abrechnung). Uhrzeit unkritisch.
_POST_TIME = time(hour=8, minute=0)

_bot = None
_channel_id = 0


def _build_embed(ladder: dict | None, hof: dict | None, *, title_prefix: str = '') -> discord.Embed:
    """Baut das Bestenlisten-Embed aus Ladder + Hall of Fame (eine der beiden darf None sein)."""
    period = (ladder or {}).get('period') or ''
    period_label = dlb.format_period(period)
    title = '🏆 Tagespuzzle-Bestenliste'
    if title_prefix:
        title = f'{title_prefix} {title}'
    embed = discord.Embed(title=title, color=EMBED_COLOR)

    field_name = f'📅 Monats-Wertung — {period_label}' if period_label else '📅 Monats-Wertung'
    embed.add_field(name=field_name, value=dlb.format_ladder(ladder or {}), inline=False)

    if hof:
        most_solved = hof.get('mostSolved') or []
        most_golds = hof.get('mostGolds') or []
        fastest = hof.get('fastest')
        if most_solved:
            embed.add_field(name='🧩 Meiste Dailies gelöst',
                            value=dlb.format_hof_list(most_solved, 'gelöst'), inline=True)
        if most_golds:
            embed.add_field(name='🥇 Meiste Gold-Tage',
                            value=dlb.format_hof_list(most_golds, '×🥇'), inline=True)
        if fastest:
            embed.add_field(name='⚡ Schnellste Lösung',
                            value=dlb.format_fastest(fastest), inline=False)

    embed.set_footer(text='Wertung: 10 Pkt je im Erstversuch gelöstem Tagespuzzle + Tages-Bonus 🥇+5 🥈+3 🥉+1')
    return embed


def _mark_posted(month_key: str) -> None:
    def _u(data):
        if not isinstance(data, dict):
            data = {}
        data['last_posted'] = month_key
        data['updated_at'] = datetime.now(timezone.utc).isoformat()
        return data
    atomic_update(STATE_FILE, _u, dict)


async def run_monthly_post() -> None:
    """Postet am 1. eines Monats die Endabrechnung des Vormonats (einmalig)."""
    if not _bot or not _channel_id:
        return
    import asyncio

    state = atomic_read(STATE_FILE, default=dict)
    month = dlb.should_post_monthly(state if isinstance(state, dict) else {},
                                    datetime.now(timezone.utc))
    if not month:
        return

    ladder = await asyncio.to_thread(rookhub.get_daily_leaderboard, month)
    # Leeren Monat nicht posten (kein Spam), aber als erledigt merken.
    if not ladder or not (ladder.get('entries')):
        log.info('Monats-Bestenliste %s: keine Einträge — nicht gepostet.', month)
        _mark_posted(month)
        return

    hof = await asyncio.to_thread(rookhub.get_daily_hall_of_fame)
    channel = _bot.get_channel(_channel_id)
    if channel is None:
        try:
            channel = await _bot.fetch_channel(_channel_id)
        except Exception:
            log.warning('Bestenlisten-Channel %s nicht gefunden.', _channel_id)
            return
    embed = _build_embed(ladder, hof, title_prefix='Endstand')
    try:
        await channel.send(embed=embed)
        _mark_posted(month)
        log.info('Monats-Bestenliste %s gepostet.', month)
    except Exception:
        log.exception('Monats-Bestenliste posten fehlgeschlagen (%s)', month)


def setup(bot, channel_id: int = 0):
    global _bot, _channel_id
    _bot = bot
    _channel_id = channel_id
    tree = bot.tree

    @tree.command(name='bestenliste',
                  description='Tagespuzzle-Bestenliste: Monats-Wertung + Hall of Fame')
    @discord.app_commands.describe(monat='Monat als JJJJ-MM (Standard: aktueller Monat)')
    async def cmd_bestenliste(interaction: discord.Interaction, monat: str = ''):
        import asyncio
        await interaction.response.defer()
        month = monat.strip() or None
        ladder = await asyncio.to_thread(rookhub.get_daily_leaderboard, month)
        if ladder is None:
            await interaction.followup.send(
                'Konnte die Bestenliste gerade nicht laden (RookHub nicht erreichbar oder Monat ungültig — Format JJJJ-MM).',
                ephemeral=True)
            return
        hof = await asyncio.to_thread(rookhub.get_daily_hall_of_fame)
        await interaction.followup.send(embed=_build_embed(ladder, hof))

    @tasks.loop(time=_POST_TIME)
    async def _monthly_loop():
        try:
            await run_monthly_post()
        except Exception:
            log.exception('Monats-Bestenlisten-Loop fehlgeschlagen')

    @bot.listen('on_ready')
    async def _start_monthly_loop():
        if not _monthly_loop.is_running():
            _monthly_loop.start()

    if hasattr(bot, '_task_loops'):
        bot._task_loops['leaderboard'] = _monthly_loop
