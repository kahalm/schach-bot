"""Tests fuer Chat-Tools: Tool-Schemas, Handler, History mit Tool-Blocks."""

import json
import test_helpers as h
from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    atomic_write, atomic_read, FakeChannel,
)
from unittest.mock import patch, MagicMock, AsyncMock

import commands.chat as chat_mod
from commands.chat_tools import TOOLS, execute_tool


def test_tool_schemas():
    """Validiert dass alle Tool-Schemas korrekt aufgebaut sind."""
    print('[chat_tool_schemas]')
    check('10 Tools definiert', len(TOOLS) == 10)
    names = set()
    for tool in TOOLS:
        check(f'Tool {tool["name"]} hat name', 'name' in tool)
        check(f'Tool {tool["name"]} hat description', 'description' in tool)
        check(f'Tool {tool["name"]} hat input_schema', 'input_schema' in tool)
        check(f'Tool {tool["name"]} schema hat type',
              tool['input_schema'].get('type') == 'object')
        names.add(tool['name'])
    expected = {'list_books', 'suggest_book', 'get_training_status',
                'set_training', 'send_puzzle', 'send_next', 'analyze_move',
                'get_version', 'get_help', 'get_release_notes'}
    check('Alle erwarteten Tool-Namen vorhanden', names == expected)


def test_tool_list_books():
    """Test fuer list_books Tool-Handler."""
    print('[tool_list_books]')
    tmpdir = setup_temp_config()
    try:
        fake_books = ['buch_a.pgn', 'buch_b.pgn']
        fake_config = {
            'buch_a.pgn': {'difficulty': 'Anfaenger', 'rating': 3,
                           'tags': ['Taktik'], 'description': 'Buch A'},
            'buch_b.pgn': {'difficulty': 'Meister', 'rating': 7},
        }
        fake_lines = [('buch_a.pgn:1', None), ('buch_a.pgn:2', None),
                      ('buch_b.pgn:1', None)]

        with patch('commands.chat_tools._tool_list_books.__module__', 'commands.chat_tools'):
            pass
        # Direkt die Funktionen patchen die im Handler aufgerufen werden
        with patch('puzzle.selection._list_pgn_files', return_value=fake_books), \
             patch('puzzle.state._load_books_config', return_value=fake_config), \
             patch('puzzle.selection.load_all_lines', return_value=fake_lines):
            from commands.chat_tools import _tool_list_books
            result_str = run_async(_tool_list_books({}, {}))
            result = json.loads(result_str)

        check('list_books gibt Liste zurueck', isinstance(result, list))
        check('list_books 2 Buecher', len(result) == 2)
        check('Buch 1 Name', result[0]['name'] != '')
        check('Buch 1 hat Tags', result[0].get('tags') == ['Taktik'])
        check('Buch 1 hat Description', result[0].get('description') == 'Buch A')
        check('Buch 2 Linien = 1', result[1]['linien'] == 1)
        check('Buch 1 Linien = 2', result[0]['linien'] == 2)
    finally:
        teardown_temp_config(tmpdir)


def test_tool_get_training_status():
    """Test fuer get_training_status Tool-Handler."""
    print('[tool_get_training_status]')
    tmpdir = setup_temp_config()
    try:
        fake_training = {'book': 'buch_a.pgn', 'position': 5}
        fake_lines = [('buch_a.pgn:' + str(i), None) for i in range(20)]

        with patch('puzzle.state._get_user_training', return_value=fake_training), \
             patch('puzzle.state._get_user_puzzle_count', return_value=(3, 15)), \
             patch('puzzle.selection.load_all_lines', return_value=fake_lines), \
             patch('puzzle.selection._list_pgn_files', return_value=['buch_a.pgn']), \
             patch('puzzle.processing._clean_book_name', return_value='Buch A'):
            from commands.chat_tools import _tool_get_training_status
            result_str = run_async(_tool_get_training_status(
                {}, {'user_id': 42}))
            result = json.loads(result_str)

        check('training vorhanden', result.get('training') is not None)
        check('training position = 5', result['training']['position'] == 5)
        check('training total = 20', result['training']['total'] == 20)
        check('puzzles_heute = 3', result['puzzles_heute'] == 3)
        check('puzzles_gesamt = 15', result['puzzles_gesamt'] == 15)

        # Ohne Training
        with patch('puzzle.state._get_user_training', return_value=None), \
             patch('puzzle.state._get_user_puzzle_count', return_value=(0, 0)):
            result_str = run_async(_tool_get_training_status(
                {}, {'user_id': 99}))
            result = json.loads(result_str)

        check('ohne Training → None', result['training'] is None)
    finally:
        teardown_temp_config(tmpdir)


