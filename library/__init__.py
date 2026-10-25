"""Bibliothek-Katalog: index.txt parsen, Tags generieren, Suche, Slash-Commands.

Aufteilung (Zerlegung Z41, früher eine Datei ``library.py``):

- ``config``   – Umgebung (LIBRARY_INDEX, LIBRARY_ENFORCE_PD, SFTPGo) + ``_local_path``
- ``tags``     – Tag-Wörterbücher, ``_auto_tag``
- ``catalog``  – index.txt → library.json (``build_library_catalog``), ignore.json
- ``search``   – Katalog-Cache + Suche (``_search_library``, ``_ensure_library``)
- ``sharing``  – Gemeinfreiheits-Sperre, Formate auf der Disk, SFTPGo-Link
- ``views``    – Embed, Buch-Auswahl, Format-Buttons, Blättern
- ``commands`` – /bibliothek, /tag, /autor, /reindex (``setup``)

Andere Module greifen über die Untermodule zu (``library.search._search_library``),
damit Tests an genau einer Stelle patchen.
"""

from library import catalog, commands, config, search, sharing, tags, views
from library.commands import setup

__all__ = ['catalog', 'commands', 'config', 'search', 'setup', 'sharing', 'tags', 'views']
