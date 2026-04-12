"""Reminder-Modul: wiederkehrende Puzzle-DMs in konfigurierbarem Intervall."""

import json
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

import puzzle

log = logging.getLogger('schach-bot')

REMINDER_FILE = 'reminder.json'


def _load() -> dict:
    try:
        with open(REMINDER_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict):
    with open(REMINDER_FILE, 'w') as f:
        json.dump(data, f, indent=2)


_bot = None


@tasks.loop(minutes=1)
async def _reminder_loop():
    data = _load()
    now = datetime.now(timezone.utc)
    changed = False

    for uid_str, entry in list(data.items()):
        next_time = datetime.fromisoformat(entry['next']).replace(tzinfo=timezone.utc)
        if now < next_time:
            continue

        uid = int(uid_str)
        try:
            user = await _bot.fetch_user(uid)
            dm = await user.create_dm()
            await puzzle.post_puzzle(
                dm,
                count=entry.get('puzzle', 1),
                book_idx=entry.get('buch', 0),
                user_id=uid,
            )
            log.info('Reminder: %d Puzzle(s) an User %s gesendet.', entry.get('puzzle', 1), uid)
        except discord.Forbidden:
            log.warning('Reminder: DM an %s nicht möglich (DMs deaktiviert).', uid)
        except Exception as e:
            log.warning('Reminder: Fehler für User %s: %s', uid, e)

        # Nächsten Zeitpunkt setzen
        hours = entry['hours']
        entry['next'] = (next_time + timedelta(hours=hours)).isoformat()
        changed = True

    if changed:
        _save(data)


def setup(bot):
    global _bot
    _bot = bot
    tree = bot.tree

    @tree.command(name='reminder', description='Wiederkehrende Puzzle-DMs einstellen')
    @discord.app_commands.describe(
        hours='Intervall in Stunden (1–168). 0 = Reminder stoppen.',
        puzzle_count='Anzahl Puzzles pro Erinnerung (1–20, Standard: 1)',
        buch='Nur aus diesem Buch (Nummer aus /kurs, Standard: alle)',
    )
    async def cmd_reminder(
        interaction: discord.Interaction,
        hours: int = None,
        puzzle_count: int = 1,
        buch: int = 0,
    ):
        uid = str(interaction.user.id)
        data = _load()

        # Ohne Parameter → Status anzeigen
        if hours is None:
            entry = data.get(uid)
            if not entry:
                await interaction.response.send_message(
                    'Du hast keinen aktiven Reminder. '
                    'Nutze `/reminder hours:4 puzzle_count:3` um einen einzurichten.',
                    ephemeral=True,
                )
                return
            next_ts = datetime.fromisoformat(entry['next']).replace(tzinfo=timezone.utc)
            buch_txt = f"Buch {entry['buch']}" if entry.get('buch') else 'alle Bücher'
            await interaction.response.send_message(
                f"**Dein Reminder:**\n"
                f"Alle **{entry['hours']}h** — **{entry['puzzle']}** Puzzle(s) — {buch_txt}\n"
                f"Nächster: <t:{int(next_ts.timestamp())}:R> (<t:{int(next_ts.timestamp())}:f>)",
                ephemeral=True,
            )
            return

        # hours:0 → Reminder stoppen
        if hours == 0:
            if uid in data:
                del data[uid]
                _save(data)
                await interaction.response.send_message('Reminder gestoppt.', ephemeral=True)
            else:
                await interaction.response.send_message(
                    'Du hattest keinen aktiven Reminder.', ephemeral=True
                )
            return

        # Validierung
        if not 1 <= hours <= 168:
            await interaction.response.send_message(
                'Stunden müssen zwischen 1 und 168 liegen.', ephemeral=True
            )
            return
        if not 1 <= puzzle_count <= 20:
            await interaction.response.send_message(
                'Puzzle-Anzahl muss zwischen 1 und 20 liegen.', ephemeral=True
            )
            return

        # Reminder aktivieren
        next_time = datetime.now(timezone.utc) + timedelta(hours=hours)
        data[uid] = {
            'hours': hours,
            'puzzle': puzzle_count,
            'buch': buch,
            'next': next_time.isoformat(),
        }
        _save(data)

        buch_txt = f"Buch {buch}" if buch else 'alle Bücher'
        await interaction.response.send_message(
            f"Reminder aktiviert: alle **{hours}h** — **{puzzle_count}** Puzzle(s) — {buch_txt}\n"
            f"Nächster: <t:{int(next_time.timestamp())}:R>",
            ephemeral=True,
        )

    # Loop starten wenn Bot ready
    @bot.listen('on_ready')
    async def _start_reminder_loop():
        if not _reminder_loop.is_running():
            _reminder_loop.start()