def test_tool_set_training():
    """Test fuer set_training Tool-Handler."""
    print('[tool_set_training]')
    tmpdir = setup_temp_config()
    try:
        fake_books = ['buch_a.pgn', 'buch_b.pgn']
        set_calls = []

        def fake_set(uid, book, pos):
            set_calls.append((uid, book, pos))

        clear_calls = []

        def fake_clear(uid):
            clear_calls.append(uid)

        with patch('puzzle.selection._list_pgn_files', return_value=fake_books), \
             patch('puzzle.state._set_user_training', side_effect=fake_set), \
             patch('puzzle.state._clear_user_training', side_effect=fake_clear), \
             patch('puzzle.state._get_user_training', return_value=None), \
             patch('puzzle.processing._clean_book_name', return_value='Buch A'):
            from commands.chat_tools import _tool_set_training

            # buch=0 → Training beenden
            result_str = run_async(_tool_set_training(
                {'buch': 0}, {'user_id': 42}))
            result = json.loads(result_str)
            check('buch=0 → clear aufgerufen', len(clear_calls) == 1)
            check('buch=0 → status-Meldung', 'beendet' in result.get('status', '').lower())

            # buch=1 → Training setzen
            result_str = run_async(_tool_set_training(
                {'buch': 1}, {'user_id': 42}))
            result = json.loads(result_str)
            check('buch=1 → set aufgerufen', len(set_calls) == 1)
            check('buch=1 → korrektes Buch', set_calls[0][1] == 'buch_a.pgn')

            # buch out of range → Fehler
            result_str = run_async(_tool_set_training(
                {'buch': 99}, {'user_id': 42}))
            result = json.loads(result_str)
            check('buch=99 → Fehler', 'error' in result)

    finally:
        teardown_temp_config(tmpdir)


def test_tool_suggest_book():
    """Test fuer suggest_book Tool-Handler."""
    print('[tool_suggest_book]')
    tmpdir = setup_temp_config()
    try:
        fake_books = ['taktik.pgn', 'endspiel.pgn']
        fake_config = {
            'taktik.pgn': {'difficulty': 'Anfaenger', 'rating': 5,
                           'tags': ['Taktik'], 'description': 'Taktik-Buch'},
            'endspiel.pgn': {'difficulty': 'Meister', 'rating': 7,
                             'tags': ['Endspiel'], 'description': 'Endspiel-Buch'},
        }

        with patch('puzzle.selection._list_pgn_files', return_value=fake_books), \
             patch('puzzle.state._load_books_config', return_value=fake_config), \
             patch('puzzle.processing._clean_book_name', side_effect=lambda fn: fn.replace('.pgn', '')):
            from commands.chat_tools import _tool_suggest_book

            # Filter nach Schwierigkeit
            result_str = run_async(_tool_suggest_book(
                {'difficulty': 'Anfaenger'}, {}))
            result = json.loads(result_str)
            check('Anfaenger → 1 Treffer',
                  len(result['puzzle_buecher']) == 1)
            check('Anfaenger → taktik',
                  result['puzzle_buecher'][0]['name'] == 'taktik')

            # Filter nach Query
            result_str = run_async(_tool_suggest_book(
                {'query': 'Endspiel'}, {}))
            result = json.loads(result_str)
            check('Query Endspiel → 1 Treffer',
                  len(result['puzzle_buecher']) == 1)

            # Ohne Filter → alle
            result_str = run_async(_tool_suggest_book({}, {}))
            result = json.loads(result_str)
            check('Ohne Filter → alle Buecher',
                  len(result['puzzle_buecher']) == 2)

    finally:
        teardown_temp_config(tmpdir)


