"""Minimale i18n fuer die Tagespuzzle-Posts und /puzzle (de/en).

Bewusst klein gehalten: NUR die Strings, die in mehrkanaligen Daily-Posts pro
Channel (ggf. in einer anderen Guild) in unterschiedlicher Sprache erscheinen,
plus die Antworten von /puzzle – dem einzigen Befehl, der auch in Zusatz-Guilds
registriert ist (Sprache: ``puzzle.commands.reply_lang``).
Kein vollwertiges Gettext — der Bot ist sonst deutsch. Default bleibt Deutsch,
damit bestehendes Verhalten unveraendert ist.
"""

DEFAULT_LANG = 'de'
SUPPORTED = ('de', 'en')


def norm(lang: str | None) -> str:
    """Normalisiert eine Sprachangabe auf einen unterstuetzten Code (Fallback de)."""
    code = (lang or '').strip().lower()[:2]
    return code if code in SUPPORTED else DEFAULT_LANG


# Schluessel → {lang: text}. ``{n}``/``{body}`` sind str.format-Platzhalter.
_T: dict[str, dict[str, str]] = {
    'daily.solver_field':      {'de': '🏆 Tagespuzzle',        'en': '🏆 Daily puzzle'},
    'daily.turn_field':        {'de': 'Am Zug',                'en': 'To move'},
    'daily.turn_white':        {'de': '⬜ Weiß am Zug',         'en': '⬜ White to move'},
    'daily.turn_black':        {'de': '⬛ Schwarz am Zug',      'en': '⬛ Black to move'},
    'daily.solution_field':    {'de': '💡 Lösung',             'en': '💡 Solution'},
    'daily.none_solved':       {'de': 'Noch niemand gelöst',   'en': 'Nobody has solved it yet'},
    'daily.label':             {'de': 'Tagespuzzle',           'en': 'Daily puzzle'},
    'daily.solve_on_rookhub':  {'de': 'Auf RookHub lösen',     'en': 'Solve on RookHub'},
    'daily.replaced':          {'de': '⚠️ Dieses Puzzle wurde durch ein neues ersetzt.',
                                'en': '⚠️ This puzzle has been replaced by a new one.'},
    # Solver-Zeile (format_solver_line)
    'daily.none_solved_attempts': {'de': 'Noch niemand gelöst · 🧩 {n} dran versucht',
                                   'en': 'Nobody has solved it yet · 🧩 {n} attempted'},
    'daily.solved':            {'de': '✅ Gelöst ({n}): {body}', 'en': '✅ Solved ({n}): {body}'},
    'daily.more':              {'de': '+{n} weitere',          'en': '+{n} more'},
    'daily.anon':              {'de': '{n} anonym',            'en': '{n} anonymous'},
    'daily.attempts_suffix':   {'de': ' · 🧩 {n} dran versucht', 'en': ' · 🧩 {n} attempted'},
    # /puzzle-Antworten (puzzle/commands.py) + Link-Text der RookHub-Puzzle-DM (posting.py)
    'puzzle.board_on':         {'de': '✅ Board-Anzeige aktiviert. Du siehst ab jetzt Brettbild + Lösung bei `/puzzle`.',
                                'en': '✅ Board display on. From now on `/puzzle` shows the board image + solution.'},
    'puzzle.board_off':        {'de': '✅ Board-Anzeige deaktiviert. Du bekommst ab jetzt nur den Link bei `/puzzle`.',
                                'en': '✅ Board display off. From now on `/puzzle` only sends the link.'},
    'puzzle.admin_only_other': {'de': '⚠️ Nur Admins duerfen Puzzles an andere User senden.',
                                'en': '⚠️ Only admins can send puzzles to other users.'},
    'puzzle.anzahl_range':     {'de': '⚠️ `anzahl` muss zwischen 1 und 20 liegen.',
                                'en': '⚠️ `anzahl` must be between 1 and 20.'},
    'puzzle.blind_max':        {'de': '⚠️ Maximal 50 Blind-Züge erlaubt.',
                                'en': '⚠️ At most 50 blind moves are allowed.'},
    'puzzle.not_found':        {'de': '⚠️ Puzzle `{id}` nicht gefunden.',
                                'en': '⚠️ Puzzle `{id}` not found.'},
    'puzzle.no_training':      {'de': '⚠️ `{id}` hat keinen Trainingskommentar.',
                                'en': '⚠️ `{id}` has no training comment.'},
    'puzzle.blind_too_short':  {'de': '⚠️ Puzzle `{id}` hat nicht genug Vorlauf-Züge für blind:{n}.',
                                'en': '⚠️ Puzzle `{id}` does not have enough preceding moves for blind:{n}.'},
    'puzzle.sends_you':        {'de': '**{name}** schickt dir ein Rätsel 🧩',
                                'en': '**{name}** sends you a puzzle 🧩'},
    'puzzle.sends_you_blind':  {'de': '**{name}** schickt dir ein Blind-Puzzle 🙈',
                                'en': '**{name}** sends you a blind puzzle 🙈'},
    'puzzle.dest_you':         {'de': 'dir', 'en': 'to you'},
    'puzzle.dest_user':        {'de': 'an {mention}', 'en': 'to {mention}'},
    'puzzle.sent_blind':       {'de': '🙈 Blind-Puzzle `{ref}` {dest} per DM gesendet.',
                                'en': '🙈 Blind puzzle `{ref}` sent {dest} by DM.'},
    'puzzle.sent_id':          {'de': '✅ Puzzle `{id}` {dest} per DM gesendet.',
                                'en': '✅ Puzzle `{id}` sent {dest} by DM.'},
    'puzzle.sent_n':           {'de': '✅ {n} Puzzle(s) wurde(n) {dest} per DM gesendet.{note}',
                                'en': '✅ {n} puzzle(s) sent {dest} by DM.{note}'},
    'puzzle.sent_partial':     {'de': '⚠️ Nur {n}/{total} Puzzle(s) konnten {dest} gesendet werden – Details im Bot-Log.{note}',
                                'en': '⚠️ Only {n}/{total} puzzle(s) could be sent {dest} – details in the bot log.{note}'},
    'puzzle.sent_none':        {'de': '❌ Es konnte kein Puzzle gesendet werden – Details im Bot-Log.',
                                'en': '❌ No puzzle could be sent – details in the bot log.'},
    'puzzle.note_book':        {'de': ' (aus Buch {buch})', 'en': ' (from book {buch})'},
    'puzzle.note_book_unknown': {'de': ' – Buch {buch} unbekannt? `/kurs` zeigt die IDs.',
                                 'en': ' – book {buch} unknown? `/kurs` shows the IDs.'},
    'puzzle.error':            {'de': '❌ Ein Fehler ist aufgetreten.', 'en': '❌ Something went wrong.'},
    'puzzle.solve_link':       {'de': 'Rätsel auf RookHub lösen', 'en': 'Solve the puzzle on RookHub'},
}


def t(key: str, lang: str | None = None, **fmt) -> str:
    """Uebersetzt ``key`` in die (normalisierte) Sprache; optionale str.format-Args."""
    text = _T[key][norm(lang)]
    return text.format(**fmt) if fmt else text
