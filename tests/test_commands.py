"""
Runner fuer alle Command-Tests.

Ausfuehren: python tests/test_commands.py

Importiert Shared Infrastructure aus test_helpers.py und Tests aus den
test_cmd_*.py Domain-Dateien.
"""

import sys
import test_helpers as h

from test_cmd_info import (
    test_help, test_version, test_release_notes,
    test_event_log, test_healthcheck,
)
from test_cmd_puzzle import (
    test_puzzle, test_puzzle_blind_by_id, test_puzzle_link_only, test_kurs, test_train, test_next, test_endless, test_blind,
    test_buttons, test_format_blind_moves, test_puzzle_anzahl_validation,
    test_posted_reset_per_pool, test_build_puzzle_embed, test_build_daily_embed,
    test_post_rookhub_puzzle_board_vs_link, test_post_rookhub_puzzle_daily_uses_minimal_embed,
)
from test_cmd_community import (
    test_elo, test_resourcen, test_collection_limits, test_youtube,
    test_reminder, test_wanted, test_collection_duplicate_url,
)
from test_cmd_events import (
    test_schachrallye, test_turnier_sub, test_turnier_prune,
    test_turnier_review, test_turnier_approve_modal,
    test_wochenpost, test_wochenpost_batch, test_wochenpost_buttons,
    test_parse_zeit, test_wochenpost_sub, test_wochenpost_chat_spark,
    test_wochenpost_remind,
)
from test_cmd_library import (
    test_bibliothek, test_tag, test_autor, test_reindex, test_reindex_requires_admin,
    test_parse_index_entry, test_auto_tag, test_build_library_catalog,
)
from test_cmd_admin import (
    test_daily, test_ignore_kapitel, test_test_cmd, test_announce,
    test_greeted, test_stats, test_dm_log, test_log,
    test_dm_log_internals, test_dm_log_incoming, test_dm_permissions,
    test_suppress_empty_fen,
)
from test_cmd_chat import (
    test_chat_whitelist, test_chat_clear, test_chat_routing,
    test_chat_history_prune, test_chat_history_sanitize,
    test_chat_no_key, test_puzzle_context,
)
from test_cmd_chat_tools import (
    test_tool_schemas, test_tool_list_books, test_tool_get_training_status,
    test_tool_set_training, test_tool_suggest_book, test_tool_send_puzzle,
    test_tool_send_next, test_tool_error_handling, test_history_tool_blocks,
    test_history_backward_compat, test_tool_loop_limit, test_system_prompt_tools,
    test_tool_analyze_move, test_parse_first_solution_move,
    test_normalize_move, test_uci_line_to_san, test_analyze_move_edge_cases,
    test_tool_get_version, test_tool_get_help, test_tool_get_release_notes,
    test_tool_send_library_book,
)


def main():
    print(f'Slash-Command-Tests\n')

    test_help()
    test_version()
    test_elo()
    test_resourcen()
    test_collection_limits()
    test_youtube()
    test_puzzle()
    test_puzzle_blind_by_id()
    test_puzzle_link_only()
    test_kurs()
    test_train()
    test_next()
    test_endless()
    test_blind()
    test_daily()
    test_ignore_kapitel()
    test_test_cmd()
    test_bibliothek()
    test_tag()
    test_autor()
    test_reindex()
    test_reindex_requires_admin()
    test_reminder()
    test_announce()
    test_greeted()
    test_stats()
    test_wanted()
    test_release_notes()
    test_parse_index_entry()
    test_auto_tag()
    test_build_library_catalog()
    test_dm_log()
    test_log()
    test_schachrallye()
    test_turnier_sub()
    test_event_log()
    test_buttons()
    test_format_blind_moves()
    test_puzzle_anzahl_validation()
    test_collection_duplicate_url()
    test_turnier_prune()
    test_turnier_review()
    test_turnier_approve_modal()
    test_posted_reset_per_pool()
    test_wochenpost()
    test_wochenpost_batch()
    test_wochenpost_buttons()
    test_parse_zeit()
    test_wochenpost_sub()
    test_healthcheck()
    test_build_puzzle_embed()
    test_build_daily_embed()
    test_post_rookhub_puzzle_board_vs_link()
    test_post_rookhub_puzzle_daily_uses_minimal_embed()
    test_dm_log_internals()
    test_dm_log_incoming()
    test_dm_permissions()
    test_suppress_empty_fen()
    test_wochenpost_chat_spark()
    test_wochenpost_remind()
    test_chat_whitelist()
    test_chat_clear()
    test_chat_routing()
    test_chat_history_prune()
    test_chat_history_sanitize()
    test_chat_no_key()
    test_puzzle_context()
    test_tool_schemas()
    test_tool_list_books()
    test_tool_get_training_status()
    test_tool_set_training()
    test_tool_suggest_book()
    test_tool_send_puzzle()
    test_tool_send_next()
    test_tool_error_handling()
    test_history_tool_blocks()
    test_history_backward_compat()
    test_tool_loop_limit()
    test_system_prompt_tools()
    test_tool_analyze_move()
    test_parse_first_solution_move()
    test_normalize_move()
    test_uci_line_to_san()
    test_analyze_move_edge_cases()
    test_tool_get_version()
    test_tool_get_help()
    test_tool_get_release_notes()
    test_tool_send_library_book()

    print(f'---\n{h.total - h.failed}/{h.total} checks passed.')
    if h.failed:
        print(f'{h.failed} FAILED')
        sys.exit(1)
    else:
        print('Alle Tests OK.')


if __name__ == '__main__':
    main()
