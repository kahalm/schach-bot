"""Bibliothek: Konfiguration aus der Umgebung + Pfad-Übersetzung index.txt → lokal.

Wird beim Import EINMAL gelesen (wie bisher library.py). Alle anderen Module der
Bibliothek lesen die Werte zur Laufzeit als ``config.<NAME>`` (Tests setzen sie hier).
"""

import logging
import os
import re

log = logging.getLogger('schach-bot')

# --- Config (aus Umgebung) ---

LIBRARY_INDEX = os.getenv('LIBRARY_INDEX', '')
LIBRARY_FILE  = (os.path.join(os.path.dirname(LIBRARY_INDEX), 'library.json')
                 if LIBRARY_INDEX else 'library.json')
# Lokaler Basis-Pfad (Verzeichnis der index.txt) für Pfad-Übersetzung
_LOCAL_BASE   = os.path.dirname(LIBRARY_INDEX) if LIBRARY_INDEX else ''

# Gemeinfreiheits-Sperre durchsetzen? Default AUS: das ``publicDomainFrom``-Feld
# wird zwar im Katalog gespeichert (reine Daten), sperrt aber nichts. Erst mit
# ``LIBRARY_ENFORCE_PD=1`` werden noch nicht gemeinfreie Bücher in der Anzeige
# markiert und vom Teilen ausgeschlossen.
LIBRARY_ENFORCE_PD = os.getenv('LIBRARY_ENFORCE_PD', '').strip().lower() in ('1', 'true', 'yes', 'on')

# SFTPGo-Config für Dateien über dem Discord-Upload-Limit
_SFTPGO_BASE_URL       = os.getenv('SFTPGO_BASE_URL', '').rstrip('/')
_SFTPGO_SHARE_ID       = os.getenv('SFTPGO_SHARE_ID', '')
_SFTPGO_SHARE_PASSWORD = os.getenv('SFTPGO_SHARE_PASSWORD', '')

_REMOTE_PREFIX_RE = re.compile(r'.*/schach/')


_IGNORE_FILE = 'ignore.json'


_MAX_UPLOAD = 8 * 1024 * 1024  # Discord-Limit 8 MB (ohne Nitro)


def _local_path(remote: str) -> str | None:
    """Übersetzt einen remote-Pfad aus index.txt in den lokalen Syncthing-Pfad.

    Gibt ``None`` zurück wenn der resultierende Pfad außerhalb von
    ``_LOCAL_BASE`` liegt (Path-Traversal-Schutz).
    """
    suffix = _REMOTE_PREFIX_RE.sub('', remote)
    if not _LOCAL_BASE:
        return remote
    path = os.path.normpath(os.path.join(_LOCAL_BASE, suffix))
    base = os.path.normpath(_LOCAL_BASE)
    if not (path == base or path.startswith(base + os.sep)):
        log.warning('Path-Traversal blockiert: %s', remote)
        return None
    return path