def test_tool_send_puzzle():
    """Test fuer send_puzzle Tool-Handler."""
    print('[tool_send_puzzle]')
    tmpdir = setup_temp_config()
    try:
        channel = FakeChannel()

        with patch('puzzle.posting.post_puzzle', new_callable=AsyncMock,
                   return_value=3) as mock_post:
            from commands.chat_tools import _tool_send_puzzle
            result_str = run_async(_tool_send_puzzle(
                {'count': 3, 'buch': 2},
                {'user_id': 42, 'channel': channel}))
            result = json.loads(result_str)

        check('send_puzzle → gesendet=3', result['gesendet'] == 3)
        check('send_puzzle → angefragt=3', result['angefragt'] == 3)
        check('post_puzzle aufgerufen', mock_post.called)
        check('post_puzzle count=3', mock_post.call_args.kwargs.get('count') == 3)
        check('post_puzzle book_idx=2', mock_post.call_args.kwargs.get('book_idx') == 2)

        # Ohne Channel → Fehler
        from commands.chat_tools import _tool_send_puzzle
        result_str = run_async(_tool_send_puzzle(
            {'count': 1}, {'user_id': 42, 'channel': None}))
        result = json.loads(result_str)
        check('ohne Channel → Fehler', 'error' in result)

    finally:
        teardown_temp_config(tmpdir)


def test_tool_send_next():
    """Test fuer send_next Tool-Handler."""
    print('[tool_send_next]')
    tmpdir = setup_temp_config()
    try:
        channel = FakeChannel()
        fake_result = {'sent': 2, 'new_position': 7, 'total': 20,
                       'book': 'Taktik', 'finished': False}

        with patch('puzzle.commands.send_next_training',
                   new_callable=AsyncMock, return_value=fake_result):
            from commands.chat_tools import _tool_send_next
            result_str = run_async(_tool_send_next(
                {'count': 2},
                {'user_id': 42, 'channel': channel}))
            result = json.loads(result_str)

        check('send_next → sent=2', result['sent'] == 2)
        check('send_next → book=Taktik', result['book'] == 'Taktik')
        check('send_next → new_position=7', result['new_position'] == 7)

    finally:
        teardown_temp_config(tmpdir)


def test_tool_error_handling():
    """Test dass Tool-Fehler als Error-String zurueckgegeben werden."""
    print('[tool_error_handling]')

    # Unbekanntes Tool
    result_str = run_async(execute_tool('nonexistent', {}, {}))
    result = json.loads(result_str)
    check('unbekanntes Tool → error', 'error' in result)

    # Handler wirft Exception
    with patch('commands.chat_tools._tool_list_books',
               side_effect=RuntimeError('Testfehler')):
        # execute_tool nutzt _HANDLERS dict, also muessen wir dort patchen
        import commands.chat_tools as ct
        original = ct._HANDLERS['list_books']
        ct._HANDLERS['list_books'] = AsyncMock(side_effect=RuntimeError('Testfehler'))
        try:
            result_str = run_async(execute_tool('list_books', {}, {}))
            result = json.loads(result_str)
            check('Exception → error-String', 'error' in result)
            check('Exception → kein Crash', True)
        finally:
            ct._HANDLERS['list_books'] = original


def test_history_tool_blocks():
    """Test dass History mit Tool-Blocks korrekt gespeichert und geladen wird."""
    print('[history_tool_blocks]')
    tmpdir = setup_temp_config()
    try:
        atomic_write(chat_mod.CHAT_FILE, {'history': {}})

        # Erst eine User-Nachricht, damit History nicht leer-gepruned wird
        chat_mod._append_and_get_history(42, 'Zeig mir die Buecher')

        # Simulierte tool_use Response-Blocks
        class FakeTextBlock:
            type = 'text'
            text = 'Ich schaue mal nach...'

        class FakeToolUseBlock:
            type = 'tool_use'
            id = 'toolu_123'
            name = 'list_books'
            input = {}

        blocks = [FakeTextBlock(), FakeToolUseBlock()]
        serialized = chat_mod._serialize(blocks)

        check('serialize → 2 Eintraege', len(serialized) == 2)
        check('serialize text-Block', serialized[0] == {'type': 'text', 'text': 'Ich schaue mal nach...'})
        check('serialize tool_use-Block',
              serialized[1] == {'type': 'tool_use', 'id': 'toolu_123',
                                'name': 'list_books', 'input': {}})

        # extract_text
        text = chat_mod._extract_text(blocks)
        check('extract_text → nur Text', text == 'Ich schaue mal nach...')

        # Speichern + Laden Roundtrip
        chat_mod._save_response_blocks(42, blocks)
        data = atomic_read(chat_mod.CHAT_FILE, dict)
        msgs = data.get('history', {}).get('42', [])
        # msgs[0] = user, msgs[1] = assistant
        check('response_blocks gespeichert', len(msgs) == 2)
        check('response_blocks role=assistant', msgs[1]['role'] == 'assistant')
        check('response_blocks content ist Liste', isinstance(msgs[1]['content'], list))

        # Tool-Results speichern
        tool_results = [
            {'type': 'tool_result', 'tool_use_id': 'toolu_123',
             'content': '{"books": []}'}
        ]
        chat_mod._save_tool_results(42, tool_results)
        data = atomic_read(chat_mod.CHAT_FILE, dict)
        msgs = data.get('history', {}).get('42', [])
        check('tool_results gespeichert', len(msgs) == 3)
        check('tool_results role=user', msgs[2]['role'] == 'user')

    finally:
        teardown_temp_config(tmpdir)


