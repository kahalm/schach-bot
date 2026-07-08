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
    """Whitelist-Check (aus chat.json) + Rate-Limit fuer Nicht-Whitelisted."""
    print('[chat_routing]')
    tmpdir = setup_temp_config()
    try:
        atomic_write(chat_mod.CHAT_FILE, {'whitelist': [42]})
        check('whitelisted User → True', chat_mod._is_whitelisted(42))
        check('nicht-whitelisted User → False', not chat_mod._is_whitelisted(99))

        # Rate-Limit nur fuer Nicht-Whitelisted: bis _RATE_LIMIT_MAX erlaubt,
        # danach blockiert; nach Ablauf des Fensters wieder erlaubt.
        chat_mod._rate_hits.clear()
        uid, t = 99, 1000.0
        allowed = sum(1 for _ in range(chat_mod._RATE_LIMIT_MAX)
                      if chat_mod._check_rate_limit(uid, now=t))
        check('erste N Nachrichten erlaubt', allowed == chat_mod._RATE_LIMIT_MAX)
        check('N+1-te Nachricht blockiert',
              not chat_mod._check_rate_limit(uid, now=t))
        check('nach Ablauf des Fensters wieder erlaubt',
              chat_mod._check_rate_limit(uid, now=t + chat_mod._RATE_LIMIT_WINDOW + 1))

    finally:
        chat_mod._rate_hits.clear()
        teardown_temp_config(tmpdir)


def test_rate_hits_bounded():
    """_rate_hits waechst nicht unbegrenzt — abgelaufene/leere Eintraege werden geprunt."""
    print('[rate_hits bounded]')
    orig_max = chat_mod._RATE_LIMIT_MAXSIZE
    try:
        chat_mod._rate_hits.clear()
        chat_mod._RATE_LIMIT_MAXSIZE = 10
        # Viele User mit altem Timestamp eintragen (alle abgelaufen).
        for uid in range(50):
            chat_mod._check_rate_limit(uid, now=1000.0)
        # Ein neuer Aufruf weit spaeter → Prune raeumt die abgelaufenen weg.
        chat_mod._check_rate_limit(99999, now=1000.0 + chat_mod._RATE_LIMIT_WINDOW + 5)
        check('Rate-Limit-Dict bleibt beschraenkt',
              len(chat_mod._rate_hits) <= chat_mod._RATE_LIMIT_MAXSIZE)
    finally:
        chat_mod._RATE_LIMIT_MAXSIZE = orig_max
        chat_mod._rate_hits.clear()


def test_daily_token_cap():
    """Tages-Token-Cap: zaehlt verbrauchte Tokens pro UTC-Tag, blockt ueber Limit, rollt taeglich."""
    print('[daily_token_cap]')
    tmpdir = setup_temp_config()
    orig_cap = chat_mod._DAILY_TOKEN_CAP
    try:
        atomic_write(chat_mod.CHAT_FILE, {})
        chat_mod._DAILY_TOKEN_CAP = 1000

        check('frisch → unter Cap', chat_mod._daily_tokens_left(7) is True)
        chat_mod._record_token_usage(7, 600)
        check('nach 600 → noch unter Cap', chat_mod._daily_tokens_left(7) is True)
        chat_mod._record_token_usage(7, 600)
        check('nach 1200 → ueber Cap', chat_mod._daily_tokens_left(7) is False)
        # Anderer User unberuehrt
        check('anderer User → unter Cap', chat_mod._daily_tokens_left(8) is True)

        # Tageswechsel simulieren: gespeicherten date-Eintrag auf gestern setzen.
        data = atomic_read(chat_mod.CHAT_FILE, dict)
        data['usage']['7']['date'] = '2000-01-01'
        atomic_write(chat_mod.CHAT_FILE, data)
        check('nach Tageswechsel → Kontingent frisch', chat_mod._daily_tokens_left(7) is True)

        # Cap=0 → deaktiviert
        chat_mod._DAILY_TOKEN_CAP = 0
        check('Cap=0 → immer erlaubt', chat_mod._daily_tokens_left(7) is True)
    finally:
        chat_mod._DAILY_TOKEN_CAP = orig_cap
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


