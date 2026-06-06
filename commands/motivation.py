"""Motivations-DM: taegliche, stats-gestuetzte Motivation auf Basis der RookHub-Trainingsziele.

Ersetzt den frueheren Wochenpost-Reminder. Abonnenten bekommen einmal taeglich zu ihrer Wunschzeit
eine DM, die Claude formuliert:

* Verknuepftes RookHub-Konto:
  - Alle Tagesziele erfuellt  → whimsisches Lob, KEINE Aufforderung mehr zu tun.
  - Ziele noch offen          → ermutigender Nudge zum konkreten Rueckstand (Puzzlen/Trainieren/Spielen).
  - Bezieht den aktuellen Wochenpost-Stand mit ein.
* NICHT verknuepft → allgemeine Motivation + Hinweis, sich auf RookHub zu registrieren/zu verknuepfen
  (Link aus ``ROOKHUB_WEB_URL`` mit signiertem dl-Token).

/motivation an [zeit] [user]   — abonnieren (Default 18:00 MEZ/MESZ); `user` nur fuer Admins
/motivation aus [user]         — abbestellen; `user` nur fuer Admins
/motivation status [user]      — eigener Status; Admins sehen ohne `user` ALLE Abos, mit `user` dessen Status
/motivation_send <user> [zeit] — (Admin) Motivations-DM sofort senden; mit `zeit` zusaetzlich taeglich abonnieren
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
from core.permissions import is_privileged, display_name_cached
from core.sprueche import random_spruch as _random_spruch
from puzzle import rookhub

log = logging.getLogger('schach-bot')

MOTIVATION_SUB_FILE = os.path.join(CONFIG_DIR, 'motivation_sub.json')
ACTIVITY_WATCH_FILE = os.path.join(CONFIG_DIR, 'activity_watch.json')

_VIENNA = ZoneInfo('Europe/Vienna')
_DEFAULT_HOUR = 18
_DEFAULT_MINUTE = 0

_bot = None


def _sub_default():
    return {"subscribers": {}}


def _watch_default():
    return {"watching": {}}


# ---------------------------------------------------------------------------
# Activity-Watch (Rich Presence)
# ---------------------------------------------------------------------------

def _get_member(uid_int: int):
    """Gibt das Member-Objekt des Users zurueck (Heim-Server zuerst, dann alle Guilds)."""
    if _bot is None:
        return None
    from core.permissions import _guild_id
    if _guild_id:
        guild = _bot.get_guild(_guild_id)
        if guild:
            m = guild.get_member(uid_int)
            if m:
                return m
    for g in _bot.guilds:
        m = g.get_member(uid_int)
        if m:
            return m
    return None


def _get_current_game(member) -> str | None:
    """Gibt den Namen des aktiven Spiels zurueck (nur playing-Typ; Schach-Apps ignoriert).

    Prueft ``member.activities`` auf ``ActivityType.playing``-Eintraege. Ist der User
    offline oder hat keine passende Aktivitaet, wird ``None`` zurueckgegeben.
    """
    if member is None:
        return None
    for act in getattr(member, 'activities', ()):
        act_type = getattr(act, 'type', None)
        try:
            is_playing = (act_type == discord.ActivityType.playing)
        except Exception:
            # Stub-Umgebung (Tests): Typ als int oder String vergleichen
            is_playing = str(act_type) in ('ActivityType.playing', 'playing', '0') or (
                hasattr(act_type, 'value') and act_type.value == 0)
        if is_playing:
            name = (getattr(act, 'name', '') or '').strip()
            if name and 'chess' not in name.lower():
                return name
    return None


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
_GENERAL_SYSTEM = (
    'Du bist ein warmherziger, verspielter Schach-Buddy. Du schreibst Deutsch, kurz (2-3 Saetze), '
    'und laedst allgemein zum Schach/Puzzlen ein. Dir liegen KEINE konkreten Statistiken vor — '
    'bleib daher allgemein, ohne Zahlen, freundlich und einladend.'
)


_SLACKER_SYSTEM = (
    'Du bist ein freundlich-sarkastischer Schach-Buddy. Du schreibst Deutsch, '
    'kurz (1-2 Saetze), mit einem liebevollen Augenzwinkern — kein erhobener Zeigefinger, '
    'einfach locker aufziehen, dass der Spieler gerade nicht beim Schach ist. '
    'Verwende den Namen des laufenden Spiels und beziehe dich auf den konkreten Rueckstand.'
)


async def _via_claude(system: str, prompt: str) -> str | None:
    """Formuliert Text per Claude (one-shot, kein Chat-Verlauf). None bei fehlendem Client/Fehler."""
    from commands.chat import _client, _MODEL
    if _client is None:
        return None
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
    """Baut den Motivations-DM-Text fuer einen VERKNUEPFTEN Spieler (mit Stats)."""
    cats, has_goal, all_met = _analyze_progress(progress)
    facts = _facts_summary(progress, cats, has_goal)

    system = _PRAISE_SYSTEM if all_met else _NUDGE_SYSTEM
    prompt = (
        'Hier ist der heutige Trainingsstand eines Spielers:\n\n'
        f'{facts}\n\n'
        + ('Alle Tagesziele sind erreicht — feiere das.'
           if all_met else
           'Es sind noch Ziele offen — motiviere passend zum Rueckstand.')
    )
    text = await _via_claude(system, prompt)
    if not text:
        text = _fallback_text(cats, has_goal, all_met)

    # CTA-Link nur wenn noch etwas zu tun ist — beim reinen Lob kein "mach weiter"-Link.
    if not all_met:
        link = rookhub.daily_web_url()
        if link:
            text += f'\n\U0001f9e9 Heutiges Puzzle: {link}'
    return text


# ---------------------------------------------------------------------------
# Nicht verknuepft: allgemeine Motivation + Registrier-/Verknuepfungs-CTA
# ---------------------------------------------------------------------------

def _register_cta(user) -> str:
    """Aufforderung, sich auf RookHub zu registrieren + Discord zu verknuepfen (Link aus ENV)."""
    web_url = os.getenv('ROOKHUB_WEB_URL', '').rstrip('/')
    if web_url and discord_link.is_enabled():
        url = discord_link.append_dl(f'{web_url}/register', user.id, user.name) \
            or f'{web_url}/register'
        return ('\U0001f517 Registrier dich auf RookHub und verknuepf dabei dein Discord-Konto — '
                'dann motiviere ich dich passend zu deinem echten Fortschritt:\n'
                f'{url}')
    if web_url:
        return (f'\U0001f517 Registrier dich auf RookHub: {web_url}/register '
                '(danach `/link` zum Verknuepfen).')
    return '\U0001f517 Verknuepf dein Konto mit `/link`, dann motiviere ich dich persoenlich.'


async def _build_unlinked_text(user) -> str:
    """Allgemeine Motivation + Registrier-/Verknuepfungs-Hinweis fuer NICHT verknuepfte User."""
    text = await _via_claude(
        _GENERAL_SYSTEM,
        'Motiviere allgemein und freundlich zum Schach/Puzzlen — kurz, ohne konkrete Zahlen.')
    if not text:
        spruch = _random_spruch()
        body = ('♟️ Lust auf ein paar Puzzles oder eine Partie? '
                'Schach wird mit etwas taeglichem Training spuerbar besser.')
        text = f'{spruch}\n\n{body}' if spruch else body
    return f'{text}\n\n{_register_cta(user)}'


# ---------------------------------------------------------------------------
# Slacker-DM (Activity Watch)
# ---------------------------------------------------------------------------

async def _build_slacker_unlinked_text(activity_name: str, elapsed_min: int, user) -> str:
    """Sarkastischer Nudge fuer NICHT verknuepfte User — mit Registrierungs-CTA."""
    prompt = (
        f'Der User spielt gerade "{activity_name}" (seit {elapsed_min} Minuten) '
        f'und hat RookHub noch nicht mal registriert/verknuepft. '
        f'Schreib eine kurze sarkastisch-freundliche Nachricht im Stil von '
        f'"Aha, fuer {activity_name} hast du Zeit, aber nicht mal fuer RookHub?"'
    )
    text = await _via_claude(_SLACKER_SYSTEM, prompt)
    if not text:
        text = (
            f'Aha, fuer **{activity_name}** hast du Zeit, aber nicht mal fuer RookHub? \U0001f928'
        )
    return f'{text}\n\n{_register_cta(user)}'


async def _build_slacker_text(activity_name: str, cats: list, elapsed_min: int) -> str:
    """Baut den sarkastischen Nudge-Text wenn jemand statt Schach ein anderes Spiel spielt."""
    offen = ', '.join(
        f'{label} {done}/{target} {unit}'
        for label, done, target, met, unit in cats if not met
    )
    prompt = (
        f'Der Spieler spielt gerade "{activity_name}" (seit {elapsed_min} Minuten) '
        f'und hat noch nicht: {offen}. '
        f'Schreib eine kurze sarkastisch-freundliche Nachricht im Stil von '
        f'"Aha, fuer {activity_name} hast du Zeit, aber nicht fuer Schach?"'
    )
    text = await _via_claude(_SLACKER_SYSTEM, prompt)
    if not text:
        text = (
            f'Aha, fuer **{activity_name}** hast du Zeit, aber fuer dein Schachtraining nicht? \U0001f928\n'
            f'Noch offen: {offen} — kurzer Schach-Break gefaellig? ♟️'
        )
    return text


async def _check_activities():
    """Prueft fuer alle Motivation-Abonnenten die Discord-Aktivitaet (alle 30 min).

    Wer seit >60 min ein Nicht-Schach-Spiel spielt und noch offene Tagesziele hat,
    bekommt genau einmal pro Aktivitaets-Session eine sarkastisch-freundliche DM.
    """
    now = datetime.now(timezone.utc)

    sub_data = atomic_read(MOTIVATION_SUB_FILE, default=_sub_default)
    subscribers = sub_data.get('subscribers', {}) if isinstance(sub_data, dict) else {}
    if not subscribers:
        return

    watch_data = atomic_read(ACTIVITY_WATCH_FILE, default=_watch_default)
    watching = watch_data.get('watching', {}) if isinstance(watch_data, dict) else {}

    new_watching = {}

    for uid_str in list(subscribers.keys()):
        uid_int = int(uid_str)
        member = _get_member(uid_int)
        current_game = _get_current_game(member)

        if current_game is None:
            # Kein aktives Spiel → Watch-State verwerfen
            continue

        prev = watching.get(uid_str, {})

        if prev.get('name', '') != current_game:
            # Neues (oder anderes) Spiel → Tracking starten
            new_watching[uid_str] = {
                'name': current_game,
                'since': now.isoformat(),
                'dm_sent': False,
            }
            continue

        # Gleiche Aktivitaet laeuft weiter
        state = dict(prev)
        new_watching[uid_str] = state

        if state.get('dm_sent'):
            continue

        try:
            since = datetime.fromisoformat(state['since'])
        except (KeyError, ValueError):
            continue

        elapsed_minutes = (now - since).total_seconds() / 60
        if elapsed_minutes < 60:
            continue

        # Tagesziele pruefen
        progress = await asyncio.to_thread(rookhub.get_player_progress, uid_int)

        try:
            user_obj = member or await _bot.fetch_user(uid_int)
            if progress is None:
                # Nicht verknuepft → sarkastischer Nudge + Registrierungs-CTA
                text = await _build_slacker_unlinked_text(current_game, round(elapsed_minutes), user_obj)
            else:
                cats, has_goal, all_met = _analyze_progress(progress)
                if not has_goal or all_met:
                    continue
                text = await _build_slacker_text(current_game, cats, round(elapsed_minutes))
            dm = await user_obj.create_dm()
            await dm.send(text)
            state['dm_sent'] = True
            log.info('Slacker-DM an User %s (spielt %s seit %d min, linked=%s)',
                     uid_str, current_game, round(elapsed_minutes), progress is not None)
        except Exception:
            log.warning('Slacker-DM an User %s fehlgeschlagen', uid_str)

    def _save_watch(data):
        if not isinstance(data, dict):
            data = _watch_default()
        data['watching'] = new_watching
        return data

    await asyncio.to_thread(atomic_update, ACTIVITY_WATCH_FILE, _save_watch, _watch_default)


# ---------------------------------------------------------------------------
# Senden (Loop + manuell + /test)
# ---------------------------------------------------------------------------

async def _send_motivation_to(uid_int: int, user_obj=None) -> bool:
    """Schickt EINEM User die passende Motivations-DM (verknuepft → persoenlich, sonst allgemein + CTA).

    ``user_obj`` optional (spart das fetch_user); sonst wird er ueber den Bot geholt. Gibt True bei Versand.
    """
    progress = await asyncio.to_thread(rookhub.get_player_progress, uid_int)
    if user_obj is None:
        user_obj = await _bot.fetch_user(uid_int)
    if progress is not None:
        text = await _build_motivation_text(uid_int, progress)
    else:
        text = await _build_unlinked_text(user_obj)
    dm = await user_obj.create_dm()
    await dm.send(text)
    return True


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
            await _send_motivation_to(int(uid_str))
            log.info('Motivations-DM an User %s gesendet.', uid_str)
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
# Subscribe-Helfer
# ---------------------------------------------------------------------------

def _subscribe(uid: str, h: int, m: int) -> bool:
    """Legt/aktualisiert ein Abo an. Gibt True zurueck, wenn es vorher schon existierte."""
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

    atomic_update(MOTIVATION_SUB_FILE, _sub, _sub_default)
    return result['updated']


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
        zeit='Uhrzeit MEZ/MESZ (z.B. 17, 17:30, 1730) — nur bei "an", Default 18:00',
        user='Anderen User verwalten (nur Admin/Mod)')
    @discord.app_commands.choices(aktion=[
        discord.app_commands.Choice(name='an', value='an'),
        discord.app_commands.Choice(name='aus', value='aus'),
        discord.app_commands.Choice(name='status', value='status'),
    ])
    async def cmd_motivation(interaction: discord.Interaction,
                             aktion: str = 'status',
                             zeit: str = None,
                             user: discord.User = None):
        # Fremd-User nur fuer Admins/Mods.
        if user is not None and not is_privileged(interaction):
            await interaction.response.send_message(
                '⚠️ Nur Admins/Moderatoren koennen andere User verwalten.', ephemeral=True)
            return

        # --- Status -------------------------------------------------------
        if aktion == 'status':
            sub_data = await asyncio.to_thread(atomic_read, MOTIVATION_SUB_FILE, _sub_default)
            subs = sub_data.get('subscribers', {})

            if user is not None:
                # Admin: Status eines bestimmten Users
                info = subs.get(str(user.id))
                if info:
                    h, m = info.get('hour', _DEFAULT_HOUR), info.get('minute', _DEFAULT_MINUTE)
                    await interaction.response.send_message(
                        f'**{user.display_name}** hat die Motivations-DM **aktiv** — '
                        f'taeglich um **{h}:{m:02d} MEZ/MESZ**.', ephemeral=True)
                else:
                    await interaction.response.send_message(
                        f'**{user.display_name}** hat keine Motivations-DM abonniert.', ephemeral=True)
                return

            if is_privileged(interaction):
                # Admin ohne user → alle Abos auflisten
                if not subs:
                    await interaction.response.send_message(
                        'Keine aktiven Motivations-Abos.', ephemeral=True)
                    return
                lines = []
                for sub_uid, info in subs.items():
                    h, m = info.get('hour', _DEFAULT_HOUR), info.get('minute', _DEFAULT_MINUTE)
                    name = display_name_cached(_bot, int(sub_uid), interaction.guild)
                    lines.append(f'- **{name}** — {h}:{m:02d} MEZ/MESZ')
                await interaction.response.send_message(
                    f'**{len(subs)} aktive(s) Motivations-Abo(s):**\n' + '\n'.join(lines),
                    ephemeral=True)
                return

            # normaler User: eigener Status
            info = subs.get(str(interaction.user.id))
            if info:
                h, m = info.get('hour', _DEFAULT_HOUR), info.get('minute', _DEFAULT_MINUTE)
                await interaction.response.send_message(
                    f'Deine Motivations-DM ist **aktiv** — taeglich um **{h}:{m:02d} MEZ/MESZ**.\n'
                    'Abbestellen: `/motivation aus`', ephemeral=True)
            else:
                await interaction.response.send_message(
                    'Du hast keine Motivations-DM abonniert.\nAbonnieren: `/motivation an`',
                    ephemeral=True)
            return

        target = user or interaction.user
        uid = str(target.id)
        for_other = user is not None

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
            who = f'**{target.display_name}**' if for_other else 'Deine Motivations-DM'
            if result['found']:
                await interaction.response.send_message(
                    f'✅ {who} abbestellt.' if for_other else '✅ Motivations-DM abbestellt.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    (f'⚠️ {who} hat kein Abo.' if for_other
                     else '⚠️ Du hast keine Motivations-DM abonniert.'), ephemeral=True)
            return

        # --- Abonnieren ("an") — auch ohne Verknuepfung erlaubt -----------
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

        updated = await asyncio.to_thread(_subscribe, uid, h, m)
        # Verknuepfungs-Status nur fuer den Hinweis im Bestaetigungstext.
        progress = await asyncio.to_thread(rookhub.get_player_progress, target.id)
        linked = progress is not None
        verb = 'aktualisiert' if updated else 'abonniert'
        wer = f'**{target.display_name}**: ' if for_other else ''
        zeit_txt = f'taeglich um **{h}:{m:02d} MEZ/MESZ**'
        if linked:
            note = ('Es kommt eine persoenliche Nachricht zum Fortschritt.' if for_other
                    else 'Du bekommst taeglich eine kurze, persoenliche Nachricht zu deinem Fortschritt.')
        else:
            note = ('Konto noch nicht mit RookHub verknuepft — bis dahin gibt es allgemeine '
                    'Motivation + einen Registrier-/Verknuepfungs-Hinweis.')
        await interaction.response.send_message(
            f'✅ {wer}Motivations-DM {verb}: {zeit_txt}.\n{note}', ephemeral=True)

    @tree.command(name='motivation_send',
                  description='Motivations-DM sofort an einen User senden (Admin); mit Zeit zusaetzlich abonnieren')
    @discord.app_commands.default_permissions(administrator=True)
    @discord.app_commands.describe(
        user='User, der die Motivations-DM jetzt bekommen soll',
        zeit='Optional: Uhrzeit MEZ/MESZ — wenn gesetzt, wird der User zusaetzlich taeglich dazu abonniert')
    async def cmd_motivation_send(interaction: discord.Interaction,
                                  user: discord.User, zeit: str = None):
        if not is_privileged(interaction):
            await interaction.response.send_message(
                '⚠️ Nur fuer Admins/Moderatoren.', ephemeral=True)
            return

        # Zeit (falls angegeben) zuerst validieren — vor dem defer, damit der Fehler sauber zurueckkommt.
        sub_time = None
        if zeit is not None:
            sub_time = _parse_zeit(zeit)
            if sub_time is None:
                await interaction.response.send_message(
                    '⚠️ Ungueltige Uhrzeit. Beispiele: `17`, `17:30`, `1730`, `17 30`.',
                    ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True)

        sent_ok = True
        try:
            await _send_motivation_to(user.id, user)
        except Exception:
            sent_ok = False
            log.warning('Manuelle Motivations-DM an %s fehlgeschlagen', user.id)

        parts = ['✅ Motivations-DM gesendet.' if sent_ok
                 else '⚠️ Sofort-DM fehlgeschlagen (DMs deaktiviert?).']
        if sub_time is not None:
            h, m = sub_time
            await asyncio.to_thread(_subscribe, str(user.id), h, m)
            parts.append(f'📅 Zusaetzlich taeglich um **{h}:{m:02d} MEZ/MESZ** abonniert.')
        await interaction.followup.send(
            f'**{user.display_name}** — ' + ' '.join(parts), ephemeral=True)

    # --- Loop (alle 30 min; DMs zur Wunschzeit + Activity-Watch) ----------
    @tasks.loop(minutes=30)
    async def _motivation_loop():
        try:
            await _run_motivation_dms()
        except Exception:
            log.exception('Motivations-Loop fehlgeschlagen')
        try:
            await _check_activities()
        except Exception:
            log.exception('Activity-Watch fehlgeschlagen')

    @bot.listen('on_ready')
    async def _start_motivation_loop():
        if not _motivation_loop.is_running():
            _motivation_loop.start()

    if hasattr(bot, '_task_loops'):
        bot._task_loops['motivation'] = _motivation_loop