def test_history_backward_compat():
    """Test dass alte String-History-Eintraege weiterhin funktionieren."""
    print('[history_backward_compat]')
    tmpdir = setup_temp_config()
    try:
        # Alte History mit String-Content
        old_history = {
            'history': {
                '42': [
                    {'role': 'user', 'content': 'Hallo'},
                    {'role': 'assistant', 'content': 'Hi!'},
                ]
            }
        }
        atomic_write(chat_mod.CHAT_FILE, old_history)

        # Neuen Eintrag hinzufuegen
        msgs = chat_mod._append_and_get_history(42, 'Noch eine Frage')
        check('backward compat: 3 Nachrichten', len(msgs) == 3)
        check('backward compat: alte User-Msg erhalten',
              msgs[0]['content'] == 'Hallo')
        check('backward compat: alte Assistant-Msg erhalten',
              msgs[1]['content'] == 'Hi!')
        check('backward compat: neue Msg dazu',
              msgs[2]['content'] == 'Noch eine Frage')

    finally:
        teardown_temp_config(tmpdir)


def test_tool_loop_limit():
    """Test dass _MAX_TOOL_ROUNDS die Tool-Loop begrenzt."""
    print('[tool_loop_limit]')
    check('MAX_TOOL_ROUNDS ist 5', chat_mod._MAX_TOOL_ROUNDS == 5)


def test_system_prompt_tools():
    """Test dass der System-Prompt den Tool-Hinweis enthaelt."""
    print('[system_prompt_tools]')
    prompt = chat_mod._SYSTEM_PROMPT
    check('System-Prompt enthaelt Tool-Hinweis', 'Tools' in prompt)
    check('System-Prompt enthaelt Puzzles', 'Puzzles' in prompt)
    check('System-Prompt enthaelt analyze_move-Hinweis', 'analyze_move' in prompt)