def test_chat_history_sanitize():
    """Test dass verwaiste tool_use/tool_result Blocks bereinigt werden."""
    print('[chat_history_sanitize]')
    tmpdir = setup_temp_config()
    try:
        # History mit tool_result am Anfang (verwaist nach Prune)
        orphan_history = {
            'history': {
                '1': [
                    {'role': 'user', 'content': [
                        {'type': 'tool_result', 'tool_use_id': 'x', 'content': '{}'}
                    ]},
                    {'role': 'assistant', 'content': 'Antwort'},
                    {'role': 'user', 'content': 'Hallo'},
                    {'role': 'assistant', 'content': 'Hi'},
                ]
            }
        }
        atomic_write(chat_mod.CHAT_FILE, orphan_history)
        result = chat_mod._append_and_get_history(1, 'Test')
        check('sanitize: kein tool_result am Anfang',
              not (isinstance(result[0].get('content'), list)
                   and any(b.get('type') == 'tool_result'
                           for b in result[0]['content']
                           if isinstance(b, dict))))
        check('sanitize: beginnt mit user-Text', result[0]['role'] == 'user')

        # History mit tool_use am Ende (verwaist, kein tool_result folgt)
        orphan_end = {
            'history': {
                '2': [
                    {'role': 'user', 'content': 'Frage'},
                    {'role': 'assistant', 'content': [
                        {'type': 'text', 'text': 'Moment...'},
                        {'type': 'tool_use', 'id': 'y', 'name': 'x', 'input': {}},
                    ]},
                ]
            }
        }
        atomic_write(chat_mod.CHAT_FILE, orphan_end)
        result = chat_mod._append_and_get_history(2, 'Weiter')
        # Das assistant tool_use ohne folgendes tool_result sollte entfernt sein
        has_orphan_tool_use = any(
            msg['role'] == 'assistant' and isinstance(msg.get('content'), list)
            and any(b.get('type') == 'tool_use' for b in msg['content'] if isinstance(b, dict))
            for msg in result[:-1]  # letzte ist die neue user-Nachricht
        )
        check('sanitize: kein verwaistes tool_use am Ende', not has_orphan_tool_use)

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

    tmpdir = setup_temp_config()
    try:
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
        check('System-Prompt enthaelt KEINE Loesung (Prompt-Injection-Schutz)',
              '1. e4 e5' not in prompt and 'Loesung:' not in prompt)
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

        # Test: Disk-Persistenz (ueberlebt In-Memory-Clear)
        save_puzzle_context(77, info_a)
        _last_puzzle_context.clear()  # simuliert Bot-Neustart
        ps._last_channel_puzzle = None
        ctx_from_disk = get_puzzle_context(77)
        check('Disk-Persistenz: Kontext nach clear', ctx_from_disk == info_a)

        # Aufraemen
        _last_puzzle_context.clear()
        ps._last_channel_puzzle = None
    finally:
        teardown_temp_config(tmpdir)


def test_chat_retry_books_tokens():
    """Nach v2.78.x: der BadRequest-Retry ruft _call_claude und bucht dadurch AUCH
    den Token-Verbrauch (vorher ging der Retry-Verbrauch verloren)."""
    print('[chat retry books tokens]')
    tmpdir = setup_temp_config()
    orig_client = chat_mod._client
    orig_cap = chat_mod._DAILY_TOKEN_CAP
    try:
        atomic_write(chat_mod.CHAT_FILE, {})
        chat_mod._DAILY_TOKEN_CAP = 100000

        class _Blk:
            type = 'text'
            text = 'Antwort'

        class _Usage:
            input_tokens = 500
            output_tokens = 300

        class _Resp:
            content = [_Blk()]
            usage = _Usage()
            stop_reason = 'end_turn'

        class _BadRequestError(Exception):
            pass

        calls = {'n': 0}

        class _Msgs:
            async def create(self, **kw):
                calls['n'] += 1
                if calls['n'] == 1:
                    raise _BadRequestError('bad history')
                return _Resp()

        class _FakeClient:
            messages = _Msgs()

        chat_mod._client = _FakeClient()
        out = run_async(chat_mod._chat_response(7, 'hallo', channel=None, persist=True))
        check('Retry lieferte die Antwort', out == 'Antwort')
        check('1× BadRequest + 1× erfolgreicher Retry', calls['n'] == 2)
        data = atomic_read(chat_mod.CHAT_FILE, default=dict)
        rec = (data.get('usage') or {}).get('7') or {}
        check('Retry hat Token gebucht (500+300=800)', rec.get('tokens') == 800)
    finally:
        chat_mod._client = orig_client
        chat_mod._DAILY_TOKEN_CAP = orig_cap
        teardown_temp_config(tmpdir)
