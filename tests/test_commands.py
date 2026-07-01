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
    test_daily_refresh_no_duplicate_board,
    test_daily_remember_multichannel, test_apply_solver_update_fans_out, test_daily_language_de_en,
    test_sync_commands_public_vs_guild,
    test_webhook_verify_signature, test_webhook_handler_dispatches_to_apply_solver_update,
    test_daily_regenerate_webhook,
)
from test_cmd_community import (
    test_elo, test_resourcen, test_collection_limits, test_youtube,
    test_reminder, test_wanted, test_collection_duplicate_url,
)
from test_cmd_events import (
    test_schachrallye, test_turnier_sub, test_turnier_prune,
    test_turnier_review, test_turnier_approve_modal,
)
from test_cmd_weeklypost import (
    test_weekly_announcer, test_weekly_results_format,
    test_weekly_announcement_prefills_progress,
)
from test_cmd_leaderboard import (
    test_leaderboard_format, test_leaderboard_monthly_schedule,
    test_leaderboard_command, test_leaderboard_monthly_post,
    test_leaderboard_daily_thread_endstand,
)
from test_cmd_motivation import (
    test_motivation_command, test_motivation_builder, test_motivation_random_spruch,
    test_parse_zeit, test_activity_watcher, test_slacker_text,
    test_motivation_dm_retry, test_motivation_tournaments, test_player_progress_signature,
)
from test_cmd_library import (
    test_bibliothek, test_tag, test_autor, test_reindex, test_reindex_requires_admin,
    test_parse_index_entry, test_auto_tag, test_build_library_catalog,
    test_sftpgo_password_separated, test_public_domain_from,
)
from test_cmd_admin import (
    test_daily, test_ignore_kapitel, test_test_cmd, test_announce,
    test_greeted, test_stats, test_dm_log, test_log,
    test_dm_log_internals, test_dm_log_incoming, test_dm_permissions,
    test_suppress_empty_fen, test_es_tags,
)
from test_cmd_chat import (
    test_chat_whitelist, test_chat_clear, test_chat_routing,
    test_chat_history_prune, test_chat_history_sanitize,
    test_chat_no_key, test_puzzle_context,
    test_rate_hits_bounded, test_daily_token_cap,
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
    test_sftpgo_password_separated()
    test_public_domain_from()
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
    test_weekly_announcer()
    test_weekly_results_format()
    test_weekly_announcement_prefills_progress()
    test_leaderboard_format()
    test_leaderboard_monthly_schedule()
    test_leaderboard_command()
    test_leaderboard_monthly_post()
    test_leaderboard_daily_thread_endstand()
    test_parse_zeit()
    test_motivation_command()
    test_motivation_builder()
    test_motivation_tournaments()
    test_motivation_random_spruch()
    test_activity_watcher()
    test_slacker_text()
    test_player_progress_signature()
    test_motivation_dm_retry()
    test_healthcheck()
    test_build_puzzle_embed()
    test_build_daily_embed()
    test_post_rookhub_puzzle_board_vs_link()
    test_post_rookhub_puzzle_daily_uses_minimal_embed()
    test_daily_refresh_no_duplicate_board()
    test_daily_remember_multichannel()
    test_apply_solver_update_fans_out()
    test_daily_language_de_en()
    test_sync_commands_public_vs_guild()
    test_webhook_verify_signature()
    test_webhook_handler_dispatches_to_apply_solver_update()
    test_daily_regenerate_webhook()
    test_dm_log_internals()
    test_dm_log_incoming()
    test_dm_permissions()
    test_suppress_empty_fen()
    test_es_tags()
    test_chat_whitelist()
    test_chat_clear()
    test_chat_routing()
    test_rate_hits_bounded()
    test_daily_token_cap()
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