def test_tool_analyze_move():
    """Test fuer analyze_move Tool-Handler — 7 Faelle."""
    print('[tool_analyze_move]')
    from commands.chat_tools import _analyze_move_sync, _tool_analyze_move

    # Puzzle-FEN: Weiss am Zug, Loesung beginnt mit e4
    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    solution = 'e4 e5 Nf3'
    ctx_puzzle = {
        'fen': fen,
        'solution': solution,
        'book': 'Test',
        'chapter': 'Kap 1',
        'turn': 'Weiss',
        'difficulty': 'Anfaenger',
    }

    # 1. Korrekter Zug (SAN)
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle):
        r = _analyze_move_sync('e4', 42)
    check('korrekter SAN → is_correct', r.get('is_correct') is True)
    check('korrekter SAN → user_move_san', r.get('user_move_san') == 'e4')
    check('korrekter SAN → opponent_reply_san', r.get('opponent_reply_san') == 'e5')

    # 2. Korrekter Zug (UCI)
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle):
        r = _analyze_move_sync('e2e4', 42)
    check('korrekter UCI → is_correct', r.get('is_correct') is True)
    check('korrekter UCI → opponent_reply_san', r.get('opponent_reply_san') == 'e5')

    # 3. Falscher Zug + Cloud-Eval Mock
    mock_cloud = {
        'depth': 36,
        'pvs': [{'cp': 50, 'moves': 'e7e5 g1f3 b8c6'}],
    }
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle), \
         patch('commands.chat_tools._fetch_cloud_eval', return_value=mock_cloud):
        r = _analyze_move_sync('d4', 42)
    check('falscher Zug → is_correct=False', r.get('is_correct') is False)
    check('falscher Zug → eval_cp', 'eval_cp' in r)
    check('falscher Zug → eval_cp invertiert', r.get('eval_cp') == -50)
    check('falscher Zug → best_line_san', 'best_line_san' in r)
    check('falscher Zug → kein solution_first_move', 'solution_first_move' not in r)
    check('falscher Zug → depth', r.get('depth') == 36)
    check('falscher Zug → fen_after_response', 'fen_after_response' in r)
    # FEN nach d4 e5: Stellung nach beiden Zuegen
    import chess as _chess
    _b = _chess.Board(fen)
    _b.push_san('d4')
    _b.push_san('e5')
    check('falscher Zug → fen_after_response korrekt', r['fen_after_response'] == _b.fen())

    # 4. Falscher Zug + Cloud-Eval 404 (None)
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle), \
         patch('commands.chat_tools._fetch_cloud_eval', return_value=None):
        r = _analyze_move_sync('a3', 42)
    check('ohne Cloud-Eval → is_correct=False', r.get('is_correct') is False)
    check('ohne Cloud-Eval → kein solution_first_move', 'solution_first_move' not in r)
    check('ohne Cloud-Eval → kein eval_cp', 'eval_cp' not in r)
    check('ohne Cloud-Eval → kein fen_after_response', 'fen_after_response' not in r)

    # 5. Ungueltiger Zug
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle):
        r = _analyze_move_sync('Zx9', 42)
    check('ungueltiger Zug → error', 'error' in r)
    check('ungueltiger Zug → Meldung', 'Zx9' in r.get('error', ''))

    # 6. Kein Puzzle-Kontext
    with patch('puzzle.state.get_puzzle_context', return_value=None):
        r = _analyze_move_sync('e4', 99)
    check('kein Puzzle → error', 'error' in r)
    check('kein Puzzle → Meldung', 'Puzzle' in r.get('error', ''))

    # 7. FEN-Override
    override_fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1'
    with patch('commands.chat_tools._fetch_cloud_eval', return_value=None):
        r = _analyze_move_sync('e5', 42, fen_override=override_fen)
    check('FEN-Override → kein error', 'error' not in r)
    check('FEN-Override → is_correct=False (keine Loesung)', r.get('is_correct') is False)
    check('FEN-Override → user_move_san', r.get('user_move_san') == 'e5')

    # 8. Korrekter Zug ohne Gegenzug (Loesung hat nur 1 Zug)
    ctx_single = dict(ctx_puzzle, solution='e4')
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_single):
        r = _analyze_move_sync('e4', 42)
    check('einzelzug → is_correct', r.get('is_correct') is True)
    check('einzelzug → kein opponent_reply', 'opponent_reply_san' not in r)

    # 9. Deutsche Notation: Sf3 → Nf3
    ctx_nf3 = dict(ctx_puzzle, solution='Nf3 Nc6')
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_nf3):
        r = _analyze_move_sync('Sf3', 42)
    check('deutsch S → is_correct', r.get('is_correct') is True)
    check('deutsch S → user_move_san=Nf3', r.get('user_move_san') == 'Nf3')

    # 10. Deutsche Notation: alle Figuren
    # D=Q, T=R, L=B — teste mit falschem Zug (Zug ist legal aber nicht Loesung)
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle), \
         patch('commands.chat_tools._fetch_cloud_eval', return_value=None):
        r = _analyze_move_sync('Sf3', 42)
    check('deutsch Sf3 falsch → is_correct=False', r.get('is_correct') is False)
    check('deutsch Sf3 falsch → user_move_san=Nf3', r.get('user_move_san') == 'Nf3')

    # 11. Annotationen werden ignoriert: e4+ → e4
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle):
        r = _analyze_move_sync('e4+', 42)
    check('e4+ → is_correct', r.get('is_correct') is True)

    # 12. Annotation #
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle):
        r = _analyze_move_sync('e4#', 42)
    check('e4# → is_correct', r.get('is_correct') is True)

    # 13. Deutsch + Annotation: Sf3!
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_nf3):
        r = _analyze_move_sync('Sf3!', 42)
    check('Sf3! → is_correct', r.get('is_correct') is True)

    # 14. Falscher Zug aber stark (eval > +300)
    mock_winning = {
        'depth': 40,
        'pvs': [{'cp': -1500, 'moves': 'e7e8'}],
    }
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle), \
         patch('commands.chat_tools._fetch_cloud_eval', return_value=mock_winning):
        r = _analyze_move_sync('d4', 42)
    check('starker falscher Zug → eval_cp=+1500', r.get('eval_cp') == 1500)
    check('starker falscher Zug → is_correct=False', r.get('is_correct') is False)

    # 15. Async-Handler
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle):
        result_str = run_async(_tool_analyze_move(
            {'move': 'e4'}, {'user_id': 42}))
        r = json.loads(result_str)
    check('async handler → is_correct', r.get('is_correct') is True)


