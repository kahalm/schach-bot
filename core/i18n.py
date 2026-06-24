"""Minimale i18n fuer die Tagespuzzle-Posts (de/en).

Bewusst klein gehalten: NUR die Strings, die in mehrkanaligen Daily-Posts pro
Channel (ggf. in einer anderen Guild) in unterschiedlicher Sprache erscheinen.
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
}


def t(key: str, lang: str | None = None, **fmt) -> str:
    """Uebersetzt ``key`` in die (normalisierte) Sprache; optionale str.format-Args."""
    text = _T[key][norm(lang)]
    return text.format(**fmt) if fmt else text
