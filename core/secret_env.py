"""Geteilte Geheimnisse aus der Umgebung lesen: Platzhalter aus ``.env.example`` gelten als leer.

Review W2 I2-001: ``.env.example`` traegt fuer die mit RookHub geteilten Geheimnisse nicht-leere
Platzhalter (``change_me_…``). Bleibt einer beim Aufsetzen stehen, signiert bzw. prueft der Bot
mit einem oeffentlich bekannten Schluessel (die Repos sind oeffentlich). Ein Platzhalter schaltet
das Feature deshalb ab wie ein leerer Wert und hinterlaesst beim Start einen ERROR im Log.

Bewusst nur stdlib: ``puzzle/rookhub.py`` und ``core/discord_link.py`` bleiben eigenstaendig testbar.
"""

import logging
import os

log = logging.getLogger('schach-bot')

# Anfaenge der Platzhalter in den .env-Vorlagen des Stacks (Bot und RookHub: ``change_me…``,
# RookHub ausserdem ``your_…``). Ohne Gross-/Kleinschreibung, Leerraum am Rand zaehlt nicht.
PLACEHOLDER_PREFIXES = ('change_me', 'your_')

# Variablen, fuer die der Platzhalter schon gemeldet wurde (ein ERROR je Variable und Prozess).
_reported: set[str] = set()


def is_placeholder(value: str | None) -> bool:
    """True, wenn ``value`` ein Platzhalter aus einer .env-Vorlage ist."""
    return (value or '').strip().lower().startswith(PLACEHOLDER_PREFIXES)


def secret_from_env(name: str, feature: str, env=None) -> str:
    """Wert der Umgebungsvariable ``name``; ``''``, wenn sie leer ODER ein Platzhalter ist.

    Beim Platzhalter einmal je Variable ein ERROR-Log, der ``feature`` als abgeschaltet nennt.
    ``env`` (Standard: ``os.environ``) erlaubt ``core.config.load`` eine eigene Umgebung.
    """
    value = (os.environ if env is None else env).get(name, '') or ''
    if is_placeholder(value):
        if name not in _reported:
            _reported.add(name)
            log.error('%s ist ein Platzhalter aus .env.example — %s deaktiviert. Echten, mit '
                      'RookHub geteilten Wert setzen.', name, feature)
        return ''
    return value
