"""Tests fuer KI-Chat Commands: /chat_whitelist, /chat_clear, DM-Routing."""

import test_helpers as h
from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    make_interaction, _captured_commands, FakeUser,
    atomic_write, atomic_read,
)

import commands.chat as chat_mod


def test_chat_whitelist():
    """Tests fuer /chat_whitelist Command."""
    print('[/chat_whitelist]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('chat_whitelist')
        check('cmd_chat_whitelist gefunden', cmd is not None)
        if not cmd:
            return

        # Test: list auf leerer Whitelist
        ia = make_interaction(admin=True)
        run_async(cmd(ia, user=None, aktion='list'))
        check('leere Whitelist → Hinweis',
              'leer' in (ia.response.calls[0].get('content') or '').lower())

        # Test: User hinzufuegen
        target = FakeUser(uid=99999, name='ChessKid')
        ia = make_interaction(admin=True)
        run_async(cmd(ia, user=target, aktion='add'))
        check('add → Bestaetigung',
              'hinzugefuegt' in (ia.response.calls[0].get('content') or '').lower())

        # Test: Doppelt hinzufuegen
        ia = make_interaction(admin=True)
        run_async(cmd(ia, user=target, aktion='add'))
        check('add doppelt → already',
              'bereits' in (ia.response.calls[0].get('content') or '').lower())

        # Test: list mit Eintrag
        ia = make_interaction(admin=True)
        run_async(cmd(ia, user=None, aktion='list'))
        check('list → zeigt User',
              '99999' in (ia.response.calls[0].get('content') or ''))

        # Test: User entfernen
        ia = make_interaction(admin=True)
        run_async(cmd(ia, user=target, aktion='remove'))
        check('remove → Bestaetigung',
              'entfernt' in (ia.response.calls[0].get('content') or '').lower())

        # Test: Nicht-vorhandenen User entfernen
        ia = make_interaction(admin=True)
        run_async(cmd(ia, user=target, aktion='remove'))
        check('remove nicht vorhanden → Hinweis',
              'nicht auf' in (ia.response.calls[0].get('content') or '').lower())

        # Test: Non-Admin blocked
        ia = make_interaction(admin=False)
        run_async(cmd(ia, user=target, aktion='add'))
        check('non-admin → abgelehnt',
              'admin' in (ia.response.calls[0].get('content') or '').lower())

        # Test: ungueltige Aktion
        ia = make_interaction(admin=True)
        run_async(cmd(ia, user=target, aktion='invalid'))
        check('ungueltige aktion → Fehler',
              'ungueltig' in (ia.response.calls[0].get('content') or '').lower())

    finally:
        teardown_temp_config(tmpdir)


def test_chat_clear():
    """Tests fuer /chat_clear Command."""
    print('[/chat_clear]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('chat_clear')
        check('cmd_chat_clear gefunden', cmd is not None)
        if not cmd:
            return

        # Test: clear ohne Historie
        ia = make_interaction()
        run_async(cmd(ia))
        check('clear ohne Historie → Hinweis',
              'keine' in (ia.response.calls[0].get('content') or '').lower())

        # Test: Historie anlegen und dann clearen
        uid = ia.user.id
        atomic_write(chat_mod.CHAT_FILE, {
            'whitelist': [uid],
            'history': {
                str(uid): [
                    {'role': 'user', 'content': 'Hallo'},
                    {'role': 'assistant', 'content': 'Hi!'},
                ]
            }
        })

        ia = make_interaction()
        run_async(cmd(ia))
        check('clear mit Historie → geloescht',
              'geloescht' in (ia.response.calls[0].get('content') or '').lower())

        # Verifizieren dass History weg ist
        data = atomic_read(chat_mod.CHAT_FILE, dict)
        check('Historie tatsaechlich geloescht',
              str(uid) not in data.get('history', {}))

    finally:
        teardown_temp_config(tmpdir)


def test_chat_routing():
    """Tests fuer DM-Routing: nur whitelisted User bekommen Antwort."""
    print('[chat_routing]')
    tmpdir = setup_temp_config()
    try:
        # Aktuell fuer alle freigeschaltet (vorerst)
        check('alle User → True', chat_mod._is_whitelisted(42))
        check('alle User → True (auch ohne Whitelist)', chat_mod._is_whitelisted(99))

    finally:
        teardown_temp_config(tmpdir)


def test_chat_history_prune():
    """Tests dass History auf _MAX_HISTORY begrenzt wird."""
    print('[chat_history_prune]')
    tmpdir = setup_temp_config()
    try:
        # Viele Nachrichten einfuegen
        atomic_write(chat_mod.CHAT_FILE, {'whitelist': [1], 'history': {}})

        for i in range(25):
            chat_mod._append_and_get_history(1, f'Nachricht {i}')

        data = atomic_read(chat_mod.CHAT_FILE, dict)
        msgs = data.get('history', {}).get('1', [])
        check(f'History begrenzt auf {chat_mod._MAX_HISTORY}',
              len(msgs) <= chat_mod._MAX_HISTORY)

        # Letzte Nachricht sollte die neueste sein
        check('Letzte Nachricht ist die neueste',
              msgs[-1]['content'] == 'Nachricht 24')

        # Nach Prune mit abwechselnden user/assistant: erste Nachricht muss user sein
        atomic_write(chat_mod.CHAT_FILE, {'whitelist': [2], 'history': {}})
        for i in range(10):
            chat_mod._append_and_get_history(2, f'User {i}')
            chat_mod._save_assistant_response(2, f'Bot {i}')
        # 20 msgs voll, naechste user-Nachricht triggert Prune
        result = chat_mod._append_and_get_history(2, 'Overflow')
        check('nach Prune beginnt History mit user',
              result[0]['role'] == 'user')
        check('nach Prune letzte Nachricht ist Overflow',
              result[-1]['content'] == 'Overflow')

    finally:
        teardown_temp_config(tmpdir)


def test_chat_no_key():
    """Tests dass ohne API Key _client None ist und Feature deaktiviert."""
    print('[chat_no_key]')
    # _client ist None wenn kein Key gesetzt (Standard im Test)
    check('_client ist None im Test', chat_mod._client is None)


def test_puzzle_context():
    """Tests fuer Puzzle-Kontext im KI-Chat."""
    print('[puzzle_context]')
    from puzzle.state import (
        save_puzzle_context, get_puzzle_context,
        _last_puzzle_context, _last_channel_puzzle,
    )
    import puzzle.state as ps

    # Sauberer Zustand
    _last_puzzle_context.clear()
    ps._last_channel_puzzle = None

    info_a = {
        'book': 'Taktik-Buch',
        'chapter': 'Kapitel 1',
        'line': 'Linie 5',
        'fen': 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
        'turn': 'Weiss',
        'solution': '1. e4 e5 2. Sf3',
        'difficulty': 'Mittel',
        'line_id': 'taktik.pgn:1.5',
    }

    # Test: ohne Daten → None
    check('kein Kontext → None', get_puzzle_context(99) is None)

    # Test: per-User speichern und abrufen
    save_puzzle_context(42, info_a)
    check('per-User Kontext abrufbar', get_puzzle_context(42) == info_a)

    # Test: Channel-Fallback (user_id=None)
    info_b = dict(info_a, book='Endspiel-Buch')
    save_puzzle_context(None, info_b)
    check('Channel-Fallback fuer unbekannten User',
          get_puzzle_context(999) == info_b)

    # Test: per-User hat Vorrang vor Channel-Fallback
    check('per-User Vorrang vor Channel',
          get_puzzle_context(42) == info_a)

    # Test: _build_system_prompt mit Kontext
    prompt = chat_mod._build_system_prompt(42)
    check('System-Prompt enthaelt Buch', 'Taktik-Buch' in prompt)
    check('System-Prompt enthaelt FEN', 'rnbqkbnr' in prompt)
    check('System-Prompt enthaelt Loesung', '1. e4 e5' in prompt)
    check('System-Prompt enthaelt Hinweis-Regel', 'Hinweisen' in prompt)

    # Test: _build_system_prompt ohne Kontext
    _last_puzzle_context.clear()
    ps._last_channel_puzzle = None
    prompt_plain = chat_mod._build_system_prompt(123)
    check('ohne Kontext kein FEN', 'FEN' not in prompt_plain)

    # Test: Kontext ohne Loesung (Blind-Modus)
    info_blind = dict(info_a)
    del info_blind['solution']
    save_puzzle_context(50, info_blind)
    prompt_blind = chat_mod._build_system_prompt(50)
    check('Blind-Kontext: kein Loesungsblock', 'Loesung:' not in prompt_blind)
    check('Blind-Kontext: Buch vorhanden', 'Taktik-Buch' in prompt_blind)

    # Aufraemen
    _last_puzzle_context.clear()
    ps._last_channel_puzzle = None
