"""Zentrale Pfad-Konstanten.

Importiert via `from paths import CONFIG_DIR`.
Der `config/`-Ordner wird beim ersten Import automatisch angelegt.
"""

import os

CONFIG_DIR = 'config'
os.makedirs(CONFIG_DIR, exist_ok=True)
