"""Puzzle-Paket: bündelt Rendering, Loader, Lichess-Upload, State und Slash-Commands.

Wird Schritt für Schritt aus `legacy.py` aufgeteilt. Bis dahin werden alle
öffentlichen Namen (inkl. der von bot.py / commands.reminder verwendeten
Unterstrich-Namen) aus `legacy` re-exportiert, damit `import puzzle` und
`puzzle.<name>` weiter wie gewohnt funktionieren.
"""

from .legacy import (  # noqa: F401
    # Slash-Command-Setup
    setup,
    # Puzzle-Posting
    post_puzzle,
    post_blind_puzzle,
    post_next_endless,
    # Puzzle-Auswahl
    load_all_lines,
    clear_lines_cache,
    pick_random_lines,
    pick_random_line,
    pick_random_blind_lines,
    pick_sequential_lines,
    find_line_by_id,
    # Bücher
    get_random_books,
    get_blind_books,
    # Puzzle-State
    load_puzzle_state,
    save_puzzle_state,
    # Ignore-System
    ignore_puzzle,
    unignore_puzzle,
    ignore_chapter,
    unignore_chapter,
    get_chapter_from_line_id,
    # Puzzle-Nachrichten-Tracking
    is_puzzle_message,
    get_puzzle_line_id,
    get_puzzle_mode,
    # Endless-Modus
    start_endless,
    stop_endless,
    is_endless,
    # Embed-Bau
    build_puzzle_embed,
)

# Button-View für persistente Registrierung in bot.on_ready()
from .buttons import PuzzleView  # noqa: F401
