"""Bibliothek: Teilen – Gemeinfreiheits-Sperre, vorhandene Formate, SFTPGo-Link.

- ``publicDomainFrom`` je Buch (Sidecar); gesperrt nur mit ``LIBRARY_ENFORCE_PD``
- ``_collect_formats``: welche Formate liegen auf der Disk (isfile → nur im Thread)
- SFTPGo-Share für Dateien über dem Discord-Limit; kein Link, solange der Share
  gesperrte Bücher preisgäbe (``_share_exposes_locked``)
"""

import logging
import os
from datetime import date

from library import config, search

log = logging.getLogger('schach-bot')

# ---------------------------------------------------------------------------
# Gemeinfreiheit (Public Domain) — pro Buch via Sidecar-Feld publicDomainFrom
# ---------------------------------------------------------------------------

def _pd_release(entry: dict) -> date | None:
    """Freigabedatum aus ``publicDomainFrom`` (ISO ``YYYY-MM-DD``) oder ``None``.

    Ohne (gültiges) Feld gilt das Buch als unbeschränkt teilbar (Opt-in-Sperre):
    nur ein gesetztes Zukunftsdatum sperrt das Teilen bis dahin.
    """
    raw = entry.get('publicDomainFrom')
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError:
        log.warning('publicDomainFrom unparsebar (%r) bei %s', raw, entry.get('id'))
        return None


def _is_locked(entry: dict) -> bool:
    """True, solange das Buch noch nicht gemeinfrei ist (Freigabedatum in der Zukunft).

    Nur wirksam bei aktivierter Durchsetzung (``LIBRARY_ENFORCE_PD``). Ist sie aus
    (Default), bleibt nichts gesperrt — das Datum ist dann reine Metainfo.
    """
    if not config.LIBRARY_ENFORCE_PD:
        return False
    rel = _pd_release(entry)
    return rel is not None and rel > date.today()


def _lock_note(entry: dict) -> str:
    """🔒-Hinweistext „frei ab <DD.MM.YYYY>" für gesperrte Bücher, sonst ''."""
    rel = _pd_release(entry)
    if rel is None or rel <= date.today():
        return ''
    return f'🔒 frei ab {rel.strftime("%d.%m.%Y")}'


def _collect_formats(entry: dict) -> dict[str, str]:
    """Gibt {ext: lokaler_pfad} für alle auf der Disk vorhandenen Formatvarianten zurück.

    Prüft entry['files'] sowie Geschwisterdateien mit gleichem Stem
    (die von convert_formats.sh erzeugt wurden).
    """
    found: dict[str, str] = {}
    stems: set[str] = set()

    for f in entry.get('files', []):
        local = config._local_path(f)
        if not local or not os.path.isfile(local):
            continue
        raw = os.path.splitext(local)[1].lower().lstrip('.')
        canon = 'djvu' if raw == 'djv' else raw
        if canon in ('pdf', 'djvu', 'epub') and canon not in found:
            found[canon] = local
        stems.add(os.path.splitext(local)[0])

    # Geschwisterdateien prüfen (z. B. durch Konvertierung erzeugt)
    for stem in stems:
        for ext in ('pdf', 'djvu', 'epub'):
            if ext not in found and os.path.isfile(f'{stem}.{ext}'):
                found[ext] = f'{stem}.{ext}'

    return found


def _sftpgo_configured() -> bool:
    return bool(config._SFTPGO_BASE_URL and config._SFTPGO_SHARE_ID)


def _share_exposes_locked() -> bool:
    """True, wenn der SFTPGo-Share bei aktiver Sperre gesperrte Bücher preisgäbe.

    Der Share deckt das ganze Bibliotheksverzeichnis ab (.env.example); der
    Browse-Link öffnet mit dem gemeinsamen Passwort den SFTPGo-Web-Client, in dem
    man frei navigiert, also auch zu gesperrten Büchern (Review W4s S4-022).
    Solange ein Katalog-Buch (auch ein per ignore.json ausgeblendetes) gesperrt
    ist, gibt der Bot deshalb keinen Share-Link aus.
    """
    if not config.LIBRARY_ENFORCE_PD:
        return False
    search._ensure_library()
    return any(_is_locked(e) for e in search._library_all)


def _sftpgo_link_allowed() -> bool:
    """Darf für eine Datei über dem Upload-Limit der Share-Link raus?"""
    return _sftpgo_configured() and not _share_exposes_locked()


def _share_block_note() -> str:
    """Zusatz zur „zu groß“-Meldung, wenn nur die Gemeinfreiheits-Sperre den Link verhindert."""
    if _sftpgo_configured() and _share_exposes_locked():
        return ('\nDen Link über den Datei-Share gibt es bei aktiver Gemeinfreiheits-Sperre '
                'nicht (der Share enthält auch noch gesperrte Bücher).')
    return ''


def _sftpgo_rel_path(local_path: str) -> str | None:
    """Gibt den relativen Pfad der Datei innerhalb der Library zurück."""
    if not config._LOCAL_BASE:
        return None
    from pathlib import Path
    try:
        resolved = Path(local_path).resolve()
        base = Path(config._LOCAL_BASE).resolve()
        rel = resolved.relative_to(base)
    except (ValueError, OSError):
        return None
    return str(rel).replace('\\', '/')


def _sftpgo_message(entry: dict, path: str, fmt: str, size: int | None = None) -> str:
    """Baut die ephemere Antwort-Nachricht mit Web-Client-Link (OHNE Passwort).

    Das Passwort wird bewusst NICHT in diese Nachricht gepackt — es geht als
    separate Nachricht (`_sftpgo_password_message`), damit es nicht im selben
    (kopier-/weiterleitbaren) Block wie der Link steht. ``size`` (Bytes) geben
    die Aufrufer mit, wenn sie sie schon kennen, dann fällt das getsize weg.
    _sftpgo_rel_path (Path.resolve) liest trotzdem den Bibliotheks-Mount →
    aus dem Event-Loop nur per asyncio.to_thread aufrufen.
    """
    from urllib.parse import quote
    rel        = _sftpgo_rel_path(path) or os.path.basename(path)
    encoded    = quote('/' + rel)
    browse_url = (f'{config._SFTPGO_BASE_URL}/web/client/pubshares/'
                  f'{config._SFTPGO_SHARE_ID}/browse?path={encoded}')
    if size is None:
        size = os.path.getsize(path)
    mb         = size / (1024 * 1024)
    msg = (f'📥 **{entry["title"]}** `[{fmt.upper()} · {mb:.1f} MB]`\n\n'
           f'🔗 {browse_url}')
    if config._SFTPGO_SHARE_PASSWORD:
        msg += '\n\n🔑 Das Passwort schicke ich dir gleich separat.'
    return msg


def _sftpgo_password_message() -> str | None:
    """Separate Nachricht NUR mit dem Share-Passwort (Spoiler), oder None wenn keins gesetzt."""
    if not config._SFTPGO_SHARE_PASSWORD:
        return None
    return f'🔑 Passwort: ||`{config._SFTPGO_SHARE_PASSWORD}`|| *(bitte nicht weitergeben)*'
