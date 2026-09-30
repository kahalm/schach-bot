"""Zustellpolitik fuer wiederkehrende Bot-DMs (Motivation, Reminder).

Beide Loops schicken zu einem Termin eine DM und entscheiden danach, wann sie es wieder
versuchen. Gemeinsame Regel, damit ein unzustellbarer User weder jede Minute angepingt wird
noch die Logs flutet:

* :data:`SENT`        – zugestellt: naechster regulaerer Termin, Zaehler zurueck.
* :data:`UNREACHABLE` – DMs gesperrt oder Konto weg (``Forbidden``/``NotFound``): NICHT gleich
  wiederholen, sondern zum naechsten regulaeren Termin; decken die Fehlschlaege in Folge
  :data:`MAX_UNREACHABLE_DAYS` Tage ab (:func:`unreachable_expired`), wird der Eintrag entfernt.
* :data:`TRANSIENT`   – alles andere: hoechstens :data:`MAX_TRANSIENT_RETRIES` Versuche je
  Termin (der erste zaehlt mit), danach ebenfalls der naechste regulaere Termin.
"""

import discord

SENT = 'sent'
UNREACHABLE = 'unreachable'
TRANSIENT = 'transient'

MAX_TRANSIENT_RETRIES = 3   # Versuche je Termin bei voruebergehenden Fehlern (1 + 2 Wiederholungen)
MAX_UNREACHABLE_DAYS = 5    # so lange in Folge unzustellbar → Eintrag automatisch entfernen


def outcome_of(exc: BaseException | None) -> str:
    """Ergebnis eines Zustellversuchs: ``None`` = zugestellt, sonst nach Ausnahmetyp."""
    if exc is None:
        return SENT
    if isinstance(exc, (discord.Forbidden, discord.NotFound)):
        return UNREACHABLE
    return TRANSIENT


def unreachable_expired(count: int, interval_hours: float = 24,
                        max_days: int = MAX_UNREACHABLE_DAYS) -> bool:
    """True, wenn ``count`` unzustellbare Termine in Folge (Abstand ``interval_hours``) so weit
    auseinanderliegen wie ``max_days`` taegliche: vom ersten bis zum letzten mindestens
    ``max_days - 1`` Tage. Motivation (taeglich): ab dem 5. Mal; 4-Stunden-Reminder: ab dem
    25.; Wochen-Reminder: ab dem 2."""
    count = int(count or 0)
    return count > 0 and (count - 1) * interval_hours >= (max_days - 1) * 24
