"""Puzzle-Paket: bündelt Rendering, Loader, Lichess-Upload, State und Slash-Commands.

Wird Schritt für Schritt aus `legacy.py` aufgeteilt. Bis dahin werden alle
öffentlichen Namen (inkl. der von bot.py / commands.reminder verwendeten
Unterstrich-Namen) aus `legacy` re-exportiert, damit `import puzzle` und
`puzzle.<name>` weiter wie gewohnt funktionieren.
"""

from .legacy import *  # noqa: F401,F403

# Unterstrich-Namen werden von `import *` nicht erfasst – explizit re-exportieren.
from .legacy import _PUZZLE_REACTIONS  # noqa: F401
