"""Reminder-Modul: wiederkehrende Puzzle-DMs in konfigurierbarem Intervall."""

import logging
import os
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

import puzzle
from core import dm_delivery
from core.datetime_utils import parse_utc as _parse_utc
from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

REMINDER_FILE = os.path.join(CONFIG_DIR, 'reminder.json')

_bot = None


@tasks.loop(minutes=1)
async def _reminder_loop():
    try:
        await _reminder_loop_inner()
    except Exception:
        log.exception('Reminder-Loop fehlgeschlagen')


async def _reminder_loop_inner():
    data = atomic_read(REMINDER_FILE)
    if not isinstance(data, dict):
        return
    now = datetime.now(timezone.utc)
    # uid -> (gelesenes next, {next?, retries, unreachable}); remove: uid -> gelesenes next
    updates: dict[str, tuple[str, dict]] = {}
    remove: dict[str, str] = {}

    for uid_str, entry in list(data.items()):
        raw_next = entry.get('next')
        if not raw_next:
            continue
        try:
            next_time = _parse_utc(raw_next)
        except ValueError:
            # Korrupter Eintrag darf nicht den ganzen Pass abbrechen (sonst
            # verhungern alle nachfolgenden User und bereits bediente bekommen
            # kein next-Update → Duplikat-DMs jede Minute).
            log.warning('Reminder: ungueltiger next-Wert %r fuer User %s, uebersprungen.',
                        raw_next, uid_str)
            continue
        if now < next_time:
            continue

        hours = entry.get('hours')
        if not hours or hours < 1:
            log.warning('Reminder: ungueltiger hours-Wert %r fuer User %s, uebersprungen.', hours, uid_str)
            continue
        missed = int((now - next_time).total_seconds() // (hours * 3600))

        uid = int(uid_str)
        error = None
        first_dm_sent = False   # Nachhol-Zweig: Hinweis-DM raus → Termin rueckt auf jeden Fall vor
        posted = 0
        try:
            user = await _bot.fetch_user(uid)
            dm = await user.create_dm()
            if missed > 0:
                # Bot war offline — nur 1 Puzzle nachreichen statt alle verpassten
                await dm.send(
                    f'Ich war leider offline und habe **{missed}** '
                    f'Reminder verpasst. Hier ist ein Puzzle zum Nachholen:'
                )
                first_dm_sent = True
                posted = await puzzle.post_puzzle(dm, count=1, book_idx=entry.get('buch', 0), user_id=uid)
                log.info('Reminder: %d verpasst, 1 nachgereicht für User %s.', missed, uid)
            else:
                # raise_unreachable: gesperrte DMs kommen als Forbidden hoch (statt 0 gepostet),
                # damit der unreachable-Zaehler auch im Regelfall mitlaeuft.
                posted = await puzzle.post_puzzle(
                    dm,
                    count=entry.get('puzzle', 1),
                    book_idx=entry.get('buch', 0),
                    user_id=uid,
                    raise_unreachable=True,
                )
                log.info('Reminder: %d Puzzle(s) an User %s gesendet.', entry.get('puzzle', 1), uid)
        except Exception as e:
            error = e

        # Zustellpolitik wie bei /motivation (core/dm_delivery): unzustellbar → regulaerer
        # Termin + Zaehler, nach MAX_UNREACHABLE_DAYS entfernen; voruebergehend → hoechstens
        # MAX_TRANSIENT_RETRIES Versuche je Termin (im Minutentakt). Vorher: jede Minute ein
        # neuer Versuch, endlos. posted == 0 ohne Ausnahme (z. B. keine Linien) gilt als
        # zugestellt, setzt den unreachable-Zaehler aber nicht zurueck.
        outcome = dm_delivery.outcome_of(None if first_dm_sent else error)
        retries = int(entry.get('retries', 0) or 0)
        unreachable = int(entry.get('unreachable', 0) or 0)
        new_next = (next_time + timedelta(hours=hours) * (missed + 1)).isoformat()
        if outcome == dm_delivery.SENT:
            if error is not None:
                log.warning('Reminder: Fehler für User %s: %s', uid, error)
            retries = 0
            if first_dm_sent or posted:
                unreachable = 0
        elif outcome == dm_delivery.UNREACHABLE:
            log.warning('Reminder: DM an %s nicht möglich (DMs deaktiviert).', uid)
            retries, unreachable = 0, unreachable + 1
            if dm_delivery.unreachable_expired(unreachable, hours):
                log.info('Reminder: User %s %d-mal in Folge nicht erreichbar – Reminder '
                         'automatisch beendet.', uid, unreachable)
                remove[uid_str] = raw_next
                continue
        else:
            log.warning('Reminder: Fehler für User %s: %s', uid, error)
            retries += 1
            if retries < dm_delivery.MAX_TRANSIENT_RETRIES:
                new_next = None   # naechste Minute erneut, Termin bleibt
            else:
                log.warning('Reminder: User %s nach %d Fehlversuchen übersprungen – nächster '
                            'regulärer Termin.', uid, retries)
                retries = 0
        updates[uid_str] = (raw_next, {'next': new_next, 'retries': retries,
                                       'unreachable': unreachable})

    # Atomares Update: nur die eigenen Felder, und nur wenn der Eintrag unveraendert ist
    # (ein zwischenzeitlich neu gesetzter /reminder wird weder ueberschrieben noch geloescht).
    if updates or remove:
        def _apply(data):
            for uid_str, (seen_next, fields) in updates.items():
                cur = data.get(uid_str)
                if not isinstance(cur, dict) or cur.get('next') != seen_next:
                    continue
                if fields['next']:
                    cur['next'] = fields['next']
                for key in ('retries', 'unreachable'):
                    if fields[key]:
                        cur[key] = fields[key]
                    else:
                        cur.pop(key, None)
            for uid_str, seen_next in remove.items():
                if isinstance(data.get(uid_str), dict) and data[uid_str].get('next') == seen_next:
                    del data[uid_str]
            return data
        atomic_update(REMINDER_FILE, _apply)


def setup(bot):
    global _bot
    _bot = bot
    tree = bot.tree

    @tree.command(name='reminder', description='Wiederkehrende Puzzle-DMs einstellen',
                  extras={'help': 'puzzle'})
    @discord.app_commands.describe(
        hours='Intervall in Stunden (1–168). 0 = Reminder stoppen.',
        puzzle_count='Anzahl Puzzles pro Erinnerung (1–20, Standard: 1)',
        buch=f'{puzzle.LOCAL_BOOK_DESCRIBE} (Standard: alle)',
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
            buch_txt = puzzle.local_book_label(entry.get('buch', 0))
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
        # `buch` = lokales Buch (Index in _list_pgn_files), nicht die /kurs-ID — sonst
        # speichert der Reminder eine ungueltige Nummer und schickt jedes Intervall eine Fehler-DM.
        books = puzzle._list_pgn_files()
        if buch > len(books) and books:
            await interaction.response.send_message(
                puzzle.local_book_not_found(buch, len(books)), ephemeral=True)
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

        buch_txt = puzzle.local_book_label(buch)
        await interaction.response.send_message(
            f"Reminder aktiviert: alle **{hours}h** — **{puzzle_count}** Puzzle(s) — {buch_txt}\n"
            f"Nächster: <t:{int(next_time.timestamp())}:R>",
            ephemeral=True,
        )

    @cmd_reminder.autocomplete('buch')
    async def reminder_buch_autocomplete(interaction: discord.Interaction, current: str):
        return puzzle.local_book_choices(current)

    # Loop starten wenn Bot ready
    @bot.listen('on_ready')
    async def _start_reminder_loop():
        if not _reminder_loop.is_running():
            _reminder_loop.start()

    if hasattr(bot, '_task_loops'):
        bot._task_loops['reminder'] = _reminder_loop