def test_parse_first_solution_move():
    """Test fuer _parse_first_solution_move: PGN-Parser + Fallback."""
    print('[parse_first_solution_move]')
    import chess
    from commands.chat_tools import _parse_first_solution_move

    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

    # Standard-PGN mit Zugnummern
    m = _parse_first_solution_move(fen, '1. e4 e5 2. Nf3')
    check('PGN mit Zugnummern → e4', m == chess.Move.from_uci('e2e4'))

    # Ohne Zugnummern (nur SAN)
    m = _parse_first_solution_move(fen, 'e4 e5 Nf3')
    check('ohne Zugnummern → e4', m == chess.Move.from_uci('e2e4'))

    # Hohe Zugnummer (Fallback noetig wenn PGN-Parser versagt)
    fen32 = '7b/p1r1k3/1p2P1Rp/4Nn2/5P2/3R4/1P5P/4K3 w - - 0 32'
    m = _parse_first_solution_move(fen32, '32. Rg7+ Ke8 33. Rxh8#')
    check('hohe Zugnummer → Rg7+', m is not None)
    check('hohe Zugnummer → korrekte from-sq',
          m == chess.Move.from_uci('g6g7'))

    # Mit Varianten und Kommentaren
    m = _parse_first_solution_move(fen, '1. e4 {bester Zug} (1. d4 d5) 1... e5')
    check('mit Kommentaren → e4', m == chess.Move.from_uci('e2e4'))

    # Leere Loesung
    m = _parse_first_solution_move(fen, '')
    check('leere Loesung → None', m is None)

    # Ungueltige Loesung
    m = _parse_first_solution_move(fen, 'Zx9 blah')
    check('ungueltige Loesung → None', m is None)


def test_normalize_move():
    """Test fuer _normalize_move: deutsche Notation + Annotationen."""
    print('[normalize_move]')
    from commands.chat_tools import _normalize_move

    check('Sf3 → Nf3', _normalize_move('Sf3') == 'Nf3')
    check('Dxf7 → Qxf7', _normalize_move('Dxf7') == 'Qxf7')
    check('Td1 → Rd1', _normalize_move('Td1') == 'Rd1')
    check('Lc4 → Bc4', _normalize_move('Lc4') == 'Bc4')
    check('Nf3 bleibt Nf3', _normalize_move('Nf3') == 'Nf3')
    check('e4 bleibt e4', _normalize_move('e4') == 'e4')
    check('Qxf7+ → Qxf7', _normalize_move('Qxf7+') == 'Qxf7')
    check('Sf3# → Nf3', _normalize_move('Sf3#') == 'Nf3')
    check('e4! → e4', _normalize_move('e4!') == 'e4')
    check('Dxf7+! → Qxf7', _normalize_move('Dxf7+!') == 'Qxf7')
    check('O-O bleibt', _normalize_move('O-O') == 'O-O')
    check('Leerzeichen getrimmt', _normalize_move(' Sf3 ') == 'Nf3')


