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
from core.permissions import is_privileged, display_name_cached
from core.sprueche import random_spruch as _random_spruch  # re-exportiert (Modul-Oberfläche/Test)
from puzzle import rookhub

log = logging.getLogger('schach-bot')

MOTIVATION_SUB_FILE = os.path.join(CONFIG_DIR, 'motivation_sub.json')
ACTIVITY_WATCH_FILE = os.path.join(CONFIG_DIR, 'activity_watch.json')

_VIENNA = ZoneInfo('Europe/Vienna')
_DEFAULT_HOUR = 18
_DEFAULT_MINUTE = 0

# Retry-/Erreichbarkeits-Grenzen, damit ein unzustellbarer User nicht endlos
# stuendlich angepingt wird (und die Logs flutet).
_MAX_TRANSIENT_RETRIES = 3   # 60-min-Retries bei voruebergehenden Fehlern, dann erst morgen wieder
_MAX_UNREACHABLE_DAYS = 5    # Tage in Folge unzustellbar (DMs gesperrt) → Abo automatisch beenden

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


def _get_current_game(member) -> 'tuple[str, datetime | None] | None':
    """Gibt (Name, Start) des aktiven Spiels zurueck (nur playing-Typ; Schach-Apps ignoriert).

    ``Start`` ist ``act.start`` aus dem Discord Rich Presence (datetime UTC) oder None.
    Ist der User offline oder hat keine passende Aktivitaet, wird ``None`` zurueckgegeben.
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
                return (name, getattr(act, 'start', None))
    return None


# Reiner Text-/Analyse-Teil ausgelagert nach commands/motivation_text.py; hier
# re-importiert, damit bestehende Aufrufer (Loops unten) und Tests (mot._X) unveraendert bleiben.
from commands.motivation_text import (  # noqa: F401
    _analyze_progress, _fmt_points, _days_phrase, _tournament_facts, _facts_summary,
    _via_claude, _fallback_text, _fallback_tournament_note, _build_motivation_text,
    _register_cta, _build_unlinked_text, _build_slacker_unlinked_text, _build_slacker_text,
    _PRAISE_SYSTEM, _NUDGE_SYSTEM, _GENERAL_SYSTEM, _SLACKER_SYSTEM, _CLAUDE_TIMEOUT,
)


async def _check_goals_completed():
    """Schickt Motivation-Abonnenten eine Glückwunsch-DM, wenn sie heute alle Tagesziele erfüllt haben.

    Läuft alle 10 min im Motivations-Loop. Sendet nur EINMAL pro Tag pro User (Zustand in
    reinforcement.json). Nur für Abonnenten mit verknüpftem RookHub-Konto und gesetzten Zielen.
    """
    from core import reinforcement

    sub_data = atomic_read(MOTIVATION_SUB_FILE, default=_sub_default)
    subscribers = sub_data.get('subscribers', {}) if isinstance(sub_data, dict) else {}
    if not subscribers:
        return

    for uid_str in list(subscribers.keys()):
        uid_int = int(uid_str)
        if not reinforcement.goals_not_yet_notified_today(uid_str):
            continue
        progress = await asyncio.to_thread(rookhub.get_player_progress, uid_int)
        if progress is None:
            continue
        cats, has_goal, all_met = _analyze_progress(progress)
        if not has_goal or not all_met:
            continue
        try:
            await reinforcement.notify_goals_met(_bot, uid_str, cats)
        except Exception:
            log.debug('Goals-Reinforcement an %s fehlgeschlagen', uid_str)


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
        game_info = _get_current_game(member)

        if game_info is None:
            # Kein aktives Spiel → Watch-State verwerfen
            continue

        current_game, act_start = game_info
        prev = watching.get(uid_str, {})

        if prev.get('name', '') != current_game:
            # Neues (oder anderes) Spiel → Tracking starten; Discord-Start bevorzugen
            since = act_start.isoformat() if act_start is not None else now.isoformat()
            new_watching[uid_str] = {
                'name': current_game,
                'since': since,
                'dm_sent': False,
            }
            continue

        # Gleiche Aktivitaet laeuft weiter
        state = dict(prev)
        new_watching[uid_str] = state

        # dm_sent speichert den Timestamp der letzten DM (oder None); nach 3h erneut senden
        dm_sent = state.get('dm_sent')
        if dm_sent:
            try:
                if (now - datetime.fromisoformat(dm_sent)).total_seconds() < 3 * 3600:
                    continue
            except (TypeError, ValueError):
                continue  # Legacy-Boolean True → ueberspringen

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
            state['dm_sent'] = now.isoformat()
            log.info('Slacker-DM an User %s (spielt %s seit %d min, linked=%s)',
                     uid_str, current_game, round(elapsed_minutes), progress is not None,
                     extra={'es_fields': {
                         'tags': ['motivation'],
                         'username': user_obj.name,
                         'dm_text': text,
                         'game': current_game,
                         'elapsed_minutes': round(elapsed_minutes),
                         'linked': progress is not None,
                     }})
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

    to_remove = []

    for uid_str, info in list(subscribers.items()):
        raw_next = info.get('next')
        if not raw_next:
            continue
        if now < _parse_utc(raw_next):
            continue

        hour = info.get('hour', _DEFAULT_HOUR)
        minute = info.get('minute', _DEFAULT_MINUTE)

        # 'sent' | 'unreachable' (DMs gesperrt/Account weg) | 'transient' (voruebergehend)
        outcome = 'sent'
        try:
            await _send_motivation_to(int(uid_str))
            log.info('Motivations-DM an User %s gesendet.', uid_str,
                     extra={'es_fields': {'tags': ['motivation']}})
        except (discord.Forbidden, discord.NotFound):
            outcome = 'unreachable'
        except Exception:
            outcome = 'transient'

        # Standard-Folgetermin: morgen zur Wunschzeit.
        next_day = (now_vienna + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        new_retries = 0
        new_unreachable = 0

        if outcome == 'sent':
            next_dt = next_day
        elif outcome == 'unreachable':
            # User kann keine DM empfangen (gesperrt) → NICHT stuendlich haemmern,
            # erst morgen erneut; nach _MAX_UNREACHABLE_DAYS Tagen Abo automatisch beenden.
            new_unreachable = info.get('unreachable', 0) + 1
            if new_unreachable >= _MAX_UNREACHABLE_DAYS:
                log.info('Motivations-DM: User %s seit %d Tagen nicht erreichbar (DMs gesperrt?) '
                         '— Abo automatisch beendet.', uid_str, new_unreachable)
                to_remove.append(uid_str)
                continue
            log.warning('Motivations-DM an User %s nicht zustellbar (Tag %d/%d) '
                        '— naechster Versuch morgen.', uid_str, new_unreachable, _MAX_UNREACHABLE_DAYS)
            next_dt = next_day
        else:  # transient
            new_unreachable = info.get('unreachable', 0)  # voruebergehender Fehler aendert das nicht
            new_retries = info.get('retries', 0) + 1
            if new_retries >= _MAX_TRANSIENT_RETRIES:
                log.warning('Motivations-DM an User %s nach %d Versuchen aufgegeben '
                            '— naechster Versuch morgen.', uid_str, new_retries)
                next_dt = next_day
                new_retries = 0
            else:
                log.warning('Motivations-DM an User %s fehlgeschlagen (Versuch %d/%d) '
                            '— Retry in 60 min.', uid_str, new_retries, _MAX_TRANSIENT_RETRIES)
                next_dt = (now + timedelta(hours=1)).astimezone(_VIENNA)

        next_iso = next_dt.astimezone(timezone.utc).isoformat()

        def _advance_one(data, _uid=uid_str, _iso=next_iso, _r=new_retries, _u=new_unreachable):
            if not isinstance(data, dict):
                data = _sub_default()
            subs = data.setdefault('subscribers', {})
            if _uid in subs:
                subs[_uid]['next'] = _iso
                subs[_uid]['retries'] = _r
                subs[_uid]['unreachable'] = _u
            return data

        await asyncio.to_thread(atomic_update, MOTIVATION_SUB_FILE, _advance_one, _sub_default)

    for uid_str in to_remove:
        def _drop(data, _uid=uid_str):
            if isinstance(data, dict):
                data.get('subscribers', {}).pop(_uid, None)
            return data

        await asyncio.to_thread(atomic_update, MOTIVATION_SUB_FILE, _drop, _sub_default)


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

    # --- Loop (alle 10 min; DMs zur Wunschzeit + Activity-Watch + Goals-Reinforcement) ----------
    @tasks.loop(minutes=10)
    async def _motivation_loop():
        try:
            await _run_motivation_dms()
        except Exception:
            log.exception('Motivations-Loop fehlgeschlagen')
        try:
            await _check_activities()
        except Exception:
            log.exception('Activity-Watch fehlgeschlagen')
        try:
            await _check_goals_completed()
        except Exception:
            log.exception('Goals-Reinforcement-Check fehlgeschlagen')

    @bot.listen('on_ready')
    async def _start_motivation_loop():
        if not _motivation_loop.is_running():
            _motivation_loop.start()

    if hasattr(bot, '_task_loops'):
        bot._task_loops['motivation'] = _motivation_loop
