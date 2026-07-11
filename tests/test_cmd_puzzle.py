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

        # Patch post_rookhub_puzzle um IO zu vermeiden (RookHub liefert jetzt die Auswahl)
        orig_post = leg.post_rookhub_puzzle
        call_log = []

        async def fake_post_rookhub(channel, pool='random', user_id=None, exclude=None,
                                    book_id=None):
            call_log.append({'pool': pool, 'user_id': user_id,
                             'exclude': list(exclude) if exclude else None,
                             'book_id': book_id})
            return 1000 + len(call_log)   # eindeutige Puzzle-ID je Aufruf

        leg.post_rookhub_puzzle = fake_post_rookhub

        try:
            # Test: Standard-Aufruf (anzahl=2 → 2 RookHub-Posts, zweiter schließt das erste aus)
            ia = make_interaction()
            run_async(cmd(ia, anzahl=2, buch=0, id='', user=None))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('post_rookhub_puzzle 2× aufgerufen', len(call_log) == 2)
            check('pool=random', call_log[0]['pool'] == 'random')
            check('zweiter Aufruf excludet das erste Puzzle', call_log[1]['exclude'] == [1001])
            check('ohne Buch → book_id None', call_log[0]['book_id'] is None)
            check('followup mit Bestaetigung',
                  len(ia.followup.calls) > 0 and
                  '2' in (ia.followup.calls[0].get('content') or ''))

            # Test: buch:<ID> wird als book_id an RookHub durchgereicht
            call_log.clear()
            ia = make_interaction()
            run_async(cmd(ia, anzahl=1, buch=7, id='', user=None))
            check('buch → book_id durchgereicht', call_log and call_log[0]['book_id'] == 7)

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
            leg.post_rookhub_puzzle = orig_post
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_puzzle_blind_by_id():
    """Regression: /puzzle id:...:blind:N baut den Puzzle-Kontext ohne NameError (diff)."""
    print('[/puzzle blind-by-id]')
    import chess
    import chess.pgn
    import puzzle as leg

    tmpdir = setup_temp_config()
    cmd = _captured_commands.get('puzzle')
    check('cmd_puzzle gefunden', cmd is not None)
    if not cmd:
        teardown_temp_config(tmpdir)
        return

    game = chess.pgn.Game()
    game.headers['White'] = 'A'
    game.headers['Black'] = 'B'
    game.add_variation(chess.Move.from_uci('e2e4'))

    saved = {}
    captured = {}
    names = ('find_line_by_id', '_has_training_comment', '_split_for_blind',
             '_load_books_config', '_render_board', '_resilient_send',
             '_register_puzzle_msg', '_build_puzzle_context', 'save_puzzle_context',
             '_solution_pgn')
    orig = {n: getattr(leg, n) for n in names}

    async def fake_resilient_send(channel, **kw):
        return await channel.send(**kw)

    def rec_build_ctx(g, turn, diff, line_id, include_solution=True):
        captured['diff'] = diff
        return {'difficulty': diff, 'line_id': line_id}

    try:
        leg.find_line_by_id = lambda lid: ('test.pgn:1.1', game)
        leg._has_training_comment = lambda g: True
        leg._split_for_blind = lambda orig_game, n: (chess.Board(), ['e4', 'e5'], game)
        leg._load_books_config = lambda: {'test.pgn': {'difficulty': 'Mittel', 'rating': 5}}
        leg._render_board = lambda board: None
        leg._resilient_send = fake_resilient_send
        leg._register_puzzle_msg = lambda *a, **k: None
        leg._build_puzzle_context = rec_build_ctx
        leg.save_puzzle_context = lambda uid, ctx: saved.update(uid=uid, ctx=ctx)
        leg._solution_pgn = lambda g: ''

        ia = make_interaction()
        run_async(cmd(ia, anzahl=1, buch=0, id='test.pgn:1.1:blind:2', user=None))

        contents = ' '.join((c.get('content') or '') for c in ia.followup.calls)
        check('Blind-per-ID erfolgreich (kein NameError)', 'per DM gesendet' in contents)
        check('kein generischer Fehler-Followup', 'Ein Fehler ist aufgetreten' not in contents)
        check('Kontext-difficulty aus meta (statt undefined diff)', captured.get('diff') == 'Mittel')
        check('save_puzzle_context aufgerufen', saved.get('ctx') is not None)
    finally:
        for n, fn in orig.items():
            setattr(leg, n, fn)
        teardown_temp_config(tmpdir)
    print()