def test_uci_line_to_san():
    """Test fuer UCI→SAN Konvertierung mit echtem python-chess."""
    print('[uci_line_to_san]')
    from commands.chat_tools import _uci_line_to_san

    # Startstellung nach 1.e4
    fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1'
    san = _uci_line_to_san(fen, 'e7e5 g1f3 b8c6')
    check('UCI→SAN 3 Zuege', len(san) == 3)
    check('UCI→SAN erster Zug', san[0] == 'e5')
    check('UCI→SAN zweiter Zug', san[1] == 'Nf3')
    check('UCI→SAN dritter Zug', san[2] == 'Nc6')

    # Leerer String
    san_empty = _uci_line_to_san(fen, '')
    check('UCI→SAN leer → leere Liste', san_empty == [])

    # Nur Whitespace
    san_ws = _uci_line_to_san(fen, '   ')
    check('UCI→SAN whitespace → leere Liste', san_ws == [])

    # Ungueltiger UCI mittendrin → bricht ab, gibt bisherige Zuege zurueck
    san_bad = _uci_line_to_san(fen, 'e7e5 XXXX b8c6')
    check('UCI→SAN bad mid → 1 Zug', len(san_bad) == 1)
    check('UCI→SAN bad mid → erster Zug ok', san_bad[0] == 'e5')

    # Rochade
    fen_castle = 'r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1'
    san_castle = _uci_line_to_san(fen_castle, 'e1g1')
    check('UCI→SAN Rochade', len(san_castle) == 1)
    check('UCI→SAN Rochade → O-O', san_castle[0] == 'O-O')

    # Promotion
    fen_promo = '8/P7/8/8/8/8/8/4K2k w - - 0 1'
    san_promo = _uci_line_to_san(fen_promo, 'a7a8q')
    check('UCI→SAN Promotion', len(san_promo) == 1)
    check('UCI→SAN Promotion → a8=Q+', san_promo[0] == 'a8=Q+')


def test_analyze_move_edge_cases():
    """Test fuer analyze_move Edge Cases: leere PV, Matt-Eval."""
    print('[analyze_move_edge_cases]')
    from commands.chat_tools import _analyze_move_sync

    fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    solution = 'e4 e5 Nf3'
    ctx_puzzle = {
        'fen': fen, 'solution': solution,
        'book': 'Test', 'chapter': 'Kap 1',
        'turn': 'Weiss', 'difficulty': 'Anfaenger',
    }

    # 1. Cloud-Eval mit leerer moves-Zeile
    mock_empty_pv = {'depth': 30, 'pvs': [{'cp': 10, 'moves': ''}]}
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle), \
         patch('commands.chat_tools._fetch_cloud_eval', return_value=mock_empty_pv):
        r = _analyze_move_sync('d4', 42)
    check('leere PV → kein Crash', 'error' not in r)
    check('leere PV → is_correct=False', r.get('is_correct') is False)
    check('leere PV → kein best_response_san', 'best_response_san' not in r)
    check('leere PV → kein fen_after_response', 'fen_after_response' not in r)

    # 2. Cloud-Eval mit whitespace-only moves
    mock_ws_pv = {'depth': 30, 'pvs': [{'cp': 10, 'moves': '   '}]}
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle), \
         patch('commands.chat_tools._fetch_cloud_eval', return_value=mock_ws_pv):
        r = _analyze_move_sync('d4', 42)
    check('whitespace PV → kein Crash', 'error' not in r)
    check('whitespace PV → kein best_response_san', 'best_response_san' not in r)

    # 3. Matt-Eval (mate statt cp)
    mock_mate = {
        'depth': 40,
        'pvs': [{'mate': -3, 'moves': 'e7e5 g1f3 b8c6'}],
    }
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle), \
         patch('commands.chat_tools._fetch_cloud_eval', return_value=mock_mate):
        r = _analyze_move_sync('d4', 42)
    check('matt eval → eval_mate vorhanden', 'eval_mate' in r)
    check('matt eval → eval_mate invertiert', r.get('eval_mate') == 3)
    check('matt eval → kein eval_cp', 'eval_cp' not in r)
    check('matt eval → best_response_san', r.get('best_response_san') == 'e5')

    # 4. Cloud-Eval mit leerer pvs-Liste
    mock_no_pvs = {'depth': 30, 'pvs': []}
    with patch('puzzle.state.get_puzzle_context', return_value=ctx_puzzle), \
         patch('commands.chat_tools._fetch_cloud_eval', return_value=mock_no_pvs):
        r = _analyze_move_sync('d4', 42)
    check('leere pvs → kein Crash', 'error' not in r)
    check('leere pvs → kein eval_cp', 'eval_cp' not in r)


def test_tool_get_version():
    """Test fuer get_version Tool-Handler."""
    print('[tool_get_version]')
    from commands.chat_tools import _tool_get_version
    result_str = run_async(_tool_get_version({}, {}))
    result = json.loads(result_str)
    check('get_version hat version', 'version' in result)
    check('get_version hat git_sha', 'git_sha' in result)
    check('get_version hat start_time', 'start_time' in result)
    check('get_version version ist String', isinstance(result['version'], str))
    check('get_version version nicht leer', len(result['version']) > 0)


