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
