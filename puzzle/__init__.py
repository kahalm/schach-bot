"""Puzzle-Paket: buendelt Rendering, Loader, Lichess-Upload, State und Slash-Commands.

Alle oeffentlichen und internen Namen werden hier re-exportiert, damit
``import puzzle`` und ``puzzle.<name>`` als Convenience-Namespace funktionieren.
"""

# --- Zustand/Persistenz ---
from .state import (  # noqa: F401
    IGNORE_FILE, CHAPTER_IGNORE_FILE, BOOKS_DIR, PUZZLE_STUDY_ID,
    PUZZLE_STATE_FILE, USER_STUDIES_FILE, LICHESS_COOLDOWN_FILE,
    _PUZZLE_MSG_CAP, _puzzle_msg_ids,
    _register_puzzle_msg, is_puzzle_message, get_puzzle_line_id, get_puzzle_mode,
    _ignore_cache, _load_ignore_list, _invalidate_ignore_cache,
    ignore_puzzle, unignore_puzzle,
    _chapter_ignore_cache, _load_chapter_ignore_list, _invalidate_chapter_ignore_cache,
    _is_chapter_ignored, ignore_chapter, unignore_chapter, get_chapter_from_line_id,
    _endless_sessions, _ENDLESS_TIMEOUT_SECS,
    _evict_stale_endless, start_endless, stop_endless, is_endless, get_endless_session,
    load_puzzle_state, save_puzzle_state,
    _load_user_studies, _save_user_studies,
    _get_user_study_id, _get_user_puzzle_count, _set_user_study_id,
    _books_config_cache, _load_books_config, _invalidate_books_config_cache,
    _get_user_training, _set_user_training, _clear_user_training,
)

# --- PGN-Verarbeitung ---
from .processing import (  # noqa: F401
    _solution_pgn, _clean_book_name, _prelude_pgn, _has_training_comment,
    _trim_to_training_position, _split_for_blind, _format_blind_moves,
    _flatten_null_move_variations, _strip_pgn_annotations, _clean_pgn_for_lichess,
)

# --- Board-Rendering ---
from .rendering import _svg_to_pil, _get_piece, _label_font, _render_board, safe_render_board  # noqa: F401

# --- Auswahl/Caching ---
from .selection import (  # noqa: F401
    _find_chapter_prefix, _list_chapters, _list_pgn_files,
    _FATAL_STATUS, _lines_cache, _lines_cache_fp,
    _books_fingerprint, clear_lines_cache, load_all_lines, _parse_all_lines,
    pick_sequential_lines, get_random_books,
    pick_random_lines, pick_random_line, find_line_by_id,
    get_blind_books, pick_random_blind_lines,
)

# --- Lichess-API ---
from .lichess import (  # noqa: F401
    _LICHESS_STUDY_NAME_MAX, _LICHESS_CHAPTER_NAME_MAX,
    LICHESS_API_TIMEOUT, LICHESS_TOKEN,
    _extract_study_id, _export_pgn_for_lichess,
    _LICHESS_COOLDOWN_SECS, LichessRateLimitError,
    _lichess_cooldown_until, _lichess_rate_limited, _lichess_set_cooldown,
    _lichess_request, upload_to_lichess, upload_many_to_lichess,
)

# --- Embed-Bau ---
from .embed import build_puzzle_embed  # noqa: F401

# --- Posting ---
from .posting import (  # noqa: F401
    _DISCORD_THREAD_NAME_MAX, _upload_puzzles_async,
    _send_puzzle_followups, post_next_endless,
    _resilient_send, _send_optional,
    post_puzzle, post_blind_puzzle,
)

# --- Slash-Commands ---
from .commands import (  # noqa: F401
    _cmd_puzzle, _cmd_buecher, _cmd_train, _cmd_next,
    _cmd_endless, _cmd_ignore_kapitel, setup,
)

# Button-View fuer persistente Registrierung in bot.on_ready()
from .buttons import PuzzleView  # noqa: F401