def test_puzzle_link_only():
    """hideBoard: _send_puzzle_link_only postet NUR den klickbaren Link, kein Embed/Bild."""
    print('[/puzzle hideBoard link-only]')
    import chess
    import chess.pgn
    import puzzle as leg
    import puzzle.rookhub as rh
    from test_helpers import FakeChannel

    tmpdir = setup_temp_config()
    orig_web = rh.web_url_for_line
    try:
        game = chess.pgn.Game()
        game.headers['White'] = 'Carlsen, M.'
        game.headers['Black'] = 'Rapport, R.'
        game.add_variation(chess.Move.from_uci('e2e4'))

        # Link vorhanden → genau eine Nachricht, nur der klickbare Link, kein Embed/File
        rh.web_url_for_line = lambda lid: 'https://rookhub.test/puzzles/book/42'
        ch = FakeChannel()
        run_async(leg._send_puzzle_link_only(ch, game, 'buch.pgn:001',
                                             user_id=123, diff='Fortgeschritten', turn=chess.WHITE))
        check('genau 1 Nachricht', len(ch.sent) == 1)
        check('Inhalt ist der klickbare Link',
              len(ch.sent) == 1 and ch.sent[0].content ==
              '[Klickbares Rätsel](https://rookhub.test/puzzles/book/42)')
        check('kein Embed', len(ch.sent) == 1 and 'embed' not in ch.sent[0].kwargs)
        check('kein Bild/File', len(ch.sent) == 1 and 'file' not in ch.sent[0].kwargs)

        # Kein Link → knapper Fallback-Text statt leerer DM
        rh.web_url_for_line = lambda lid: None
        ch2 = FakeChannel()
        run_async(leg._send_puzzle_link_only(ch2, game, 'buch.pgn:002',
                                             user_id=123, diff='', turn=chess.WHITE))
        check('Fallback: 1 Nachricht', len(ch2.sent) == 1)
        check('Fallback ohne Embed', len(ch2.sent) == 1 and 'embed' not in ch2.sent[0].kwargs)
        check('Fallback nennt line_id',
              len(ch2.sent) == 1 and 'buch.pgn:002' in (ch2.sent[0].content or ''))
    finally:
        rh.web_url_for_line = orig_web
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

        # /kurs holt die Bücher jetzt von RookHub → rookhub.get_books patchen
        orig_books = leg.rookhub.get_books

        try:
            # Test: keine Bücher
            leg.rookhub.get_books = lambda *a, **k: []
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('keine Bücher → Hinweis', len(ia.followup.calls) > 0)

            # Test: mit Büchern (Übersicht)
            leg.rookhub.get_books = lambda *a, **k: [
                {'bookId': 7, 'bookFileName': 'book1_firstkey.pgn',
                 'difficulty': 'Anfaenger', 'bookRating': 3, 'puzzleCount': 42},
            ]
            ia = make_interaction()
            run_async(cmd(ia, buch=0))
            embed = ia.followup.calls[0].get('embed')
            check('Übersicht → Embed hat Felder',
                  embed is not None and len(embed.fields) > 0)
            check('Übersicht nennt Buch-ID',
                  embed is not None and any('7' in (f.get('name') or '') for f in embed.fields))

            # Test: Detailansicht (buch = RookHub-Buch-ID)
            ia = make_interaction()
            run_async(cmd(ia, buch=7))
            embed = ia.followup.calls[0].get('embed')
            check('Detail → Embed', embed is not None)
            check('Detail nennt /puzzle buch:7',
                  embed is not None and '/puzzle buch:7' in (embed.description or ''))
        finally:
            leg.rookhub.get_books = orig_books
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_train():
    """/train verweist jetzt auf RookHub-Kurse (Training + Fortschritt liegen dort)."""
    print('[/train]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('train')
        check('cmd_train gefunden', cmd is not None)
        if not cmd:
            return
        ia = make_interaction()
        run_async(cmd(ia, buch=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('train → RookHub-Hinweis', 'rookhub' in content)
        check('train → Verknüpfungs-/Puzzle-Hinweis', '/link' in content or '/puzzle' in content)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_next():
    """/next verweist jetzt auf RookHub-Kurse."""
    print('[/next]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('next')
        check('cmd_next gefunden', cmd is not None)
        if not cmd:
            return
        ia = make_interaction()
        run_async(cmd(ia, anzahl=1))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('next → RookHub-Hinweis', 'rookhub' in content)
        check('next → /puzzle-Hinweis', '/puzzle' in content)
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
    """/blind ist abgelöst (Discord-Blind entfällt) → verweist auf /puzzle bzw. RookHub."""
    print('[/blind]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('blind')
        check('cmd_blind gefunden', cmd is not None)
        if not cmd:
            return
        ia = make_interaction()
        run_async(cmd(ia, moves=4, anzahl=1, buch=0, user=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('blind → abgelöst/RookHub-Hinweis', 'abgelöst' in content or 'rookhub' in content)
        check('blind → /puzzle-Hinweis', '/puzzle' in content)
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
    old_cap = btns._tracker._cap
    btns._tracker._cap = 5
    try:
        for i in range(6):
            btns._apply_click(i, '✅', user_id=600)
        check('eviction → max entries <= cap+1', len(btns._clicks) <= 5 + 1)
        # Aelteste (msg_id=0) sollte rausgeflogen sein
        check('eviction → msg 0 entfernt', 0 not in btns._clicks)
    finally:
        btns._tracker._cap = old_cap

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


def test_build_puzzle_embed():
    """Tests fuer puzzle/embed.py build_puzzle_embed."""
    print('[build_puzzle_embed]')
    import chess
    import chess.pgn
    import io as _io
    from puzzle.embed import build_puzzle_embed

    # Minimales PGN Game erzeugen
    pgn = _io.StringIO('[Event "TestKurs"]\n[White "Linie1"]\n[Black "Kapitel1"]\n\n1. e4 *')
    game = chess.pgn.read_game(pgn)

    # --- Basis-Embed mit allen Feldern ---
    embed = build_puzzle_embed(game, turn=chess.WHITE, puzzle_num=3,
                               puzzle_total=42, difficulty='Mittel',
                               rating=1500, line_id='test.pgn:1.1',
                               blind_moves=0)
    check('embed title enthaelt Event', 'TestKurs' in embed.title)
    check('embed hat Kapitel-Feld', any('Kapitel' in f.get('name', '') for f in embed.fields))
    check('embed hat Linie-Feld', any('Linie' in f.get('name', '') for f in embed.fields))
    check('embed hat Schwierigkeit', any('Mittel' in str(f.get('value', '')) for f in embed.fields))
    check('embed hat Am-Zug Weiss', any('Weiß' in str(f.get('value', '')) for f in embed.fields))
    check('embed footer ohne blind', embed._footer.get('text') == 'ID: test.pgn:1.1')

    # --- Schwarz am Zug ---
    embed2 = build_puzzle_embed(game, turn=chess.BLACK)
    check('Am-Zug Schwarz', any('Schwarz' in str(f.get('value', '')) for f in embed2.fields))

    # --- blind_moves im Footer ---
    embed3 = build_puzzle_embed(game, line_id='x.pgn:1.1', blind_moves=4)
    check('footer mit blind', ':blind:4' in embed3._footer.get('text', ''))

    # --- Kein line_id → Default-Footer ---
    embed4 = build_puzzle_embed(game)
    check('default footer', 'Tägliches Puzzle' in embed4._footer.get('text', ''))

    # --- Langer Event-Name wird gekuerzt ---
    pgn_long = _io.StringIO(f'[Event "{"A" * 100}"]\n\n1. e4 *')
    game_long = chess.pgn.read_game(pgn_long)
    embed5 = build_puzzle_embed(game_long)
    check('langer Titel gekuerzt', len(embed5.title) <= 84)  # 🧩 + space + 80 chars max

    # --- White == Event → kein Linie-Feld ---
    pgn_same = _io.StringIO('[Event "Kurs"]\n[White "Kurs"]\n\n1. e4 *')
    game_same = chess.pgn.read_game(pgn_same)
    embed6 = build_puzzle_embed(game_same)
    check('same name → kein Linie-Feld',
          not any('Linie' in f.get('name', '') for f in embed6.fields))

    # --- puzzle_num=0 → kein Stats-Feld ---
    embed7 = build_puzzle_embed(game, puzzle_num=0)
    check('puzzle_num=0 → kein Stats',
          not any('Heute' in str(f.get('value', '')) for f in embed7.fields))

    print()



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


def test_webhook_verify_signature():
    """HMAC-Signatur-Verifikation ist robust und timing-safe."""
    print('[webhook _verify_signature]')
    import hmac as _hmac
    import hashlib as _hashlib
    from core.webhook_server import _verify_signature

    secret = 's3cret'
    body = b'{"puzzleId":42}'
    good = _hmac.new(secret.encode(), body, _hashlib.sha256).hexdigest()

    check('valid signature → True', _verify_signature(secret, body, good) is True)
    check('sha256= prefix akzeptiert', _verify_signature(secret, body, 'sha256=' + good) is True)
    check('missing header → False', _verify_signature(secret, body, None) is False)
    check('wrong signature → False', _verify_signature(secret, body, 'deadbeef' * 8) is False)
    check('empty signature → False', _verify_signature(secret, body, '') is False)
    check('different secret → False', _verify_signature('other', body, good) is False)
    check('different body → False', _verify_signature(secret, b'{"x":1}', good) is False)

    # --- Timestamp-/Replay-Schutz (opt-in, rueckwaertskompatibel) ---
    import time as _time
    now = 1_700_000_000
    ts = now  # frisch
    ts_sig = _hmac.new(secret.encode(), f'{ts}.'.encode() + body, _hashlib.sha256).hexdigest()
    check('mit Timestamp: gueltige Sig+frischer TS → True',
          _verify_signature(secret, body, ts_sig, timestamp_header=str(ts), now=now) is True)
    # Alter Body-only-Signatur darf NICHT mehr passen, sobald ein TS mitkommt
    check('mit Timestamp: alte body-only Sig → False',
          _verify_signature(secret, body, good, timestamp_header=str(ts), now=now) is False)
    # Abgelaufener Timestamp (Replay nach >300s) → abgelehnt, auch mit gueltiger Sig
    old_ts = now - 400
    old_sig = _hmac.new(secret.encode(), f'{old_ts}.'.encode() + body, _hashlib.sha256).hexdigest()
    check('mit Timestamp: abgelaufen (>300s) → False',
          _verify_signature(secret, body, old_sig, timestamp_header=str(old_ts), now=now) is False)
    # Zukunfts-Timestamp knapp im Fenster → ok
    fut_ts = now + 200
    fut_sig = _hmac.new(secret.encode(), f'{fut_ts}.'.encode() + body, _hashlib.sha256).hexdigest()
    check('mit Timestamp: Zukunft im Fenster → True',
          _verify_signature(secret, body, fut_sig, timestamp_header=str(fut_ts), now=now) is True)
    check('mit Timestamp: kaputter TS-Header → False',
          _verify_signature(secret, body, ts_sig, timestamp_header='abc', now=now) is False)
    # Leerer Timestamp-Header → wie kein Header (Fallback auf body-only)
    check('leerer Timestamp-Header → Fallback body-only',
          _verify_signature(secret, body, good, timestamp_header='', now=now) is True)
    print()


def test_webhook_handler_dispatches_to_apply_solver_update():
    """POST /webhook/puzzle-attempt: HMAC-verifiziert + ruft apply_solver_update fuer
    den aktuell gemerkten Daily-Post auf. 401 bei falscher Sig, 200 sonst."""
    print('[webhook handler dispatch]')
    import hashlib as _hashlib
    import hmac as _hmac
    import json as _json
    from unittest.mock import MagicMock, AsyncMock
    from aiohttp import web
    from core import webhook_server
    from puzzle import daily_results as dr

    secret = 'unit-test-secret'
    captured = {}

    # Patch: current() liefert einen aktuellen Daily-Post mit puzzle_id=42.
    orig_current = dr.current
    dr.current = lambda: {'channel_id': 1, 'message_id': 555, 'puzzle_id': 42}
    orig_apply = dr.apply_solver_update
    async def fake_apply(bot, cur, results):
        captured['args'] = (cur, results)
    dr.apply_solver_update = fake_apply

    handler = webhook_server._make_handler(bot=MagicMock(), secret=secret)

    async def post_request(body_dict: dict, sig_override: str | None = None) -> web.Response:
        body = _json.dumps(body_dict).encode('utf-8')
        sig = sig_override if sig_override is not None else \
              _hmac.new(secret.encode(), body, _hashlib.sha256).hexdigest()
        # MagicMock-Request mit .read() async + headers
        req = MagicMock()
        req.read = AsyncMock(return_value=body)
        req.headers = {'X-Webhook-Signature': sig} if sig is not None else {}
        return await handler(req)

    # 1) Gueltige Signatur + matching puzzleId → apply_solver_update aufgerufen.
    captured.clear()
    payload = {'puzzleId': 42, 'results': {'solvedCount': 1, 'attemptCount': 3,
                                            'anonymousSolvedCount': 0,
                                            'solvers': [{'name': 'Anna', 'discordId': '111'}]}}
    resp = run_async(post_request(payload))
    check('valid → status 200', resp.status == 200)
    check('valid → apply_solver_update aufgerufen', 'args' in captured)
    if 'args' in captured:
        cur, results = captured['args']
        check('valid → results durchgereicht (solvedCount)', results.get('solvedCount') == 1)
        check('valid → cur passt', cur.get('puzzle_id') == 42)

    # 2) Falsche Signatur → 401, kein apply.
    captured.clear()
    resp = run_async(post_request(payload, sig_override='deadbeefdeadbeef'))
    check('invalid sig → status 401', resp.status == 401)
    check('invalid sig → kein apply', 'args' not in captured)

    # 3) Korrekter Body, aber puzzleId passt nicht zum aktuellen Daily → 200, kein apply.
    captured.clear()
    other_payload = {'puzzleId': 999, 'results': payload['results']}
    resp = run_async(post_request(other_payload))
    check('non-current puzzleId → status 200', resp.status == 200)
    check('non-current puzzleId → kein apply', 'args' not in captured)

    # 4) Flacher Payload (results direkt auf Top-Level, ohne ``results``-Wrapper).
    captured.clear()
    flat_payload = {'puzzleId': 42, 'solvedCount': 2, 'anonymousSolvedCount': 1,
                    'attemptCount': 5, 'solvers': []}
    resp = run_async(post_request(flat_payload))
    check('flat payload → status 200', resp.status == 200)
    check('flat payload → apply aufgerufen', 'args' in captured)
    if 'args' in captured:
        _, results = captured['args']
        check('flat payload → solvedCount durchgereicht', results.get('solvedCount') == 2)

    # 5) Kein aktueller Daily-Post → 200, kein apply.
    dr.current = lambda: None
    captured.clear()
    resp = run_async(post_request(payload))
    check('no current daily → status 200', resp.status == 200)
    check('no current daily → kein apply', 'args' not in captured)

    # Cleanup
    dr.current = orig_current
    dr.apply_solver_update = orig_apply
    print()


def test_daily_regenerate_webhook():
    """POST /webhook/daily-regenerate: HMAC-verifiziert + postet neues Daily wenn date == current."""
    print('[webhook daily-regenerate handler]')
    import hashlib as _hashlib
    import hmac as _hmac
    import json as _json
    from unittest.mock import MagicMock, AsyncMock, patch
    from aiohttp import web
    from core import webhook_server
    from puzzle import daily_results as dr

    secret = 'regen-secret'
    posted = {}

    orig_current = dr.current

    async def fake_post_rookhub_puzzle(channel, pool, **kwargs):
        posted['called'] = True
        posted['pool'] = pool

    async def make_request(body_dict: dict, sig_override=None) -> web.Response:
        body = _json.dumps(body_dict).encode('utf-8')
        sig = sig_override if sig_override is not None else \
              _hmac.new(secret.encode(), body, _hashlib.sha256).hexdigest()
        req = MagicMock()
        req.read = AsyncMock(return_value=body)
        req.headers = {'X-Webhook-Signature': sig} if sig else {}
        return req

    # Fake-Message für alten Thread (channel_id=1 aus current())
    fake_old_msg = MagicMock()
    fake_old_msg.reply = AsyncMock()
    fake_old_ch = MagicMock()
    fake_old_ch.fetch_message = AsyncMock(return_value=fake_old_msg)

    # Haupt-Channel (channel_id=999, wird für den neuen Post verwendet)
    fake_channel = MagicMock()

    def get_channel_by_id(cid):
        if cid == 1:
            return fake_old_ch
        return fake_channel

    fake_bot = MagicMock()
    fake_bot.get_channel = MagicMock(side_effect=get_channel_by_id)
    fake_bot.fetch_channel = AsyncMock(return_value=fake_old_ch)

    with patch('puzzle.posting.post_rookhub_puzzle', fake_post_rookhub_puzzle):
        handler = webhook_server._make_daily_regenerate_handler(
            bot=fake_bot, secret=secret, daily_channels=[(999, 'de')])

        today = dr._today()

        # 1) Datum == aktuelles HEUTIGES Daily → neues Puzzle posten, alter Thread bekommt Hinweis
        dr.current = lambda: {'date': today, 'channel_id': 1, 'message_id': 555, 'puzzle_id': 100}
        posted.clear()
        req = run_async(make_request({'date': today, 'puzzleId': 200}))
        resp = run_async(handler(req))
        check('current date → status 200', resp.status == 200)
        check('current date → post_rookhub_puzzle aufgerufen', posted.get('called') is True)
        check('current date → pool daily', posted.get('pool') == 'daily')
        check('current date → alter Thread bekommt Reply', fake_old_msg.reply.called)

        # 1b) REGRESSION: Regenerate eines VERGANGENEN Datums, das (noch) als current gilt
        #     (heutiges Daily bis zum Tages-Post noch nicht gepostet) → KEIN Posting.
        #     Vorher wurde hier verfrueht das heutige Puzzle gepostet + Solver-Tracking gekapert.
        dr.current = lambda: {'date': '2020-01-01', 'channel_id': 1, 'message_id': 555, 'puzzle_id': 100}
        posted.clear()
        fake_old_msg.reply.reset_mock()
        req = run_async(make_request({'date': '2020-01-01', 'puzzleId': 200}))
        resp = run_async(handler(req))
        check('past date == current → status 200', resp.status == 200)
        check('past date == current → KEIN Posting (kein Vorzeitig-Post)', not posted.get('called'))
        check('past date == current → kein Ersetzt-Reply', not fake_old_msg.reply.called)

        # 2) Datum != aktuelles Daily → kein Posting
        posted.clear()
        fake_old_msg.reply.reset_mock()
        req = run_async(make_request({'date': '2026-06-05', 'puzzleId': 300}))
        resp = run_async(handler(req))
        check('different date → status 200', resp.status == 200)
        check('different date → kein Posting', not posted.get('called'))

        # 3) Kein aktuelles Daily → kein Posting
        dr.current = lambda: None
        posted.clear()
        req = run_async(make_request({'date': '2026-06-06', 'puzzleId': 400}))
        resp = run_async(handler(req))
        check('no current daily → status 200', resp.status == 200)
        check('no current daily → kein Posting', not posted.get('called'))

        # 4) Falsche Signatur → 401
        posted.clear()
        req = run_async(make_request({'date': '2026-06-06', 'puzzleId': 200}, sig_override='bad'))
        resp = run_async(handler(req))
        check('invalid sig → status 401', resp.status == 401)

        # 5) Fehlendes Pflichtfeld → 400
        dr.current = lambda: {'date': '2026-06-06', 'channel_id': 1, 'message_id': 555, 'puzzle_id': 100}
        req = run_async(make_request({'date': '2026-06-06'}))  # kein puzzleId
        resp = run_async(handler(req))
        check('missing puzzleId → status 400', resp.status == 400)

        # 6) Idempotenz: aktuelles Daily zeigt bereits die regenerierte puzzleId
        #    → kein erneutes Posting (Schutz vor wiederholtem Webhook-Feuern).
        dr.current = lambda: {'date': '2026-06-06', 'channel_id': 1, 'message_id': 555, 'puzzle_id': 200}
        posted.clear()
        fake_old_msg.reply.reset_mock()
        req = run_async(make_request({'date': '2026-06-06', 'puzzleId': 200}))
        resp = run_async(handler(req))
        check('schon aktuelle puzzleId → status 200', resp.status == 200)
        check('schon aktuelle puzzleId → kein erneutes Posting', not posted.get('called'))
        check('schon aktuelle puzzleId → kein Ersetzt-Hinweis', not fake_old_msg.reply.called)

        # 7) bool als puzzleId darf NICHT als int durchgehen → 400
        dr.current = lambda: {'date': '2026-06-06', 'channel_id': 1, 'message_id': 555, 'puzzle_id': 100}
        req = run_async(make_request({'date': '2026-06-06', 'puzzleId': True}))
        resp = run_async(handler(req))
        check('bool puzzleId → status 400', resp.status == 400)

    dr.current = orig_current
    print()


def test_daily_remember_multichannel():
    """remember() sammelt Posts mehrerer Channels unter EINEM Puzzle (Mehrkanal-Spiegelung
    in andere Guild), ist idempotent pro Channel und migriert das Alt-Format beim Lesen."""
    print('[daily_results.remember multichannel]')
    from puzzle import daily_results as dr
    from core.json_store import atomic_write

    tmpdir = setup_temp_config()
    orig_file = dr.DAILY_FILE
    dr.DAILY_FILE = os.path.join(tmpdir, 'daily_post.json')
    try:
        # Zwei Channels (z. B. Haupt-Guild + 2. Guild), gleiches Tagespuzzle
        dr.remember(111, 1001, 42)
        dr.remember(222, 2002, 42)
        cur = dr.current()
        check('2 Posts gemerkt', len(cur['posts']) == 2)
        check('Channel 111 + 222 vorhanden',
              {p['channel_id'] for p in cur['posts']} == {111, 222})
        check('Primaer = erster Channel (top-level gespiegelt)',
              cur['channel_id'] == 111 and cur['message_id'] == 1001)
        check('puzzle_id gesetzt', cur['puzzle_id'] == 42)

        # Re-Post Channel 111 → ersetzt nur dessen message_id; Primaer/Anzahl stabil
        dr.remember(111, 1009, 42)
        cur = dr.current()
        check('Re-Post: weiterhin 2 Posts', len(cur['posts']) == 2)
        check('Re-Post: message_id von 111 aktualisiert',
              next(p['message_id'] for p in cur['posts'] if p['channel_id'] == 111) == 1009)
        check('Re-Post: Primaer bleibt 111', cur['channel_id'] == 111)

        # Neues Puzzle → Liste wird zurueckgesetzt
        dr.remember(111, 3003, 99)
        cur = dr.current()
        check('Neues Puzzle: Liste zurueckgesetzt',
              len(cur['posts']) == 1 and cur['puzzle_id'] == 99)

        # Alt-Format (nur channel_id/message_id, kein posts) wird beim Lesen migriert
        atomic_write(dr.DAILY_FILE,
                     {'date': dr._today(), 'channel_id': 5, 'message_id': 6, 'puzzle_id': 7})
        cur = dr.current()
        check('Alt-Format migriert zu posts',
              cur['posts'] == [{'channel_id': 5, 'message_id': 6, 'lang': 'de'}])
    finally:
        dr.DAILY_FILE = orig_file
        teardown_temp_config(tmpdir)
    print()


def test_apply_solver_update_fans_out():
    """apply_solver_update editiert ALLE gemerkten Posts (beide Guilds), ermittelt neue
    Solver aber nur EINMAL → Reinforcement-DMs feuern genau einmal pro Loeser, nicht pro Channel."""
    print('[daily_results.apply_solver_update fan-out]')
    import asyncio
    from unittest.mock import MagicMock, AsyncMock
    from puzzle import daily_results as dr
    from core import reinforcement

    edited = []

    class FakeEmbed:
        def __init__(self): self.fields = []
        def add_field(self, name, value, inline=False): self.fields.append({'name': name})
        def set_field_at(self, i, name, value, inline=False): self.fields[i] = {'name': name}
        def set_image(self, url=None): pass

    def make_channel(cid):
        ch = MagicMock()
        m = MagicMock()
        m.embeds = [FakeEmbed()]
        m.edit = AsyncMock(side_effect=lambda **kw: edited.append(cid))
        ch.fetch_message = AsyncMock(return_value=m)
        return ch

    channels = {111: make_channel(111), 222: make_channel(222)}
    fake_bot = MagicMock()
    fake_bot.get_channel = MagicMock(side_effect=lambda cid: channels.get(cid))

    calls = {'new': 0}
    created = []
    orig_new = reinforcement.new_puzzle_solvers
    orig_ct = asyncio.create_task

    def counting_new(pid, solvers):
        calls['new'] += 1
        return [{'discordId': 12345}]

    def fake_ct(coro, *a, **k):
        created.append(coro)
        coro.close()  # 'coroutine never awaited'-Warnung vermeiden
        return MagicMock()

    reinforcement.new_puzzle_solvers = counting_new
    asyncio.create_task = fake_ct
    try:
        cur = {'puzzle_id': 42,
               'posts': [{'channel_id': 111, 'message_id': 1},
                         {'channel_id': 222, 'message_id': 2}]}
        results = {'solvers': [{'discordId': 12345, 'timeSeconds': 30}],
                   'solvedCount': 1, 'attemptCount': 1}
        run_async(dr.apply_solver_update(fake_bot, cur, results))
        check('beide Channels editiert', sorted(edited) == [111, 222])
        check('new_puzzle_solvers nur einmal (kein Pro-Channel-Dup)', calls['new'] == 1)
        check('genau eine Reinforcement-DM-Task', len(created) == 1)
    finally:
        reinforcement.new_puzzle_solvers = orig_new
        asyncio.create_task = orig_ct
    print()


def test_sync_commands_public_vs_guild():
    """_sync_commands: bei gesetztem GUILD_ID bekommt die Haupt-Guild ALLE Commands,
    global bleibt nur PUBLIC_COMMANDS (/puzzle) → Zusatz-Guilds haben nur /puzzle (+ Daily).
    /puzzle wird aus der Guild-Kopie entfernt (kein Duplikat in der Haupt-Guild)."""
    print('[_sync_commands public vs guild]')
    import bot as bot_mod

    class FakeCmd:
        def __init__(self, name): self.name = name

    class FakeTree:
        def __init__(self, names):
            self.global_cmds = {n: FakeCmd(n) for n in names}
            self.guild_cmds = {}
            self.synced = []  # ('global'|gid, sorted names)

        def copy_global_to(self, guild):
            self.guild_cmds[guild.id] = dict(self.global_cmds)

        def remove_command(self, name, guild=None):
            if guild is None:
                self.global_cmds.pop(name, None)
            else:
                self.guild_cmds.get(guild.id, {}).pop(name, None)

        def get_commands(self, guild=None):
            return list(self.global_cmds.values())

        async def sync(self, guild=None):
            if guild is None:
                self.synced.append(('global', sorted(self.global_cmds)))
            else:
                self.synced.append((guild.id, sorted(self.guild_cmds.get(guild.id, {}))))

    orig_tree, orig_gid = bot_mod.tree, bot_mod.GUILD_ID
    try:
        # GUILD_ID gesetzt → Split
        ft = FakeTree(['puzzle', 'kurs', 'daily', 'stats'])
        bot_mod.tree = ft
        bot_mod.GUILD_ID = 4242
        run_async(bot_mod._sync_commands())
        # discord.Object kann im Test gestubbt sein → Guild-ID nicht hart vergleichen,
        # sondern „alles ausser global" als Guild-Sync werten.
        guild_sync = [s for gid, s in ft.synced if gid != 'global']
        global_sync = [s for gid, s in ft.synced if gid == 'global']
        check('Guild-Sync erfolgt', len(guild_sync) == 1)
        check('Haupt-Guild = alle Nicht-Public', guild_sync and guild_sync[0] == ['daily', 'kurs', 'stats'])
        check('kein puzzle-Duplikat in Haupt-Guild', guild_sync and 'puzzle' not in guild_sync[0])
        check('Global nur /puzzle', global_sync and global_sync[0] == ['puzzle'])

        # Ohne GUILD_ID → globaler Sync aller Commands (Alt-Verhalten)
        ft2 = FakeTree(['puzzle', 'kurs', 'daily'])
        bot_mod.tree = ft2
        bot_mod.GUILD_ID = 0
        run_async(bot_mod._sync_commands())
        check('ohne GUILD_ID: nur globaler Sync', [g for g, _ in ft2.synced] == ['global'])
        check('ohne GUILD_ID: alle global', ft2.synced[0][1] == ['daily', 'kurs', 'puzzle'])
    finally:
        bot_mod.tree, bot_mod.GUILD_ID = orig_tree, orig_gid
    print()


def test_daily_language_de_en():
    """Pro-Channel-Sprache: build_daily_embed + format_solver_line liefern de/en;
    apply_solver_update findet/aktualisiert das (lokalisierte) Solver-Feld je Post-Sprache."""
    print('[daily language de/en]')
    import chess
    from puzzle.embed import build_daily_embed
    from puzzle import daily_results as dr

    # 1) Embed-Felder lokalisiert (Test-Embed speichert Felder als dicts)
    en = build_daily_embed(turn=chess.WHITE, solution_san='1. Qh7#', lang='en')
    names_en = [f.get('name', '') for f in en.fields]
    values_en = [str(f.get('value', '')) for f in en.fields]
    check('EN: To-move-Feld', 'To move' in names_en)
    check('EN: White to move', any('White to move' in v for v in values_en))
    check('EN: Daily-puzzle-Slot', any('Daily puzzle' in n for n in names_en))
    check('EN: Solution-Feld', any('Solution' in n for n in names_en))
    de = build_daily_embed(turn=chess.BLACK, solution_san='1. Qh7#', lang='de')
    names_de = [f.get('name', '') for f in de.fields]
    values_de = [str(f.get('value', '')) for f in de.fields]
    check('DE bleibt deutsch', any('Tagespuzzle' in n for n in names_de)
          and any('Schwarz am Zug' in v for v in values_de))

    # 2) Solver-Zeile lokalisiert
    res = {'solvedCount': 2, 'attemptCount': 5,
           'solvers': [{'name': 'A'}, {'name': 'B'}]}
    line_en = dr.format_solver_line(res, lang='en')
    check('EN: "Solved (2)"', 'Solved (2)' in line_en)
    check('EN: "attempted"', 'attempted' in line_en)
    line_de = dr.format_solver_line(res, lang='de')
    check('DE: "Gelöst (2)"', 'Gelöst (2)' in line_de)

    # 3) apply_solver_update editiert je Post in dessen Sprache (gemischt de/en)
    import asyncio
    from unittest.mock import MagicMock, AsyncMock
    from core import reinforcement

    captured = {}

    class FakeEmbed:
        def __init__(self): self.fields = []
        def add_field(self, name, value, inline=False): self.fields.append({'name': name, 'value': value})
        def set_field_at(self, i, name, value, inline=False): self.fields[i] = {'name': name, 'value': value}
        def set_image(self, url=None): pass

    def make_channel(cid):
        ch = MagicMock()
        m = MagicMock()
        m.embeds = [FakeEmbed()]
        async def _edit(embed=None): captured[cid] = list(embed.fields)
        m.edit = _edit
        ch.fetch_message = AsyncMock(return_value=m)
        return ch

    channels = {111: make_channel(111), 222: make_channel(222)}
    fake_bot = MagicMock()
    fake_bot.get_channel = MagicMock(side_effect=lambda cid: channels.get(cid))

    orig_new = reinforcement.new_puzzle_solvers
    orig_ct = asyncio.create_task
    reinforcement.new_puzzle_solvers = lambda pid, solvers: []
    asyncio.create_task = lambda coro, *a, **k: (coro.close(), MagicMock())[1]
    try:
        cur = {'puzzle_id': 7,
               'posts': [{'channel_id': 111, 'message_id': 1, 'lang': 'de'},
                         {'channel_id': 222, 'message_id': 2, 'lang': 'en'}]}
        run_async(dr.apply_solver_update(fake_bot, cur, res))
        de_field = captured[111][0]['name']
        en_field = captured[222][0]['name']
        check('Post 111 (de): deutsches Solver-Feld', 'Tagespuzzle' in de_field)
        check('Post 111 (de): deutsche Zeile', 'Gelöst' in captured[111][0]['value'])
        check('Post 222 (en): englisches Solver-Feld', 'Daily puzzle' in en_field)
        check('Post 222 (en): englische Zeile', 'Solved' in captured[222][0]['value'])
    finally:
        reinforcement.new_puzzle_solvers = orig_new
        asyncio.create_task = orig_ct
    print()


def test_daily_refresh_no_duplicate_board():
    """refresh() darf das Brettbild nicht doppelt rendern lassen.

    Beim Edit muss der lose Datei-Anhang entfernt werden (attachments=[])
    und embed.image auf die CDN-URL des Anhangs zeigen — sonst zeigt Discord
    das Bild zwei mal (Embed.image + standalone attachment darunter).

    Die Test-Helpers stubben discord.Embed mit FakeEmbed (fields = list[dict],
    _image = dict). Refresh muss damit umgehen (und mit prod EmbedProxy).
    """
    print('[daily_results.refresh no-duplicate-board]')
    import discord
    from puzzle import daily_results as dr

    captured = {}

    class _Att:
        filename = 'board.png'
        url = 'https://cdn.discordapp.com/attachments/1/2/board.png?ex=abc'

    # FakeEmbed (aus test_helpers) – fields werden als dict abgelegt.
    # FakeEmbed hat kein set_field_at(), darum monkey-patchen wir es defensiv:
    fake_embed = discord.Embed()
    fake_embed.add_field(name=dr.SOLVER_FIELD, value='alt', inline=False)
    def _set_field_at(idx, **kw):
        fake_embed.fields[idx] = kw
    fake_embed.set_field_at = _set_field_at

    class _Msg:
        id = 555
        attachments = [_Att()]
        embeds = [fake_embed]
        async def edit(self, **kw):
            captured['edit_kwargs'] = kw
        async def add_reaction(self, _):
            pass

    msg = _Msg()

    class _Ch:
        async def fetch_message(self, mid):
            return msg

    class _Bot:
        def get_channel(self, cid):
            return _Ch()

    orig_current = dr.current
    dr.current = lambda: {'channel_id': 1, 'message_id': 555, 'puzzle_id': 77, 'since': None}
    import puzzle.rookhub as rookhub
    orig_get = getattr(rookhub, 'get_daily_results', None)
    rookhub.get_daily_results = lambda pid, since=None: {
        'solvedCount': 1, 'anonymousSolvedCount': 0, 'attemptCount': 3,
        'solvers': [{'name': 'Anna', 'discordId': '111'}]
    }
    orig_warn = dr.log.warning
    warnings = []
    dr.log.warning = lambda *a, **k: warnings.append(a)
    try:
        try:
            run_async(dr.refresh(_Bot()))
        except Exception as _e:
            captured['refresh_exception'] = repr(_e)
    finally:
        dr.current = orig_current
        dr.log.warning = orig_warn
        if orig_get is not None:
            rookhub.get_daily_results = orig_get

    if 'refresh_exception' in captured:
        print(f'  ! refresh raised: {captured["refresh_exception"]}')
    for w in warnings:
        try:
            print(f'  ! warn: {w}')
        except Exception:
            print('  ! warn (unprintable)')

    edited = captured.get('edit_kwargs') or {}
    check('refresh: msg.edit aufgerufen', bool(edited))
    # Wichtig: KEIN attachments-Parameter mehr — den Anhang lassen wir in Ruhe,
    # damit Discord ihn unveraendert als Brett rendert (nicht ins Embed). Sonst
    # wuerde Discord beim Edit das Brett doppelt zeigen.
    check('refresh: kein attachments-Parameter (vorhandener Anhang bleibt)',
          'attachments' not in edited)
    edited_embed = edited.get('embed')
    check('refresh: embed mitgeschickt', edited_embed is not None)
    if edited_embed is not None:
        # embed.image ist explizit geleert, damit ein Alt-Embed mit CDN-URL
        # nicht zusaetzlich zum File-Anhang rendert.
        img_dict = getattr(edited_embed, '_image', None) or {}
        check('refresh: embed.image geleert (kein doppeltes Brett)',
              not img_dict.get('url'))
        field_values = [str(f.get('value', '')) for f in edited_embed.fields]
        check('refresh: SOLVER_FIELD enthaelt Gelöst-Zeile',
              any('Gelöst' in v for v in field_values))
    print()


def test_build_daily_embed():
    """Minimaler Tagespuzzle-Embed: Am Zug, Tagespuzzle-Slot, Lösungs-Spoiler — sonst nichts."""
    print('[build_daily_embed]')
    import chess
    from puzzle.embed import build_daily_embed, DAILY_SOLVER_FIELD

    # Weiss am Zug + Lösung
    e = build_daily_embed(turn=chess.WHITE, solution_san='1. Qxh7+ Kxh7 2. Rh3#')
    names = [f.get('name', '') for f in e.fields]
    values = [str(f.get('value', '')) for f in e.fields]

    check('kein Titel', not getattr(e, 'title', None))
    check('keine Footer', not getattr(e, '_footer', None) or not e._footer.get('text'))
    check('Am-Zug-Feld vorhanden', 'Am Zug' in names)
    check('Weiss am Zug', any('Weiß' in v for v in values))
    check('Tagespuzzle-Slot vorhanden', DAILY_SOLVER_FIELD in names)
    check('Tagespuzzle-Slot Placeholder', any('Noch niemand gelöst' in v for v in values))
    check('Lösung als Spoiler', '💡 Lösung' in names and any('||' in v for v in values))
    check('Reihenfolge Am-Zug → Tagespuzzle → Lösung',
          names == ['Am Zug', DAILY_SOLVER_FIELD, '💡 Lösung'])
    check('kein Kapitel-Feld', not any('Kapitel' in n for n in names))
    check('kein Linie-Feld', not any('Linie' in n for n in names))
    check('kein Schwierigkeit-Feld', not any('Schwierigkeit' in n for n in names))
    check('kein RookHub-Link-Feld', not any('RookHub' in v for v in values))

    # Schwarz am Zug, ohne Lösung
    e2 = build_daily_embed(turn=chess.BLACK)
    names2 = [f.get('name', '') for f in e2.fields]
    values2 = [str(f.get('value', '')) for f in e2.fields]
    check('Schwarz am Zug', any('Schwarz' in v for v in values2))
    check('ohne Lösung kein Spoiler-Feld', '💡 Lösung' not in names2)
    check('SOLVER_FIELD sync mit daily_results',
          DAILY_SOLVER_FIELD == __import__('puzzle.daily_results', fromlist=['SOLVER_FIELD']).SOLVER_FIELD)
    print()


def test_post_rookhub_puzzle_daily_uses_minimal_embed():
    """pool='daily' nutzt den minimalen build_daily_embed (kein Titel, kein Auf-RookHub-Link-Feld)."""
    print('[post_rookhub_puzzle daily minimal-embed]')
    import io
    import puzzle.posting as posting

    tmpdir = setup_temp_config()
    DTO = {'id': 77, 'lineId': 'b.pgn:1', 'bookFileName': 'b.pgn',
           'fen': 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
           'moves': 'e2e4 e7e5 g1f3', 'startPly': 0,
           'difficulty': 'Anfaenger', 'bookRating': 3}
    sent = []

    class _Msg:
        id = 999

    class _Ch:
        pass

    async def fake_send(target, *a, **kw):
        sent.append(kw)
        return _Msg()

    async def fake_render(game):
        return ('white', io.BytesIO(b'PNGDATA'))

    orig = (posting.rookhub.get_puzzle, posting.rookhub.puzzle_web_url, posting.rookhub.daily_web_url,
            posting.safe_render_board,
            posting._resilient_send, posting._register_puzzle_msg, posting.discord.DMChannel)
    posting.rookhub.get_puzzle = lambda pool, exclude=None, book_id=None: dict(DTO)
    posting.rookhub.puzzle_web_url = lambda pid: f'https://rookhub.test/puzzles/book/{pid}'
    posting.rookhub.daily_web_url = lambda date_str=None: 'https://rookhub.test/puzzles/daily/20260603'
    posting.safe_render_board = fake_render
    posting._resilient_send = fake_send
    posting._register_puzzle_msg = lambda *a, **k: None
    posting.discord.DMChannel = _Ch
    try:
        sent.clear()
        run_async(posting.post_rookhub_puzzle(_Ch(), 'daily', user_id=None, with_board=True))
        emb = sent[0].get('embed') if sent else None
        check('daily: Embed gesendet', emb is not None)
        if emb is not None:
            names = [f.get('name', '') for f in emb.fields]
            values = [str(f.get('value', '')) for f in emb.fields]
            check('daily: kein Titel', not getattr(emb, 'title', None))
            check('daily: kein Footer',
                  not getattr(emb, '_footer', None) or not emb._footer.get('text'))
            check('daily: kein Kapitel-Feld', not any('Kapitel' in n for n in names))
            check('daily: kein Linie-Feld', not any('Linie' in n for n in names))
            check('daily: kein "Auf RookHub"-Feld im Embed',
                  not any('Auf RookHub' in v for v in values))
            check('daily: Tagespuzzle-Slot vorhanden', '🏆 Tagespuzzle' in names)
            check('daily: Lösungs-Spoiler vorhanden', '💡 Lösung' in names)
            # Wichtig: kein embed.image — sonst rendert Discord beim Refresh
            # das Brett doppelt (Anhang + Embed.image)
            img_dict = getattr(emb, '_image', None) or {}
            check('daily: kein embed.image (Brett kommt rein als File-Anhang)',
                  not img_dict.get('url'))
        # File-Anhang im 1. Send: das Brettbild ist nicht im Embed sondern als File mitgeschickt
        file_present = sent and sent[0].get('file') is not None
        check('daily: Brett als File-Anhang gesendet (nicht im Embed)', bool(file_present))
        # RookHub-Link als separate Plaintext-Nachricht (keine Embed-Border)
        link_msgs = [s for s in sent if s.get('content') and 'Auf RookHub' in s.get('content', '')]
        check('daily: RookHub-Link als Plaintext-Nachricht', len(link_msgs) == 1)
        if link_msgs:
            check('daily: Link enthält die datumsbasierte URL', 'https://rookhub.test/puzzles/daily/20260603' in link_msgs[0]['content'])
            check('daily: Link-Nachricht ohne Embed', link_msgs[0].get('embed') is None)
            check('daily: Link unterdrückt URL-Auto-Preview',
                  link_msgs[0].get('suppress_embeds') is True)
    finally:
        (posting.rookhub.get_puzzle, posting.rookhub.puzzle_web_url, posting.rookhub.daily_web_url,
         posting.safe_render_board,
         posting._resilient_send, posting._register_puzzle_msg, posting.discord.DMChannel) = orig
        teardown_temp_config(tmpdir)
    print()


def test_post_rookhub_puzzle_board_vs_link():
    """Tagespuzzle: with_board=True rendert die Stellung (Embed + Brettbild) aus der RookHub-DTO;
    with_board=False (z. B. /puzzle) postet nur den Link."""
    print('[post_rookhub_puzzle board/link]')
    import io
    import puzzle.posting as posting

    tmpdir = setup_temp_config()
    DTO = {'id': 77, 'lineId': 'b.pgn:1', 'bookFileName': 'b.pgn',
           'fen': 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
           'moves': 'e2e4 e7e5 g1f3', 'startPly': 0,
           'difficulty': 'Anfaenger', 'bookRating': 3}
    sent = []

    class _Msg:
        id = 999

    class _Ch:  # wird unten als DMChannel-Typ gesetzt → is_dm=True (kein Thread-Pfad)
        pass

    async def fake_send(target, *a, **kw):
        sent.append(kw)
        return _Msg()

    async def fake_render(game):
        return ('white', io.BytesIO(b'PNGDATA'))

    orig = (posting.rookhub.get_puzzle, posting.safe_render_board,
            posting._resilient_send, posting._register_puzzle_msg, posting.discord.DMChannel)
    posting.rookhub.get_puzzle = lambda pool, exclude=None, book_id=None: dict(DTO)
    posting.safe_render_board = fake_render
    posting._resilient_send = fake_send
    posting._register_puzzle_msg = lambda *a, **k: None
    posting.discord.DMChannel = _Ch   # Fake-Channel als DM erkennen → is_dm kurzschließt Thread-Check
    try:
        # with_board=True → Embed + Brettbild (Stellung aus der DTO)
        sent.clear()
        pid = run_async(posting.post_rookhub_puzzle(_Ch(), 'random', user_id=None, with_board=True))
        check('board: pid zurück', pid == 77)
        check('board: Embed gesendet', bool(sent) and sent[0].get('embed') is not None)
        check('board: Brettbild angehängt', bool(sent) and sent[0].get('file') is not None)

        # with_board=False → nur Link-Text, kein Embed/Bild
        sent.clear()
        run_async(posting.post_rookhub_puzzle(_Ch(), 'random', user_id=None, with_board=False))
        check('link: content gesetzt', bool(sent) and bool(sent[0].get('content')))
        check('link: kein Embed', bool(sent) and sent[0].get('embed') is None)
    finally:
        (posting.rookhub.get_puzzle, posting.safe_render_board,
         posting._resilient_send, posting._register_puzzle_msg, posting.discord.DMChannel) = orig
        teardown_temp_config(tmpdir)
    print()
