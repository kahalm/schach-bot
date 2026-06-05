"""Gemeinsame Datums-/Uhrzeit-Hilfsfunktionen."""

from datetime import date, datetime, timezone


def parse_datum(text: str) -> date | None:
    """Parst TT.MM.JJJJ zu date, gibt None bei Fehler."""
    try:
        return datetime.strptime(text.strip(), '%d.%m.%Y').date()
    except ValueError:
        return None


def parse_utc(ts: str) -> datetime:
    """Parsed ISO-Timestamp und stellt UTC sicher."""
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_zeit(raw: str) -> tuple[int, int] | None:
    """Parst eine Uhrzeit zu (hour, minute). Akzeptiert '17', '1730', '17:30', '17 30'.

    Gibt None bei ungueltigem Format oder Werten zurueck.
    """
    s = raw.strip()
    if not s:
        return None
    # "17:30" oder "17 30"
    for sep in (':', ' '):
        if sep in s:
            parts = s.split(sep, 1)
            try:
                h, m = int(parts[0]), int(parts[1])
            except ValueError:
                return None
            if 0 <= h <= 23 and 0 <= m <= 59:
                return (h, m)
            return None
    # Reine Zahl: "17" (1-2 Stellen) oder "1730" (3-4 Stellen)
    try:
        val = int(s)
    except ValueError:
        return None
    if len(s) <= 2:
        if 0 <= val <= 23:
            return (val, 0)
        return None
    if len(s) in (3, 4):
        h, m = divmod(val, 100)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return (h, m)
        return None
    return None
