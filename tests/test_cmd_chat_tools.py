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
    check('6 Tools definiert', len(TOOLS) == 6)
    names = set()
    for tool in TOOLS:
        check(f'Tool {tool["name"]} hat name', 'name' in tool)
        check(f'Tool {tool["name"]} hat description', 'description' in tool)
        check(f'Tool {tool["name"]} hat input_schema', 'input_schema' in tool)
        check(f'Tool {tool["name"]} schema hat type',
              tool['input_schema'].get('type') == 'object')
        names.add(tool['name'])
    expected = {'list_books', 'suggest_book', 'get_training_status',
                'set_training', 'send_puzzle', 'send_next'}
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