def test_tool_get_help():
    """Test fuer get_help Tool-Handler."""
    print('[tool_get_help]')
    from commands.chat_tools import _tool_get_help

    # Mock _help_fields um circular import zu vermeiden
    fake_fields = {
        'puzzle': ('🧩 Puzzles', [('/puzzle', 'Puzzle senden'), ('/kurs', 'Kurse anzeigen')]),
        'bibliothek': ('📚 Bibliothek', [('/bibliothek', 'Suchen')]),
        'community': ('🌐 Community', [('/elo', 'Elo setzen')]),
        'info': ('ℹ️ Info', [('/version', 'Version'), ('/help', 'Hilfe')]),
    }

    def mock_help_fields(bereich, is_admin=False):
        return fake_fields.get(bereich, ('', []))

    with patch('commands.chat_tools._tool_get_help.__module__', 'commands.chat_tools'):
        pass

    # Ohne Bereich → Uebersicht
    with patch('bot._help_fields', mock_help_fields):
        result_str = run_async(_tool_get_help({}, {}))
        result = json.loads(result_str)
    check('get_help ohne Bereich hat puzzle', 'puzzle' in result)
    check('get_help ohne Bereich hat info', 'info' in result)
    check('get_help puzzle hat titel', 'titel' in result['puzzle'])
    check('get_help puzzle hat commands', 'commands' in result['puzzle'])

    # Mit Bereich
    with patch('bot._help_fields', mock_help_fields):
        result_str = run_async(_tool_get_help({'bereich': 'puzzle'}, {}))
        result = json.loads(result_str)
    check('get_help puzzle hat bereich', 'bereich' in result)
    check('get_help puzzle hat commands', 'commands' in result)
    check('get_help puzzle 2 commands', len(result['commands']) == 2)

    # Unbekannter Bereich
    with patch('bot._help_fields', mock_help_fields):
        result_str = run_async(_tool_get_help({'bereich': 'xyz'}, {}))
        result = json.loads(result_str)
    check('get_help unbekannt → error', 'error' in result)
    check('get_help unbekannt → verfuegbar', 'verfuegbar' in result)


def test_tool_get_release_notes():
    """Test fuer get_release_notes Tool-Handler."""
    print('[tool_get_release_notes]')
    from commands.chat_tools import _tool_get_release_notes

    fake_entries = [
        {'version': '2.35.0', 'date': '2026-05-21', 'body': '### Added\n- Feature A'},
        {'version': '2.34.4', 'date': '2026-05-21', 'body': '### Fixed\n- Fix B'},
        {'version': '2.34.3', 'date': '2026-05-21', 'body': '### Fixed\n- Fix C'},
        {'version': '2.34.2', 'date': '2026-05-21', 'body': '### Fixed\n- Fix D'},
    ]

    # Standard: 3 Eintraege
    with patch('commands.release_notes._parse_changelog', return_value=fake_entries):
        result_str = run_async(_tool_get_release_notes({}, {}))
        result = json.loads(result_str)
    check('release_notes standard → 3 Eintraege', len(result) == 3)
    check('release_notes erster ist neueste', result[0]['version'] == '2.35.0')

    # Bestimmte Anzahl
    with patch('commands.release_notes._parse_changelog', return_value=fake_entries):
        result_str = run_async(_tool_get_release_notes({'anzahl': 2}, {}))
        result = json.loads(result_str)
    check('release_notes anzahl=2 → 2', len(result) == 2)

    # Bestimmte Version
    with patch('commands.release_notes._parse_changelog', return_value=fake_entries):
        result_str = run_async(_tool_get_release_notes({'version': '2.34.3'}, {}))
        result = json.loads(result_str)
    check('release_notes version=2.34.3 → 1', len(result) == 1)
    check('release_notes version korrekt', result[0]['version'] == '2.34.3')

    # Unbekannte Version
    with patch('commands.release_notes._parse_changelog', return_value=fake_entries):
        result_str = run_async(_tool_get_release_notes({'version': '9.9.9'}, {}))
        result = json.loads(result_str)
    check('release_notes unbekannt → error', 'error' in result)

    # Leeres Changelog
    with patch('commands.release_notes._parse_changelog', return_value=[]):
        result_str = run_async(_tool_get_release_notes({}, {}))
        result = json.loads(result_str)
    check('release_notes leer → error', 'error' in result)
