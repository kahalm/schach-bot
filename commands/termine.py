"""Reine Terminlogik der Schachrallye/Turniere – ohne Discord, ohne Datei-I/O, ohne Netz.

- Datum parsen (``_parse_datum_flex`` fuer die Termin-Seite, ``_parse_stored`` fuer turnier.json)
- Anzeige: ``_shorten_ort``, ``_format_turnier_line``, ``_is_valid_url``
- ``parse_termine``: HTML von tirol.chess.at/termine/ → Event-Dicts mit Tags
- ``due_reminders``: welche Rallye-Termine der Reminder-Loop heute erinnert

Abruf der Seite: ``commands/turnier_loops.py``; Datei: ``commands/turnier_store.py``.
"""

import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlparse

from core.datetime_utils import parse_datum as _parse_datum


def _is_valid_url(url: str) -> bool:
    """Prueft ob ein String eine gueltige http/https URL ist."""
    try:
        p = urlparse(url)
        return (p.scheme in ('http', 'https')
                and '.' in p.netloc
                and ' ' not in url)
    except Exception:
        return False


def _parse_stored(text: str) -> date | None:
    """Parst gespeichertes YYYY-MM-DD zu date."""
    try:
        return date.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def _parse_datum_flex(text: str) -> tuple[date | None, str]:
    """Parst Datum oder Datumsbereich, gibt (start_date, display_text) zurueck.

    Unterstuetzte Formate:
      14.05.2026          → einfaches Datum
      20.-24.05.2026      → Bereich, gleicher Monat
      22.05.-25.05.2026   → Bereich, verschiedene Monate
      03.06.-07.06.2026   → Bereich, verschiedene Monate
      20. + 21.06.2026    → Zwei Tage
      31.07.-02.08.2026   → Bereich ueber Monatswechsel
    """
    text = text.strip()
    d = _parse_datum(text)
    if d:
        return d, text

    # "20.-24.05.2026" oder "20. + 21.06.2026"
    m = re.match(r'(\d{1,2})\.\s*[-+]\s*\d{1,2}\.(\d{2}\.\d{4})', text)
    if m:
        return _parse_datum(f'{m.group(1)}.{m.group(2)}'), text

    # "22.05.-25.05.2026" oder "03.06.-07.06.2026"
    m = re.match(r'(\d{1,2}\.\d{2}\.)\s*-\s*\d{1,2}\.\d{2}\.(\d{4})', text)
    if m:
        return _parse_datum(f'{m.group(1)}{m.group(2)}'), text

    return None, text


def _shorten_ort(ort: str) -> str:
    """Kuerzt lange Ort-Beschreibungen auf den wesentlichen Teil."""
    if not ort:
        return ''
    for sep in [',', ';', '(', 'Info ', 'Meldung', 'Anmeldung']:
        idx = ort.find(sep)
        if 0 < idx < 60:
            ort = ort[:idx].strip()
            break
    if len(ort) > 60:
        ort = ort[:59].strip() + '\u2026'
    return ort


def _format_turnier_line(e: dict) -> str:
    """Formatiert einen Turnier-Eintrag als einzeiligen Markdown-String."""
    dt = e.get('datum_text', '')
    if not dt:
        d = _parse_stored(e['datum'])
        dt = d.strftime('%d.%m.%Y') if d else e['datum']
    link = e.get('link', '')
    name = e['name']
    ort = _shorten_ort(e.get('ort', ''))

    if link and _is_valid_url(link):
        line = f"`{dt}` [**{name}**]({link})"
    else:
        line = f"`{dt}` **{name}**"
    if ort:
        line += f" \u00b7 {ort}"
    return line


# ---------------------------------------------------------------------------
# HTML-Parser fuer tirol.chess.at/termine/
# ---------------------------------------------------------------------------

