"""Reminder-Modul: wiederkehrende Puzzle-DMs in konfigurierbarem Intervall."""

import logging
import os
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

import puzzle
from core.datetime_utils import parse_utc as _parse_utc
from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

REMINDER_FILE = os.path.join(CONFIG_DIR, 'reminder.json')

_bot = None


@tasks.loop(minutes=1)
async def _reminder_loop():
    data = atomic_read(REMINDER_FILE)
    now = datetime.now(timezone.utc)
    updated_nexts: dict[str, str] = {}

    for uid_str, entry in list(data.items()):
        next_time = _parse_utc(entry['next'])
        if now < next_time:
            continue

        hours = entry['hours']
        if not hours or hours < 1:
            log.warning('Reminder: ungueltiger hours-Wert %r fuer User %s, uebersprungen.', hours, uid_str)
            continue
        missed = int((now - next_time).total_seconds() // (hours * 3600))

        uid = int(uid_str)
        try:
            user = await _bot.fetch_user(uid)
            dm = await user.create_dm()
            if missed > 0:
                # Bot war offline — nur 1 Puzzle nachreichen statt alle verpassten
                await dm.send(
                    f'Ich war leider offline und habe **{missed}** '
                    f'Reminder verpasst. Hier ist ein Puzzle zum Nachholen:'
                )
                await puzzle.post_puzzle(dm, count=1, book_idx=entry.get('buch', 0), user_id=uid)
                log.info('Reminder: %d verpasst, 1 nachgereicht für User %s.', missed, uid)
            else:
                await puzzle.post_puzzle(
                    dm,
                    count=entry.get('puzzle', 1),
                    book_idx=entry.get('buch', 0),
                    user_id=uid,
                )
                log.info('Reminder: %d Puzzle(s) an User %s gesendet.', entry.get('puzzle', 1), uid)
        except discord.Forbidden:
            log.warning('Reminder: DM an %s nicht möglich (DMs deaktiviert).', uid)
            continue
        except Exception as e:
            log.warning('Reminder: Fehler für User %s: %s', uid, e)
            continue

        # Nur bei Erfolg: nächsten Zeitpunkt vorrücken
        new_next = next_time + timedelta(hours=hours) * (missed + 1)
        updated_nexts[uid_str] = new_next.isoformat()

    # Atomares Update: nur next-Felder aktualisieren (bewahrt parallele Aenderungen)
    if updated_nexts:
        def _update_nexts(data):
            for uid_str, new_next in updated_nexts.items():
                if uid_str in data:
                    data[uid_str]['next'] = new_next
            return data
        atomic_update(REMINDER_FILE, _update_nexts)


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

        # Ohne Parameter → Status anzeigen
        if hours is None:
            data = atomic_read(REMINDER_FILE)
            entry = data.get(uid)
            if not entry:
                await interaction.response.send_message(
                    'Du hast keinen aktiven Reminder. '
                    'Nutze `/reminder hours:4 puzzle_count:3` um einen einzurichten.',
                    ephemeral=True,
                )
                return
            next_ts = _parse_utc(entry['next'])
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
            result = {'deleted': False}
            def _remove(data):
                if uid in data:
                    del data[uid]
                    result['deleted'] = True
                return data
            atomic_update(REMINDER_FILE, _remove)
            if result['deleted']:
                await interaction.response.send_message('Reminder gestoppt.', ephemeral=True)
            else:
                await interaction.response.send_message(
                    'Du hattest keinen aktiven Reminder.', ephemeral=True)
            return

        # Validierung
        if not 1 <= hours <= 168:
            await interaction.response.send_message(
                'Stunden müssen zwischen 1 und 168 liegen.', ephemeral=True)
            return
        if not 1 <= puzzle_count <= 20:
            await interaction.response.send_message(
                'Puzzle-Anzahl muss zwischen 1 und 20 liegen.', ephemeral=True)
            return
        if buch < 0:
            await interaction.response.send_message(
                '⚠️ `buch` darf nicht negativ sein.', ephemeral=True)
            return

        # Reminder aktivieren
        next_time = datetime.now(timezone.utc) + timedelta(hours=hours)
        new_entry = {
            'hours': hours,
            'puzzle': puzzle_count,
            'buch': buch,
            'next': next_time.isoformat(),
        }

        def _set(data):
            data[uid] = new_entry
            return data
        atomic_update(REMINDER_FILE, _set)

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

    if hasattr(bot, '_task_loops'):
        bot._task_loops['reminder'] = _reminder_loop
