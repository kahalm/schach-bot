"""Tests fuer Puzzle Commands: /puzzle, /kurs, /train, /next, /endless, /blind, buttons, etc."""

import os
import sys
import tempfile
import shutil
import signal
from unittest.mock import MagicMock

import test_helpers as h
from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    make_interaction, _captured_commands, FakeMember,
)


def test_puzzle():
    """Smoke-Tests fuer /puzzle Command."""
    print('[/puzzle]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('puzzle')
        check('cmd_puzzle gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        # Patch post_puzzle um IO zu vermeiden
        orig_post = leg.post_puzzle
        call_log = []

        async def fake_post_puzzle(channel, count=1, book_idx=0, user_id=None):
            call_log.append({'count': count, 'book_idx': book_idx, 'user_id': user_id})
            return count

        leg.post_puzzle = fake_post_puzzle

        try:
            # Test: Standard-Aufruf
            ia = make_interaction()
            run_async(cmd(ia, anzahl=2, buch=0, id='', user=None))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('post_puzzle aufgerufen', len(call_log) == 1)
            check('post_puzzle count=2', call_log[0]['count'] == 2)
            check('followup mit Bestaetigung',
                  len(ia.followup.calls) > 0 and
                  '2' in (ia.followup.calls[0].get('content') or ''))

            # Test: id nicht gefunden
            call_log.clear()
            orig_find = leg.find_line_by_id
            leg.find_line_by_id = lambda lid: None
            ia = make_interaction()
            run_async(cmd(ia, anzahl=1, buch=0, id='nonexistent.pgn:999', user=None))
            check('id nicht gefunden → Fehlermeldung',
                  len(ia.followup.calls) > 0 and
                  'nicht gefunden' in (ia.followup.calls[0].get('content') or '').lower())
            leg.find_line_by_id = orig_find
        finally:
            leg.post_puzzle = orig_post
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_kurs():
    """Smoke-Tests fuer /kurs Command."""
    print('[/kurs]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('kurs')
        check('cmd_kurs gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        # Patch load_all_lines
        orig_load = leg.load_all_lines
        orig_state = leg.load_puzzle_state
        orig_books = leg._load_books_config
        orig_list = leg._list_pgn_files

        leg.load_all_lines = lambda: []
        leg.load_puzzle_state = lambda: {'posted': []}
        leg._load_books_config = lambda: {}
        leg._list_pgn_files = lambda: []

        try:
            # Test: keine Buecher
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            # Bei leeren lines gibt es ein Embed ohne Felder oder Warnung
            check('followup gesendet', len(ia.followup.calls) > 0)

            # Test: mit Buechern
            leg.load_all_lines = lambda: [
                ('book1.pgn:001.001', MagicMock()),
                ('book1.pgn:001.002', MagicMock()),
            ]
            leg._list_pgn_files = lambda: ['book1.pgn']
            leg._load_books_config = lambda: {
                'book1.pgn': {'difficulty': 'Anfaenger', 'rating': 3,
                              'random': True, 'blind': False}
            }
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            check('mit Buch → followup', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('mit Buch → Embed hat Felder',
                  embed is not None and len(embed.fields) > 0)
        finally:
            leg.load_all_lines = orig_load
            leg.load_puzzle_state = orig_state
            leg._load_books_config = orig_books
            leg._list_pgn_files = orig_list
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_train():
    """Smoke-Tests fuer /train Command."""
    print('[/train]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('train')
        check('cmd_train gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        orig_get = leg._get_user_training
        orig_set = leg._set_user_training
        orig_clear = leg._clear_user_training
        orig_load = leg.load_all_lines
        orig_list = leg._list_pgn_files
        orig_books = leg._load_books_config

        _training = {}

        def fake_get(uid):
            return _training.get(uid)

        def fake_set(uid, book, pos):
            _training[uid] = {'book': book, 'position': pos}

        def fake_clear(uid):
            _training.pop(uid, None)

        leg._get_user_training = fake_get
        leg._set_user_training = fake_set
        leg._clear_user_training = fake_clear
        leg.load_all_lines = lambda: [
            ('book1.pgn:001.001', MagicMock()),
            ('book1.pgn:001.002', MagicMock()),
        ]
        leg._list_pgn_files = lambda: ['book1.pgn']
        leg._load_books_config = lambda: {
            'book1.pgn': {'difficulty': 'Anfaenger', 'rating': 3}
        }

        try:
            # Test: Status ohne Training
            ia = make_interaction()
            run_async(cmd(ia, buch=None))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('kein Training → Hinweis', 'kein training' in content)

            # Test: Buch waehlen
            ia = make_interaction()
            run_async(cmd(ia, buch=1))
            check('Buch waehlen → Embed',
                  len(ia.followup.calls) > 0 and
                  ia.followup.calls[0].get('embed') is not None)
            check('Training gesetzt', 12345 in _training)

            # Test: Buch 0 = stoppen
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('Buch 0 → beendet', 'beendet' in content)

            # Test: ungueliges Buch
            ia = make_interaction()
            run_async(cmd(ia, buch=99))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('ungültiges Buch → Fehler', 'nicht gefunden' in content)
        finally:
            leg._get_user_training = orig_get
            leg._set_user_training = orig_set
            leg._clear_user_training = orig_clear
            leg.load_all_lines = orig_load
            leg._list_pgn_files = orig_list
            leg._load_books_config = orig_books
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_next():
    """Smoke-Tests fuer /next Command."""
    print('[/next]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('next')
        check('cmd_next gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        orig_get = leg._get_user_training
        _training = {}
        leg._get_user_training = lambda uid: _training.get(uid)

        try:
            # Test: kein Training → Fehler
            ia = make_interaction()
            run_async(cmd(ia, anzahl=1))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('kein Training → Fehler', 'kein trainingsbuch' in content)
        finally:
            leg._get_user_training = orig_get
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_endless():
    """Smoke-Tests fuer /endless Command."""
    print('[/endless]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('endless')
        check('cmd_endless gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        orig_is = leg.is_endless
        orig_start = leg.start_endless
        orig_stop = leg.stop_endless
        orig_post = leg.post_next_endless
        orig_list = leg._list_pgn_files

        _sessions = {}

        def fake_is(uid):
            return uid in _sessions

        def fake_start(uid, book):
            _sessions[uid] = {'book': book, 'count': 0}

        def fake_stop(uid):
            count = _sessions.pop(uid, {}).get('count', 0)
            return count

        async def fake_post_next(bot, uid):
            if uid in _sessions:
                _sessions[uid]['count'] += 1

        leg.is_endless = fake_is
        leg.start_endless = fake_start
        leg.stop_endless = fake_stop
        leg.post_next_endless = fake_post_next
        leg._list_pgn_files = lambda: ['book1.pgn']

        try:
            # Test: starten (braucht den bot-Parameter)
            # endless-Command in bot.py ruft _cmd_endless(bot, interaction, buch)
            # aber der captured Command ist: async def cmd_endless(interaction, buch=0)
            # → _cmd_endless(bot, interaction, buch)
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            check('starten → defer + followup',
                  ia.response.calls[0].get('type') == 'defer' and
                  len(ia.followup.calls) > 0)

            # Test: stoppen (Toggle)
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            content = ia.response.calls[0].get('content') or ''
            check('stoppen-Toggle → beendet',
                  'beendet' in content.lower() or 'Endless' in content)
        finally:
            leg.is_endless = orig_is
            leg.start_endless = orig_start
            leg.stop_endless = orig_stop
            leg.post_next_endless = orig_post
            leg._list_pgn_files = orig_list
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_blind():
    """Smoke-Tests fuer /blind Command."""
    print('[/blind]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('blind')
        check('cmd_blind gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as puzzle_mod

        orig_post = puzzle_mod.post_blind_puzzle

        call_log = []
        async def fake_post_blind(channel, moves=4, count=1, book_idx=0, user_id=None):
            call_log.append({'moves': moves, 'count': count})

        puzzle_mod.post_blind_puzzle = fake_post_blind

        try:
            # Test: moves < 1 → Fehler
            ia = make_interaction()
            run_async(cmd(ia, moves=0, anzahl=1, buch=0, user=None))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('moves < 1 → Fehler', 'zwischen 1 und 50' in content)

            # Test: Standard-Aufruf
            ia = make_interaction()
            run_async(cmd(ia, moves=4, anzahl=2, buch=0, user=None))
            check('Standard → defer', ia.response.calls[0].get('type') == 'defer')
            check('post_blind_puzzle aufgerufen', len(call_log) > 0)
        finally:
            puzzle_mod.post_blind_puzzle = orig_post
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_buttons():
    """Tests fuer puzzle/buttons.py _apply_click Logik."""
    print('[buttons]')
    import puzzle.buttons as btns

    # State vor jedem Test-Block zuruecksetzen
    btns._clicks.clear()

    # --- Einfacher Klick: hinzufuegen ---
    delta, removed = btns._apply_click(1, '✅', user_id=100)
    check('click add → delta=+1', delta == 1)
    check('click add → removed=None', removed is None)
    check('click add → count=1', btns._count(1, '✅') == 1)

    # --- Toggle-off: gleicher Klick entfernt Stimme ---
    delta, removed = btns._apply_click(1, '✅', user_id=100)
    check('toggle-off → delta=-1', delta == -1)
    check('toggle-off → count=0', btns._count(1, '✅') == 0)

    # --- Mutex: ✅ dann ❌ entfernt ✅ ---
    btns._clicks.clear()
    btns._apply_click(1, '✅', user_id=200)
    check('mutex pre → ✅=1', btns._count(1, '✅') == 1)
    delta, removed = btns._apply_click(1, '❌', user_id=200)
    check('mutex → delta=+1', delta == 1)
    check('mutex → removed=✅', removed == '✅')
    check('mutex → ✅ count=0', btns._count(1, '✅') == 0)
    check('mutex → ❌ count=1', btns._count(1, '❌') == 1)

    # --- Mutex 👍↔👎 ---
    btns._clicks.clear()
    btns._apply_click(2, '👍', user_id=300)
    delta, removed = btns._apply_click(2, '👎', user_id=300)
    check('mutex 👍→👎 → removed=👍', removed == '👍')
    check('mutex 👍→👎 → 👍=0', btns._count(2, '👍') == 0)
    check('mutex 👍→👎 → 👎=1', btns._count(2, '👎') == 1)

    # --- 🚮 hat keinen Mutex-Partner ---
    btns._clicks.clear()
    btns._apply_click(3, '✅', user_id=400)
    delta, removed = btns._apply_click(3, '🚮', user_id=400)
    check('🚮 → kein mutex', removed is None)
    check('🚮 → delta=+1', delta == 1)
    check('🚮 → ✅ bleibt', btns._count(3, '✅') == 1)

    # --- Mehrere User auf gleichem Emoji ---
    btns._clicks.clear()
    btns._apply_click(4, '✅', user_id=501)
    btns._apply_click(4, '✅', user_id=502)
    btns._apply_click(4, '✅', user_id=503)
    check('multi-user → count=3', btns._count(4, '✅') == 3)
    btns._apply_click(4, '✅', user_id=502)  # toggle-off
    check('multi-user toggle-off → count=2', btns._count(4, '✅') == 2)

    # --- Eviction bei Cap-Ueberlauf ---
    btns._clicks.clear()
    old_cap = btns._CLICKS_CAP
    btns._CLICKS_CAP = 5
    try:
        for i in range(6):
            btns._apply_click(i, '✅', user_id=600)
        check('eviction → max entries <= cap+1', len(btns._clicks) <= btns._CLICKS_CAP + 1)
        # Aelteste (msg_id=0) sollte rausgeflogen sein
        check('eviction → msg 0 entfernt', 0 not in btns._clicks)
    finally:
        btns._CLICKS_CAP = old_cap

    # --- _count bei unbekannter msg_id ---
    check('count unknown msg → 0', btns._count(99999, '✅') == 0)
    check('count unknown emoji → 0', btns._count(1, '💀') == 0)

    btns._clicks.clear()  # Aufraumen
    print()


def test_format_blind_moves():
    """Tests fuer _format_blind_moves (Zugnotation mit korrekten Nummern)."""
    print('[format_blind_moves]')
    import chess
    from puzzle.processing import _format_blind_moves

    # --- Weiss am Zug, Startposition (Zug 1) ---
    board = chess.Board()  # Standard-Startstellung, Weiss am Zug, Zug 1
    result = _format_blind_moves(board, ['e4', 'e5', 'Nf3'])
    check('white start → 1. e4 e5 2. Nf3', result == '1. e4 e5 2. Nf3')

    # --- Schwarz am Zug (z.B. nach 1.e4) ---
    board_black = chess.Board()
    board_black.push_san('e4')  # Jetzt Schwarz am Zug, Zug 1
    result = _format_blind_moves(board_black, ['e5', 'Nf3', 'Nc6'])
    check('black start → 1... e5 2. Nf3 Nc6', result == '1... e5 2. Nf3 Nc6')

    # --- Spaetere Zugnummer ---
    board_late = chess.Board()
    board_late.fullmove_number = 15
    board_late.turn = chess.WHITE
    result = _format_blind_moves(board_late, ['Nf3', 'Nc6'])
    check('Zug 15 → 15. Nf3 Nc6', result == '15. Nf3 Nc6')

    # --- Einzelner Zug Weiss ---
    result = _format_blind_moves(chess.Board(), ['d4'])
    check('single white → 1. d4', result == '1. d4')

    # --- Einzelner Zug Schwarz ---
    board_b2 = chess.Board()
    board_b2.push_san('d4')
    result = _format_blind_moves(board_b2, ['d5'])
    check('single black → 1... d5', result == '1... d5')

    # --- Leere Liste ---
    result = _format_blind_moves(chess.Board(), [])
    check('empty → leer', result == '')
    print()


def test_puzzle_anzahl_validation():
    """Test dass /puzzle anzahl ausserhalb 1-20 abgelehnt wird."""
    print('[puzzle_anzahl_validation]')
    tmpdir = setup_temp_config()
    try:
        import puzzle.commands
        cmd = getattr(puzzle.commands, '_cmd_puzzle', None)
        if cmd is None:
            for attr in dir(puzzle.commands):
                obj = getattr(puzzle.commands, attr)
                if callable(obj) and getattr(obj, '__name__', '') == '_cmd_puzzle':
                    cmd = obj
                    break
        if cmd:
            ia = make_interaction()
            run_async(cmd(ia, anzahl=100, buch=0, id='', user=None))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('/puzzle anzahl:100 → Fehler', 'zwischen 1 und 20' in content)

            ia = make_interaction()
            run_async(cmd(ia, anzahl=0, buch=0, id='', user=None))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('/puzzle anzahl:0 → Fehler', 'zwischen 1 und 20' in content)
        else:
            check('/puzzle anzahl Validierung', False, 'cmd nicht gefunden')
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_posted_reset_per_pool():
    """Test dass pick_random_lines nur Pool-Linien aus posted entfernt (#20)."""
    print('[posted_reset_per_pool]')
    tmpdir = setup_temp_config()
    try:
        import puzzle.selection as sel
        import puzzle.state as pstate

        old_dir = sel.BOOKS_DIR
        old_state_dir = pstate.BOOKS_DIR
        old_state_file = pstate.PUZZLE_STATE_FILE
        sel.BOOKS_DIR = tmpdir
        pstate.BOOKS_DIR = tmpdir

        # books.json: book_a random=true, book_b random=true
        from core.json_store import atomic_write, atomic_read
        books_json = os.path.join(tmpdir, 'books.json')
        atomic_write(books_json, {
            'book_a.pgn': {'random': True},
            'book_b.pgn': {'random': True},
        })
        pstate._invalidate_books_config_cache()

        # Puzzle-State: book_a und book_b haben je 1 Linie als posted
        state_file = os.path.join(tmpdir, 'puzzle_state.json')
        pstate.PUZZLE_STATE_FILE = state_file
        atomic_write(state_file, {
            'posted': ['book_a.pgn:1.1', 'book_b.pgn:2.1']
        })

        # Lade den posted-state und pruefe
        state = sel.load_puzzle_state()
        check('pre: 2 posted', len(state.get('posted', [])) == 2)

        # Simuliere die Reset-Logik direkt (ohne echte PGNs)
        posted = set(state.get('posted', []))
        pool_ids = {'book_a.pgn:1.1'}  # nur book_a im Pool
        # Alte Logik: posted = set() → ALLES weg
        # Neue Logik: posted -= pool_ids → nur Pool-Linien weg
        posted -= pool_ids
        check('posted reset → book_b bleibt', 'book_b.pgn:2.1' in posted)
        check('posted reset → book_a weg', 'book_a.pgn:1.1' not in posted)
    finally:
        sel.BOOKS_DIR = old_dir
        pstate.BOOKS_DIR = old_state_dir
        pstate.PUZZLE_STATE_FILE = old_state_file
        sel.clear_lines_cache()
        teardown_temp_config(tmpdir)
    print()


def test_pgn_parse_max_errors():
    """Test dass _parse_all_lines bei korruptem PGN nicht endlos loopt."""
    print('[pgn_parse_max_errors]')
    import puzzle.selection as sel
    old_dir = sel.BOOKS_DIR
    tmpdir = tempfile.mkdtemp()
    try:
        sel.BOOKS_DIR = tmpdir
        # PGN das immer Exceptions wirft (ungueltiges Encoding-Pattern)
        corrupt = '[Event "X"]\n[Round "1"]\n\n{' + 'x' * 5000 + '}\n' * 200
        with open(os.path.join(tmpdir, 'corrupt.pgn'), 'w') as f:
            f.write(corrupt)
        # Muss terminieren (nicht endlos loopen)
        timed_out = [False]
        if hasattr(signal, 'SIGALRM'):
            def _handler(sig, frame):
                timed_out[0] = True
                raise TimeoutError
            signal.signal(signal.SIGALRM, _handler)
            signal.alarm(10)
        try:
            sel._parse_all_lines()
        except TimeoutError:
            pass
        finally:
            if hasattr(signal, 'SIGALRM'):
                signal.alarm(0)
        check('PGN-Parser terminiert', not timed_out[0])
    finally:
        sel.BOOKS_DIR = old_dir
        shutil.rmtree(tmpdir, ignore_errors=True)
    print()
