"""Motivations-Texte: Fortschritts-Analyse + Claude-One-Shot-Formulierung + Fallbacks.

Reiner, discord-freier Teil des Motivations-Features (aus commands/motivation.py
ausgelagert): analysiert das BotPlayerProgressDto, baut die DM-Texte (verknuepft/
unverknuepft/Slacker) via Claude mit deterministischem Template-Fallback. Die
Abo-/Loop-/Discord-Logik bleibt in commands/motivation.py.
"""

import asyncio
import logging
import os

from core.sprueche import random_spruch as _random_spruch
from core import discord_link
from puzzle import rookhub

log = logging.getLogger('schach-bot')


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
    daily = today.get('daily') or {}
    play = today.get('play') or {}

    cats = []
    # Ein gemeinsames Tageszeit-Ziel (alle Quellen: Puzzle/Kurs/Chessable zaehlen zusammen).
    if goal.get('dailyMinutes', 0) > 0:
        cats.append(('Training', daily.get('doneSeconds', 0) // 60,
                     goal['dailyMinutes'], bool(daily.get('met')), 'min'))
    if goal.get('playGames', 0) > 0:
        cats.append(('Spielen', play.get('doneGames', 0),
                     goal['playGames'], bool(play.get('met')), 'Partien diese Woche'))

    has_goal = len(cats) > 0
    all_met = has_goal and all(c[3] for c in cats)
    return cats, has_goal, all_met


def _fmt_points(p) -> str:
    """Punkte huebsch: 2.5 -> "2,5", 3.0 -> "3"."""
    try:
        f = float(p)
    except (TypeError, ValueError):
        return str(p)
    if f == int(f):
        return str(int(f))
    return f'{f:.1f}'.replace('.', ',')


def _days_phrase(days) -> str:
    """Tage bis zum Turnier als natuerliche Phrase."""
    if days is None:
        return 'demnaechst'
    if days <= 0:
        return 'heute'
    if days == 1:
        return 'morgen'
    return f'in {days} Tagen'


def _tournament_facts(progress: dict) -> list:
    """Fakten-Zeilen zu anstehenden/laufenden/beendeten Turnieren (fuer Prompt + Fallback)."""
    lines = []
    for t in (progress.get('tournaments') or []):
        if not isinstance(t, dict):
            continue
        name = t.get('name') or 'Turnier'
        status = t.get('status')
        loc = t.get('location')
        loc_txt = f' in {loc}' if loc else ''

        pts = t.get('resultPoints')
        games = t.get('resultGames') or 0
        result_txt = ''
        if pts is not None and games > 0:
            result_txt = f' ({_fmt_points(pts)} aus {games} Partien)'

        if status == 'upcoming':
            lines.append(f'- Anstehendes Turnier "{name}"{loc_txt}: {_days_phrase(t.get("daysUntil"))}.')
        elif status == 'ongoing':
            lines.append(f'- Turnier "{name}"{loc_txt} laeuft heute{result_txt}.')
        else:  # finished
            lines.append(f'- Turnier "{name}"{loc_txt} ist gerade gelaufen{result_txt}.')
    return lines


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

    lines.extend(_tournament_facts(progress))

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


_CLAUDE_TIMEOUT = 30.0  # s — der Motivations-Loop darf nicht an einem haengenden Claude-Call kleben


async def _via_claude(system: str, prompt: str) -> str | None:
    """Formuliert Text per Claude (one-shot, kein Chat-Verlauf). None bei fehlendem Client/Fehler.

    Mit Timeout abgesichert: ein haengender API-Call darf den 10-min-Motivations-Loop
    nicht blockieren (wuerde sonst alle Folge-DMs aufhalten)."""
    from commands.chat import claude_oneshot
    return await claude_oneshot(system, prompt, max_tokens=300, timeout=_CLAUDE_TIMEOUT)


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


def _fallback_tournament_note(progress: dict) -> str:
    """Kurze Turnier-Zeile fuer den Fallback-Text (ohne Claude) — nimmt das zeitnaechste Turnier."""
    for t in (progress.get('tournaments') or []):
        if not isinstance(t, dict):
            continue
        name = t.get('name') or 'Turnier'
        status = t.get('status')
        if status == 'upcoming':
            return f'\U0001f3c6 Dein Turnier "{name}" steht an ({_days_phrase(t.get("daysUntil"))}) — viel Erfolg!'
        pts = t.get('resultPoints')
        games = t.get('resultGames') or 0
        if pts is not None and games > 0:
            return f'\U0001f3c6 Turnier "{name}": {_fmt_points(pts)} aus {games} Partien — stark!'
        return f'\U0001f3c6 Dein Turnier "{name}" ist gelaufen — ich hoffe, es lief gut!'
    return ''


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
    if progress.get('tournaments'):
        prompt += ('\n\nZusaetzlich hat der Spieler Turnier-Aktivitaet (siehe Fakten). Geh kurz und '
                   'natuerlich darauf ein: bei einem anstehenden Turnier die Daumen druecken, bei einem '
                   'gerade beendeten das Ergebnis aufgreifen (gutes Ergebnis feiern, sonst aufbauen). '
                   'Nicht aufzaehlen — locker einflechten.')
    text = await _via_claude(system, prompt)
    if not text:
        text = _fallback_text(cats, has_goal, all_met)
        # Ohne Claude die Turnier-Info nicht verlieren — kurze Zeile anhaengen.
        note = _fallback_tournament_note(progress)
        if note:
            text += f'\n{note}'

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

