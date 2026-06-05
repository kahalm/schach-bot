"""Motivations-DM: taegliche, stats-gestuetzte Motivation auf Basis der RookHub-Trainingsziele.

Ersetzt den frueheren Wochenpost-Reminder. Abonnenten bekommen einmal taeglich zu ihrer Wunschzeit
eine DM, die Claude anhand des konkreten Fortschritts (Wochenziele: Puzzle-/Buch-Minuten heute +
Rapid/Classical-Partien pro Woche, dazu Puzzle-Elo/Streak) formuliert:

* Alle Tagesziele erfuellt  → whimsisches Lob, KEINE Aufforderung mehr zu tun.
* Ziele noch offen          → ermutigender Nudge zum konkreten Rueckstand (Puzzlen/Trainieren/Spielen).

Voraussetzung: der Discord-Account ist mit RookHub verknuepft (`/link`) — sonst gibt es keine Stats
und der Bot schickt stattdessen den Verknuepfungs-Hinweis.

/motivation an [zeit]   — abonnieren (Default 18:00 MEZ/MESZ)
/motivation aus         — abbestellen
/motivation status      — eigenen Status anzeigen
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord.ext import tasks

from core.datetime_utils import parse_utc as _parse_utc, parse_zeit as _parse_zeit
from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR
from core import discord_link
from core.sprueche import random_spruch as _random_spruch
from puzzle import rookhub

log = logging.getLogger('schach-bot')

MOTIVATION_SUB_FILE = os.path.join(CONFIG_DIR, 'motivation_sub.json')

_VIENNA = ZoneInfo('Europe/Vienna')
_DEFAULT_HOUR = 18
_DEFAULT_MINUTE = 0

_bot = None


def _sub_default():
    return {"subscribers": {}}


# ---------------------------------------------------------------------------
# Fortschritts-Analyse (pur, testbar)
# ---------------------------------------------------------------------------

def _analyze_progress(progress: dict):
    """Zerlegt das BotPlayerProgressDto in die aktiven Ziel-Kategorien.

    Gibt ``(cats, has_goal, all_met)`` zurueck, wobei ``cats`` eine Liste von
    ``(label, done, target, met, einheit)`` der Kategorien mit gesetztem Ziel ist.
    """
    today = progress.get('today') or {}
    goal = today.get('goal') or {}
    puzzles = today.get('puzzles') or {}
    book = today.get('book') or {}
    play = today.get('play') or {}

    cats = []
    if goal.get('puzzleMinutes', 0) > 0:
        cats.append(('Puzzle', puzzles.get('doneSeconds', 0) // 60,
                     goal['puzzleMinutes'], bool(puzzles.get('met')), 'min'))
    if goal.get('bookMinutes', 0) > 0:
        cats.append(('Training', book.get('doneSeconds', 0) // 60,
                     goal['bookMinutes'], bool(book.get('met')), 'min'))
    if goal.get('playGames', 0) > 0:
        cats.append(('Spielen', play.get('doneGames', 0),
                     goal['playGames'], bool(play.get('met')), 'Partien diese Woche'))

    has_goal = len(cats) > 0
    all_met = has_goal and all(c[3] for c in cats)
    return cats, has_goal, all_met


def _facts_summary(progress: dict, cats, has_goal: bool) -> str:
    """Kompakte Faktenliste fuer den Claude-Prompt / das Fallback-Template."""
    name = progress.get('displayName') or progress.get('username') or 'Spieler'
    lines = [f'Spieler: {name}']
    if has_goal:
        for label, done, target, met, unit in cats:
            status = 'erreicht' if met else 'offen'
            lines.append(f'- {label}: {done}/{target} {unit} ({status})')
    else:
        lines.append('- Keine Trainingsziele gesetzt.')
    pz = progress.get('puzzles') or {}
    elo = pz.get('puzzleElo')
    streak = pz.get('currentStreak')
    if elo:
        extra = f'Puzzle-Elo: {elo}'
        if streak:
            extra += f', aktuelle Serie: {streak}'
        lines.append(extra)

    # Wochenpost-Stand (falls einer existiert) — der Bot soll darauf reagieren können.
    wp = progress.get('weeklyPost')
    if wp:
        title = wp.get('title') or 'Wochenpost'
        total = wp.get('total', 0)
        if wp.get('completed'):
            lines.append(f'Wochenpost "{title}": erledigt ({wp.get("solvedCount", 0)}/{total} gelöst)')
        elif wp.get('playedCount', 0) > 0:
            lines.append(f'Wochenpost "{title}": {wp.get("playedCount", 0)}/{total} gespielt (noch nicht fertig)')
        else:
            lines.append(f'Wochenpost "{title}": noch nicht angefangen')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Claude-One-Shot (kein Chat-Verlauf) mit Template-Fallback
# ---------------------------------------------------------------------------

_PRAISE_SYSTEM = (
    'Du bist ein warmherziger, leicht verspielter Schach-Buddy. Du schreibst Deutsch, '
    'kurz (2-3 Saetze), mit einem Augenzwinkern und Emojis sparsam. WICHTIG: Wenn der Spieler '
    'alle Tagesziele erreicht hat, LOBE ihn einfach herzlich und whimsisch — fordere ihn NICHT '
    'auf, noch mehr zu tun. Geniesse den Moment mit ihm.'
)
_NUDGE_SYSTEM = (
    'Du bist ein motivierender, freundlicher Schach-Buddy. Du schreibst Deutsch, kurz (2-3 Saetze), '
    'ermutigend und konkret. Beziehe dich auf den konkreten Rueckstand und lade locker zum Puzzlen, '
    'Trainieren oder Spielen ein — ohne Druck, ohne erhobenen Zeigefinger.'
)


async def _motivation_via_claude(facts: str, all_met: bool) -> str | None:
    """Formuliert die Motivation per Claude (one-shot). None bei fehlendem Client/Fehler."""
    from commands.chat import _client, _MODEL
    if _client is None:
        return None
    system = _PRAISE_SYSTEM if all_met else _NUDGE_SYSTEM
    prompt = (
        'Hier ist der heutige Trainingsstand eines Spielers:\n\n'
        f'{facts}\n\n'
        + ('Alle Tagesziele sind erreicht — feiere das.'
           if all_met else
           'Es sind noch Ziele offen — motiviere passend zum Rueckstand.')
    )
    try:
        resp = await _client.messages.create(
            model=_MODEL,
            max_tokens=300,
            system=system,
            messages=[{'role': 'user', 'content': prompt}],
        )
        parts = [b.text for b in resp.content if getattr(b, 'type', None) == 'text']
        text = ''.join(parts).strip()
        return text or None
    except Exception:
        log.warning('Motivations-Claude-Aufruf fehlgeschlagen')
        return None


def _fallback_text(cats, has_goal: bool, all_met: bool) -> str:
    """Deterministischer Text ohne Claude — je nach Fortschritt Lob oder Nudge."""
    spruch = _random_spruch()
    if all_met:
        body = ('\U0001f31f Alle Tagesziele erreicht — stark gemacht! '
                'Lehn dich zurueck, das hast du dir verdient.')
    elif has_goal:
        offen = [f'{label} {done}/{target} {unit}'
                 for label, done, target, met, unit in cats if not met]
        rueckstand = ', '.join(offen) if offen else 'ein kleiner Rest'
        body = (f'\U0001f4aa Noch offen: {rueckstand}. '
                'Ein, zwei Puzzles oder eine Partie bringen dich heute ans Ziel!')
    else:
        body = ('♟️ Noch keine Trainingsziele gesetzt — aber jedes Puzzle zaehlt. '
                'Lust auf eine Runde?')
    return f'{spruch}\n\n{body}' if spruch else body


async def _build_motivation_text(uid: int, progress: dict) -> str:
    """Baut den Motivations-DM-Text. Wird vom Loop UND von /test genutzt (keine Duplikat-Logik)."""
    cats, has_goal, all_met = _analyze_progress(progress)
    facts = _facts_summary(progress, cats, has_goal)

    text = await _motivation_via_claude(facts, all_met)
    if not text:
        text = _fallback_text(cats, has_goal, all_met)

    # CTA-Link nur wenn noch etwas zu tun ist — beim reinen Lob kein "mach weiter"-Link.
    if not all_met:
        link = rookhub.daily_web_url()
        if link:
            text += f'\n\U0001f9e9 Heutiges Puzzle: {link}'
    return text


# ---------------------------------------------------------------------------
# Verknuepfungs-Hinweis (wenn Account nicht mit RookHub verbunden)
# ---------------------------------------------------------------------------

def _link_hint(user) -> str:
    web_url = os.getenv('ROOKHUB_WEB_URL', '').rstrip('/')
    if web_url and discord_link.is_enabled():
        url = discord_link.append_dl(f'{web_url}/profile', user.id, user.name) \
            or f'{web_url}/profile'
        return ('\U0001f517 Fuer die Motivation muss dein Discord-Account mit RookHub verknuepft sein.\n'
                'Oeffne diesen persoenlichen Link (eingeloggt auf RookHub):\n'
                f'{url}')
    return ('\U0001f517 Fuer die Motivation muss dein Discord-Account mit RookHub verknuepft sein. '
            'Nutze dazu `/link`.')


# ---------------------------------------------------------------------------
# Reminder-Loop
# ---------------------------------------------------------------------------

async def _run_motivation_dms():
    """Sendet faellige Motivations-DMs an Abonnenten (taeglich zur Wunschzeit)."""
    now = datetime.now(timezone.utc)
    now_vienna = now.astimezone(_VIENNA)

    sub_data = atomic_read(MOTIVATION_SUB_FILE, default=_sub_default)
    subscribers = sub_data.get('subscribers', {}) if isinstance(sub_data, dict) else {}

    for uid_str, info in list(subscribers.items()):
        raw_next = info.get('next')
        if not raw_next:
            continue
        if now < _parse_utc(raw_next):
            continue

        try:
            progress = await asyncio.to_thread(rookhub.get_player_progress, int(uid_str))
            if progress is not None:
                text = await _build_motivation_text(int(uid_str), progress)
                user = await _bot.fetch_user(int(uid_str))
                dm = await user.create_dm()
                await dm.send(text)
                log.info('Motivations-DM an User %s gesendet.', uid_str)
            else:
                log.info('Motivations-DM uebersprungen (User %s nicht verknuepft).', uid_str)
        except Exception:
            log.warning('Motivations-DM an User %s fehlgeschlagen', uid_str)

        # next sofort auf morgen gleiche Zeit setzen (kein Duplikat bei Crash)
        hour = info.get('hour', _DEFAULT_HOUR)
        minute = info.get('minute', _DEFAULT_MINUTE)
        tomorrow = (now_vienna + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        tomorrow_iso = tomorrow.astimezone(timezone.utc).isoformat()

        def _advance_one(data, _uid=uid_str, _iso=tomorrow_iso):
            if not isinstance(data, dict):
                data = _sub_default()
            subs = data.setdefault('subscribers', {})
            if _uid in subs:
                subs[_uid]['next'] = _iso
            return data

        await asyncio.to_thread(atomic_update, MOTIVATION_SUB_FILE, _advance_one, _sub_default)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup(bot):
    global _bot
    _bot = bot
    tree = bot.tree

    @tree.command(name='motivation',
                  description='Taegliche Motivations-DM nach deinen RookHub-Trainingszielen')
    @discord.app_commands.describe(
        aktion='an = abonnieren, aus = abbestellen, status = Status',
        zeit='Uhrzeit MEZ/MESZ (z.B. 17, 17:30, 1730) — nur bei "an", Default 18:00')
    @discord.app_commands.choices(aktion=[
        discord.app_commands.Choice(name='an', value='an'),
        discord.app_commands.Choice(name='aus', value='aus'),
        discord.app_commands.Choice(name='status', value='status'),
    ])
    async def cmd_motivation(interaction: discord.Interaction,
                             aktion: str = 'status',
                             zeit: str = None):
        uid = str(interaction.user.id)

        # --- Status -------------------------------------------------------
        if aktion == 'status':
            sub_data = await asyncio.to_thread(atomic_read, MOTIVATION_SUB_FILE, _sub_default)
            subs = sub_data.get('subscribers', {})
            if uid in subs:
                h = subs[uid].get('hour', _DEFAULT_HOUR)
                m = subs[uid].get('minute', _DEFAULT_MINUTE)
                await interaction.response.send_message(
                    f'Deine Motivations-DM ist **aktiv** — taeglich um **{h}:{m:02d} MEZ/MESZ**.\n'
                    'Abbestellen: `/motivation aus`', ephemeral=True)
            else:
                await interaction.response.send_message(
                    'Du hast keine Motivations-DM abonniert.\nAbonnieren: `/motivation an`',
                    ephemeral=True)
            return

        # --- Abbestellen --------------------------------------------------
        if aktion == 'aus':
            result = {'found': False}

            def _unsub(data):
                if not isinstance(data, dict):
                    data = _sub_default()
                subs = data.setdefault('subscribers', {})
                if uid in subs:
                    del subs[uid]
                    result['found'] = True
                return data

            await asyncio.to_thread(atomic_update, MOTIVATION_SUB_FILE, _unsub, _sub_default)
            await interaction.response.send_message(
                '✅ Motivations-DM abbestellt.' if result['found']
                else '⚠️ Du hast keine Motivations-DM abonniert.', ephemeral=True)
            return

        # --- Abonnieren ("an") -------------------------------------------
        # Verknuepfung pruefen: ohne RookHub-Stats keine Motivation.
        progress = await asyncio.to_thread(rookhub.get_player_progress, interaction.user.id)
        if progress is None:
            await interaction.response.send_message(_link_hint(interaction.user), ephemeral=True)
            return

        if zeit is None:
            h, m = _DEFAULT_HOUR, _DEFAULT_MINUTE
        else:
            parsed = _parse_zeit(zeit)
            if parsed is None:
                await interaction.response.send_message(
                    '⚠️ Ungueltige Uhrzeit. Beispiele: `17`, `17:30`, `1730`, `17 30`.',
                    ephemeral=True)
                return
            h, m = parsed

        now_vienna = datetime.now(_VIENNA)
        next_dt = now_vienna.replace(hour=h, minute=m, second=0, microsecond=0)
        if next_dt <= now_vienna:
            next_dt += timedelta(days=1)
        next_iso = next_dt.astimezone(timezone.utc).isoformat()

        result = {'updated': False}

        def _sub(data):
            if not isinstance(data, dict):
                data = _sub_default()
            subs = data.setdefault('subscribers', {})
            result['updated'] = uid in subs
            subs[uid] = {'hour': h, 'minute': m, 'next': next_iso}
            return data

        await asyncio.to_thread(atomic_update, MOTIVATION_SUB_FILE, _sub, _sub_default)
        verb = 'aktualisiert' if result['updated'] else 'abonniert'
        await interaction.response.send_message(
            f'✅ Motivations-DM {verb}: taeglich um **{h}:{m:02d} MEZ/MESZ**.\n'
            'Du bekommst taeglich eine kurze, persoenliche Nachricht zu deinem Fortschritt.',
            ephemeral=True)

    # --- Loop (alle 30 min; feuert pro User taeglich zur Wunschzeit) ------
    @tasks.loop(minutes=30)
    async def _motivation_loop():
        try:
            await _run_motivation_dms()
        except Exception:
            log.exception('Motivations-Loop fehlgeschlagen')

    @bot.listen('on_ready')
    async def _start_motivation_loop():
        if not _motivation_loop.is_running():
            _motivation_loop.start()

    if hasattr(bot, '_task_loops'):
        bot._task_loops['motivation'] = _motivation_loop