class _TerminParser(HTMLParser):
    """Extrahiert Tabellenzeilen + Links aus der Termin-Seite."""

    def __init__(self):
        super().__init__()
        self._in_table = False
        self._in_td = False
        self._in_th = False
        self._current_row: list[str] = []
        self._current_cell: list[str] = []
        self._current_links: list[str] = []
        self._row_links: list[list[str]] = []
        self.rows: list[list[str]] = []
        self.row_links: list[list[list[str]]] = []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self._in_table = True
        elif tag == 'td' and self._in_table:
            self._in_td = True
            self._current_cell = []
            self._current_links = []
        elif tag == 'th' and self._in_table:
            self._in_th = True
        elif tag == 'tr' and self._in_table:
            self._current_row = []
            self._row_links = []
        elif tag == 'br' and self._in_td:
            self._current_cell.append(' ')
        elif tag == 'a' and self._in_td:
            # Space vor Link-Text einfuegen, damit "NameAusschreibung" → "Name Ausschreibung"
            if self._current_cell:
                self._current_cell.append(' ')
            href = dict(attrs).get('href', '')
            if href:
                self._current_links.append(href)

    def handle_endtag(self, tag):
        if tag == 'table':
            self._in_table = False
        elif tag == 'td' and self._in_td:
            self._in_td = False
            self._current_row.append(' '.join(''.join(self._current_cell).split()))
            self._row_links.append(list(self._current_links))
        elif tag == 'th':
            self._in_th = False
        elif tag == 'tr' and self._in_table:
            if self._current_row:
                self.rows.append(self._current_row)
                self.row_links.append(list(self._row_links))

    def handle_data(self, data):
        if self._in_td:
            self._current_cell.append(data)


def parse_termine(html: str) -> list[dict]:
    """Extrahiert die Termine aus dem HTML der Termin-Seite (rein, ohne Netz).

    Returns: Liste von Event-Dicts mit keys: datum, datum_text, name, ort, link, tags.
    """
    parser = _TerminParser()
    parser.feed(html)

    events: list[dict] = []
    for row, links in zip(parser.rows, parser.row_links):
        if len(row) < 3:
            continue
        datum_text, name, ort = row[0].strip(), row[1].strip(), row[2].strip()
        name_lower = name.lower()
        # Training-Eintraege komplett ignorieren
        if 'training' in name_lower:
            continue
        # OeM U08/U10 und U12/U14 ignorieren
        if 'meisterschaften u' in name_lower:
            continue
        d, display = _parse_datum_flex(datum_text)
        if d is None:
            continue
        # Artefakte aus dem Namen entfernen
        for artifact in ['Ausschreibung', 'Anmeldung']:
            cleaned = name.replace(artifact, '').strip()
            if cleaned:
                name = cleaned
        # Zeitangaben entfernen ("Start: 10 Uhr", "10:00 Uhr Turnierbeginn")
        name = re.sub(r'\s*Start:\s*\d{1,2}(?::\d{2})?\s*Uhr\b', '', name).strip()
        name = re.sub(r'\s*\d{1,2}:\d{2}\s*Uhr\s*Turnierbeginn\b', '', name).strip()
        # "auf Chess-Results" entfernen
        name = re.sub(r'\s+auf Chess-Results\b', '', name).strip()
        # Link aus der Veranstaltungs-Spalte (Index 1) nehmen
        event_links = links[1] if len(links) > 1 else []
        link = event_links[0] if event_links else ''
        tags = []
        for keyword in ['schachrallye', 'rallye', 'schnellschach', 'blitz', '960']:
            if keyword in name_lower:
                tag = 'schachrallye' if keyword == 'rallye' else keyword
                if tag not in tags:
                    tags.append(tag)
        # Jugend-Tag: Jugend*, U08-U18 etc.
        if re.search(r'jugend|u\d{2}', name_lower):
            if 'jugend' not in tags:
                tags.append('jugend')
        # Senioren-Tag
        if 'senior' in name_lower:
            if 'senioren' not in tags:
                tags.append('senioren')
        # Klassisch-Tag (Open-Turniere)
        if 'open' in name_lower:
            if 'klassisch' not in tags:
                tags.append('klassisch')
        events.append({
            'datum': d.strftime('%Y-%m-%d'),
            'datum_text': display,
            'name': name,
            'ort': ort,
            'link': link,
            'tags': tags,
        })
    return events


def due_reminders(data, today: date) -> tuple[list[dict], list]:
    """Was der Reminder-Loop an ``today`` erinnern wuerde – rein, ohne I/O.

    Nur Termine mit Tag ``schachrallye``, freigegeben (``approved`` fehlt = Altbestand = frei),
    noch nicht erinnert und 1–7 Tage in der Zukunft. Ohne Rallye-Subscriber ist nichts faellig.

    Returns: (faellige Events in Dateireihenfolge, Rallye-Subscriber-IDs)
    """
    if not data or not isinstance(data, dict):
        return [], []
    events = data.get('events', [])
    subs = data.get('subscribers', {}).get('schachrallye', [])
    if not events or not subs:
        return [], subs

    due = []
    for event in events:
        if 'schachrallye' not in event.get('tags', []):
            continue
        if event.get('approved', True) is False:
            continue
        if event.get('reminded'):
            continue
        d = _parse_stored(event['datum'])
        if d is None:
            continue
        if d <= today:
            continue
        if (d - today).days <= 7:
            due.append(event)
    return due, subs
