"""Tests fuer Admin Commands: /daily, /ignore_kapitel, /test, /announce, /greeted, /stats, /dm-log, admin enforcement."""

import os
import io as _io
from unittest.mock import MagicMock

import test_helpers as h
from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    make_interaction, _captured_commands, _CapturingBot, _discord,
    FakeUser, FakeMember, FakeChannel, FakeRole,
    bot_mod, atomic_write, atomic_read,
)


def test_daily():
    """Smoke-Tests fuer /daily Command."""
    print('[/daily]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('daily')
        check('cmd_daily gefunden', cmd is not None)
        if not cmd:
            return

        import bot as bot_mod
        import puzzle as puzzle_mod

        old_bot = bot_mod.bot
        old_channel_id = bot_mod.CHANNEL_ID
        orig_post = puzzle_mod.post_puzzle

        call_log = []
        async def fake_post(channel, **kw):
            call_log.append(True)
            return 1

        puzzle_mod.post_puzzle = fake_post

        try:
            # Test: Channel nicht gefunden
            bot_mod.CHANNEL_ID = 0

            class NullBot:
                def get_channel(self, cid):
                    return None

            bot_mod.bot = NullBot()
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('Channel nicht gefunden → Fehler', 'nicht gefunden' in content)

            # Test: Erfolg
            bot_mod.CHANNEL_ID = 99999
            bot_mod.bot = _CapturingBot()
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('post_puzzle aufgerufen', len(call_log) > 0)
            check('followup gesendet', len(ia.followup.calls) > 0)
        finally:
            bot_mod.bot = old_bot
            bot_mod.CHANNEL_ID = old_channel_id
            puzzle_mod.post_puzzle = orig_post
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_ignore_kapitel():
    """Smoke-Tests fuer /ignore_kapitel Command."""
    print('[/ignore_kapitel]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('ignore_kapitel')
        check('cmd_ignore_kapitel gefunden', cmd is not None)
        if not cmd:
            return

        import puzzle as leg

        orig_load_ign = leg._load_chapter_ignore_list
        orig_ignore = leg.ignore_chapter
        orig_unignore = leg.unignore_chapter
        orig_list = leg._list_pgn_files
        orig_find_prefix = leg._find_chapter_prefix
        orig_list_chapters = leg._list_chapters

        _ignored = set()

        leg._load_chapter_ignore_list = lambda: _ignored
        leg.ignore_chapter = lambda b, p: _ignored.add(f'{b}:{p}')
        leg.unignore_chapter = lambda b, p: _ignored.discard(f'{b}:{p}')
        leg._list_pgn_files = lambda: ['book1.pgn']
        leg._find_chapter_prefix = lambda b, k: str(k) if k <= 5 else None
        leg._list_chapters = lambda b: {'1': 10, '2': 8, '3': 5}
        leg._clean_book_name = lambda fn: fn.replace('.pgn', '')

        try:
            # Test: Liste leer
            ia = make_interaction(admin=True)
            run_async(cmd(ia, buch=0, kapitel=0, aktion=None))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('Liste leer → Hinweis', 'keine kapitel' in content)

            # Test: ignore
            ia = make_interaction(admin=True)
            run_async(cmd(ia, buch=1, kapitel=3, aktion=None))
            content = ia.followup.calls[0].get('content') or ''
            check('ignore → Bestaetigung', 'ignoriert' in content.lower())
            check('Kapitel in Liste', 'book1.pgn:3' in _ignored)

            # Test: unignore
            aktion_mock = MagicMock()
            aktion_mock.value = 'unignore'
            ia = make_interaction(admin=True)
            run_async(cmd(ia, buch=1, kapitel=3, aktion=aktion_mock))
            content = ia.followup.calls[0].get('content') or ''
            check('unignore → Bestaetigung', 'aktiviert' in content.lower())
        finally:
            leg._load_chapter_ignore_list = orig_load_ign
            leg.ignore_chapter = orig_ignore
            leg.unignore_chapter = orig_unignore
            leg._list_pgn_files = orig_list
            leg._find_chapter_prefix = orig_find_prefix
            leg._list_chapters = orig_list_chapters
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_test_cmd():
    """Smoke-Tests fuer /test Command (alle Modi)."""
    print('[/test]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('test')
        check('cmd_test gefunden', cmd is not None)
        if not cmd:
            return

        import commands.test as test_mod

        # --- Modus: snapshots (bestehender Test) ---
        orig_load = test_mod._load_snapshots
        orig_find = test_mod._find_game

        fake_snap = {
            'filename': 'book1_firstkey.pgn',
            'round': '001.001',
            'trimmed': False,
            'fen': 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
            'side': 'w',
            'first_move_uci': 'e2e4',
        }
        test_mod._load_snapshots = lambda: [fake_snap]

        import chess.pgn

        def fake_find_game(filename, round_id):
            pgn = _io.StringIO('1. e4 e5 *')
            return chess.pgn.read_game(pgn)

        test_mod._find_game = fake_find_game

        try:
            ia = make_interaction(admin=True)
            run_async(cmd(ia, modus='snapshots', kurs=0, puzzle=0, lichess=0))
            check('snapshots: defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('snapshots: followup gesendet', len(ia.followup.calls) > 0)
        finally:
            test_mod._load_snapshots = orig_load
            test_mod._find_game = orig_find

        # --- Modus: status ---
        import bot as bot_mod_local
        old_bot_loops = getattr(bot_mod_local.bot, '_task_loops', None)
        fake_loop = MagicMock()
        fake_loop.is_running = MagicMock(return_value=True)
        bot_mod_local.bot._task_loops = {'test_loop': fake_loop}
        try:
            ia = make_interaction(admin=True)
            run_async(cmd(ia, modus='status', kurs=0, puzzle=0, lichess=0))
            check('status: defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('status: followup gesendet', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('status: Embed vorhanden', embed is not None)
            if embed:
                check('status: Titel', embed.title == 'Bot-Status')
                field_names = [f.get('name', '') for f in embed.fields]
                has_version = any('Version' in n for n in field_names)
                check('status: Version-Field', has_version)
                has_loop = any('test_loop' in n for n in field_names)
                check('status: Loop-Field', has_loop)
        finally:
            if old_bot_loops is not None:
                bot_mod_local.bot._task_loops = old_bot_loops
            else:
                bot_mod_local.bot._task_loops = {}

        # --- Modus: files ---
        # Temp-Config mit gueltiger JSON
        from core.json_store import atomic_write as aw
        aw(os.path.join(tmpdir, 'test_config.json'), {'key': 'value'})
        ia = make_interaction(admin=True)
        run_async(cmd(ia, modus='files', kurs=0, puzzle=0, lichess=0))
        check('files: defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
        check('files: followup gesendet', len(ia.followup.calls) > 0)
        embed = ia.followup.calls[0].get('embed')
        check('files: Embed vorhanden', embed is not None)
        if embed:
            check('files: Titel', embed.title == 'JSON-Integritaet')

        # --- Modus: rendering ---
        orig_render = test_mod._render_board
        test_mod._render_board = lambda board: _io.BytesIO(b'fake-png')
        try:
            ia = make_interaction(admin=True)
            run_async(cmd(ia, modus='rendering', kurs=0, puzzle=0, lichess=0))
            check('rendering: defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('rendering: followup gesendet', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('rendering: Embed vorhanden', embed is not None)
            if embed:
                check('rendering: Titel', embed.title == 'Board-Rendering')
        finally:
            test_mod._render_board = orig_render

        # --- Modus: assets ---
        ia = make_interaction(admin=True)
        run_async(cmd(ia, modus='assets', kurs=0, puzzle=0, lichess=0))
        check('assets: defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
        check('assets: followup gesendet', len(ia.followup.calls) > 0)
        embed = ia.followup.calls[0].get('embed')
        check('assets: Embed vorhanden', embed is not None)
        if embed:
            check('assets: Titel', embed.title == 'Assets')

        # --- Modus: lichess ---
        # Mock Token weg damit kein HTTP-Call gemacht wird
        import puzzle.lichess as lichess_mod
        orig_token_mod = lichess_mod.LICHESS_TOKEN
        lichess_mod.LICHESS_TOKEN = ''
        try:
            ia = make_interaction(admin=True)
            run_async(cmd(ia, modus='lichess', kurs=0, puzzle=0, lichess=0))
            check('lichess: defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('lichess: followup gesendet', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('lichess: Embed vorhanden', embed is not None)
            if embed:
                check('lichess: Titel', embed.title == 'Lichess-API')
        finally:
            lichess_mod.LICHESS_TOKEN = orig_token_mod

        # --- Modus: pgn ---
        orig_books_dir = test_mod.BOOKS_DIR
        orig_load_config = test_mod._load_books_config
        pgn_dir = os.path.join(tmpdir, 'books_test')
        os.makedirs(pgn_dir, exist_ok=True)
        with open(os.path.join(pgn_dir, 'test_firstkey.pgn'), 'w') as f:
            f.write('[Event "Test"]\n[Round "1"]\n\n1. e4 e5 *\n')
        test_mod.BOOKS_DIR = pgn_dir
        test_mod._load_books_config = lambda: {'test_firstkey.pgn': {}}
        try:
            ia = make_interaction(admin=True)
            run_async(cmd(ia, modus='pgn', kurs=0, puzzle=0, lichess=0))
            check('pgn: defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('pgn: followup gesendet', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('pgn: Embed vorhanden', embed is not None)
            if embed:
                check('pgn: Titel', embed.title == 'PGN-Dateien')
        finally:
            test_mod.BOOKS_DIR = orig_books_dir
            test_mod._load_books_config = orig_load_config

        # --- CheckResult + _build_result_embed Unit-Test ---
        from commands.test import CheckResult, _build_result_embed
        checks = [
            CheckResult('Test OK', True, 'alles gut'),
            CheckResult('Test FAIL', False, 'kaputt'),
        ]
        embed = _build_result_embed('Unit-Test', checks)
        check('build_result_embed: Titel', embed.title == 'Unit-Test')
        check('build_result_embed: 2 Fields', len(embed.fields) == 2)
        check('build_result_embed: Footer 1/2',
              '1/2' in embed._footer.get('text', ''))
        check('build_result_embed: rot bei Fehlern',
              embed.colour == 0xe74c3c)

        all_ok_embed = _build_result_embed('Alles OK', [
            CheckResult('A', True, ''),
        ])
        check('build_result_embed: gruen bei 100%',
              all_ok_embed.colour != 0xe74c3c)

        # --- Test-Reminder (Wochenpost + Turnier) ---
        import commands.wochenpost as wp_mod
        import commands.schachrallye as sr_mod
        from datetime import timedelta

        # Wochenpost: User subscribed + geposteter Eintrag
        atomic_write(wp_mod.WOCHENPOST_FILE, [
            {'id': 1, 'datum': '2026-04-25', 'titel': '25.04.2026',
             'posted': True, 'msg_id': 111, 'thread_id': 222},
        ])
        atomic_write(wp_mod.WOCHENPOST_SUB_FILE, {
            'subscribers': {'12345': {'hour': 17, 'minute': 0,
                                      'next': '2099-01-01T00:00:00+00:00'}},
            'resolved': {},
        })

        # Turnier: User subscribed + zukuenftiges Event
        from datetime import date
        future = (date.today() + timedelta(days=5)).strftime('%Y-%m-%d')
        atomic_write(sr_mod.TURNIER_FILE, {
            'events': [
                {'id': 1, 'name': 'Test-Blitz', 'datum': future,
                 'ort': 'Innsbruck', 'tags': ['blitz']},
            ],
            'subscribers': {'blitz': [12345]},
            'next_id': 2,
        })

        ia = make_interaction(admin=True)
        run_async(cmd(ia, modus='status', kurs=0, puzzle=0, lichess=0))
        reminder_calls = [c for c in ia.followup.calls
                          if 'Test-Reminder' in (c.get('content') or '')]
        check('test-reminder: followup vorhanden', len(reminder_calls) > 0)
        if reminder_calls:
            content = reminder_calls[0].get('content', '')
            check('test-reminder: wochenpost', 'wochenpost' in content)
            check('test-reminder: turnier', 'turnier' in content)

        # Ohne Subscriptions → kein Reminder-Followup
        atomic_write(wp_mod.WOCHENPOST_SUB_FILE, {
            'subscribers': {}, 'resolved': {}})
        atomic_write(sr_mod.TURNIER_FILE, {
            'events': [], 'subscribers': {}, 'next_id': 1})
        ia = make_interaction(admin=True)
        run_async(cmd(ia, modus='status', kurs=0, puzzle=0, lichess=0))
        reminder_calls = [c for c in ia.followup.calls
                          if 'Test-Reminder' in (c.get('content') or '')]
        check('test-reminder: ohne Sub kein Reminder', len(reminder_calls) == 0)

    finally:
        teardown_temp_config(tmpdir)
    print()


def test_announce():
    """Tests fuer /announce Command."""
    print('[/announce]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('announce')
        check('cmd_announce gefunden', cmd is not None)
        if not cmd:
            return

        # Test: Erfolg
        target = FakeUser(uid=54321, name='Empfaenger')
        ia = make_interaction(admin=True)
        run_async(cmd(ia, user=target))
        content = ia.response.calls[0].get('content') or ''
        check('Erfolg → Bestaetigung',
              'Empfaenger' in content and '✅' in content)

        # Test: Forbidden
        class ForbiddenUser:
            id = 99
            display_name = 'Gesperrt'
            name = 'Gesperrt'
            mention = '<@99>'
            bot = False
            async def create_dm(self):
                raise _discord.Forbidden(MagicMock(), 'DMs disabled')

        ia = make_interaction(admin=True)
        run_async(cmd(ia, user=ForbiddenUser()))
        content = ia.response.calls[0].get('content') or ''
        check('Forbidden → Fehlermeldung', '❌' in content)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_greeted():
    """Tests fuer /greeted Command."""
    print('[/greeted]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('greeted')
        check('cmd_greeted gefunden', cmd is not None)
        if not cmd:
            return

        # DM_STATE_FILE patchen
        import bot as bot_mod
        old_dm_state = bot_mod.DM_STATE_FILE
        bot_mod.DM_STATE_FILE = os.path.join(tmpdir, 'dm_state.json')

        # bot-Variable in bot_mod patchen (greeted nutzt bot.fetch_user)
        old_bot = bot_mod.bot
        bot_mod.bot = _CapturingBot()

        try:
            # Test: leer
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('leer → Hinweis', 'niemand' in content)

            # Test: mit Eintraegen
            atomic_write(bot_mod.DM_STATE_FILE,
                         {'greeted': [12345, 67890]})
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            # greeted defers, dann followup.send
            check('defer aufgerufen',
                  ia.response.calls[0].get('type') == 'defer')
            check('followup.send aufgerufen', len(ia.followup.calls) > 0)
            if ia.followup.calls:
                embeds = ia.followup.calls[0].get('embeds', [])
                embed = ia.followup.calls[0].get('embed') or (embeds[0] if embeds else None)
                check('mit Eintraegen → Embed',
                      embed is not None and '2' in (embed.description or ''))
        finally:
            bot_mod.DM_STATE_FILE = old_dm_state
            bot_mod.bot = old_bot
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_stats():
    """Tests fuer /stats Command."""
    print('[/stats]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('stats')
        check('cmd_stats gefunden', cmd is not None)
        if not cmd:
            return

        # bot-Variable patchen (stats nutzt bot.fetch_user)
        import bot as bot_mod
        old_bot = bot_mod.bot
        bot_mod.bot = _CapturingBot()

        try:
            # Test: leer
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('leer → Hinweis', 'keine statistiken' in content)

            # Test: mit Daten
            import core.stats as stats_mod
            atomic_write(stats_mod.STATS_FILE, {
                '12345': {'puzzles': 10, 'downloads': 5,
                          'reaction_✅': 8, 'reaction_❌': 2},
            })
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            check('defer aufgerufen',
                  ia.response.calls[0].get('type') == 'defer')
            check('followup.send aufgerufen', len(ia.followup.calls) > 0)
            if ia.followup.calls:
                embeds = ia.followup.calls[0].get('embeds', [])
                embed = ia.followup.calls[0].get('embed') or (embeds[0] if embeds else None)
                check('mit Daten → Embed mit Stats',
                      embed is not None and embed.description is not None
                      and '10' in embed.description)
        finally:
            bot_mod.bot = old_bot
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_dm_log():
    """Tests fuer /dm-log Command."""
    print('[/dm-log]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('dm-log')
        check('cmd_dm_log gefunden', cmd is not None)
        if not cmd:
            return

        # DM_LOG_FILE patchen
        import core.dm_log as dm_log_mod
        import bot as bot_mod
        old_dm_log_file = dm_log_mod.DM_LOG_FILE
        dm_log_mod.DM_LOG_FILE = os.path.join(tmpdir, 'dm_log.json')
        old_bot = bot_mod.bot
        bot_mod.bot = _CapturingBot()

        try:
            # Test: leer
            ia = make_interaction(admin=True)
            run_async(cmd(ia, user=None))
            check('defer aufgerufen (leer)',
                  ia.response.calls[0].get('type') == 'defer')
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('leer → Hinweis', 'keine dms' in content)

            # Test: mit Eintraegen
            atomic_write(dm_log_mod.DM_LOG_FILE, {
                '12345': [
                    {'ts': '2026-04-25T18:00:00+00:00', 'text': 'Hallo!'},
                    {'ts': '2026-04-25T19:00:00+00:00', 'text': 'Puzzle gesendet'},
                ],
                '67890': [
                    {'ts': '2026-04-26T10:00:00+00:00', 'text': 'Willkommen'},
                ],
            })
            ia = make_interaction(admin=True)
            run_async(cmd(ia, user=None))
            check('defer aufgerufen (Daten)',
                  ia.response.calls[0].get('type') == 'defer')
            check('followup.send aufgerufen', len(ia.followup.calls) > 0)
            if ia.followup.calls:
                embeds = ia.followup.calls[0].get('embeds', [])
                embed = embeds[0] if embeds else None
                desc = embed.description if embed else ''
                # Uebersicht: eine Zeile pro User, kein DM-Inhalt
                check('Uebersicht enthaelt DM-Anzahl', '2 DMs' in desc)
                check('Uebersicht enthaelt Letzte', 'Letzte:' in desc)
                check('Uebersicht enthaelt KEINEN Inhalt', 'Hallo' not in desc)
        finally:
            dm_log_mod.DM_LOG_FILE = old_dm_log_file
            bot_mod.bot = old_bot
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_log():
    """Tests fuer /log Command."""
    print('[/log]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('log')
        check('cmd_log gefunden', cmd is not None)
        if not cmd:
            return

        import bot as bot_mod

        # Test: Nicht-Admin abgelehnt
        ia = make_interaction(admin=False)
        run_async(cmd(ia, zeilen=50))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('Nicht-Admin → Fehler', 'admin' in content)

        # Test: Default → Code-Block (wir patchen _read_log_tail)
        orig_read = bot_mod._read_log_tail
        bot_mod._read_log_tail = lambda n: f'Zeile 1\nZeile 2\n(n={n})'
        try:
            ia = make_interaction(admin=True)
            run_async(cmd(ia, zeilen=50))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            content = ia.followup.calls[0].get('content') or ''
            check('Default → Code-Block', '```' in content and 'Zeile 1' in content)
            check('Default → n=50', 'n=50' in content)
        finally:
            bot_mod._read_log_tail = orig_read

        # Test: Fehlende Log-Datei → (leer)
        orig_read = bot_mod._read_log_tail
        bot_mod._read_log_tail = lambda n: '(leer)'
        try:
            ia = make_interaction(admin=True)
            run_async(cmd(ia, zeilen=50))
            content = ia.followup.calls[0].get('content') or ''
            check('Fehlende Log → (leer)', '(leer)' in content)
        finally:
            bot_mod._read_log_tail = orig_read

        # Test: Lange Ausgabe → File-Attachment
        orig_read = bot_mod._read_log_tail
        bot_mod._read_log_tail = lambda n: 'X' * 2000
        try:
            ia = make_interaction(admin=True)
            run_async(cmd(ia, zeilen=200))
            call = ia.followup.calls[0]
            check('Lange Ausgabe → File', call.get('file') is not None)
        finally:
            bot_mod._read_log_tail = orig_read
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_dm_log_internals():
    """Tests fuer core/dm_log.py _describe und _append."""
    print('[dm_log internals]')
    import core.dm_log as dm_log_mod

    # --- _describe: positionaler Text ---
    check('describe pos text', dm_log_mod._describe('Hallo Welt') == 'Hallo Welt')

    # --- _describe: langer Text wird gekuerzt ---
    long_text = 'X' * 400
    result = dm_log_mod._describe(long_text)
    check('describe lang → 300+…', len(result) == 301 and result.endswith('…'))

    # --- _describe: content kwarg ---
    check('describe content kw', dm_log_mod._describe(content='Test') == 'Test')

    # --- _describe: embed ---
    from test_helpers import _discord
    embed = _discord.Embed(title='Puzzle Title', description='Beschreibung')
    result = dm_log_mod._describe(embed=embed)
    check('describe embed title', 'Puzzle Title' in result)
    check('describe embed prefix', result.startswith('[embed:'))

    # --- _describe: embed mit Beschreibung ---
    check('describe embed desc', 'Beschreibung' in result)

    # --- _describe: file ---
    check('describe file', dm_log_mod._describe(file=MagicMock()) == '[file]')

    # --- _describe: unbekannt ---
    check('describe unbekannt', dm_log_mod._describe() == '[unbekannter Inhalt]')

    # --- _append: schreibt und bereinigt alte Eintraege ---
    tmpdir = setup_temp_config()
    try:
        import os
        old_file = dm_log_mod.DM_LOG_FILE
        dm_log_mod.DM_LOG_FILE = os.path.join(tmpdir, 'dm_log.json')
        try:
            # Schreibe einen Eintrag
            dm_log_mod._append(12345, 'Test-Nachricht')

            data = atomic_read(dm_log_mod.DM_LOG_FILE)
            check('append → Eintrag vorhanden', len(data.get('12345', [])) == 1)
            check('append → text korrekt', data['12345'][0]['text'] == 'Test-Nachricht')
            check('append → ts vorhanden', 'ts' in data['12345'][0])

            # Zweiter Eintrag
            dm_log_mod._append(12345, 'Zweite Nachricht')
            data = atomic_read(dm_log_mod.DM_LOG_FILE)
            check('append → 2 Eintraege', len(data.get('12345', [])) == 2)

            # Alter Eintrag (>30 Tage) wird bereinigt
            from core.json_store import atomic_write as aw
            aw(dm_log_mod.DM_LOG_FILE, {
                '99': [{'ts': '2020-01-01T00:00:00+00:00', 'text': 'alt'}]
            })
            dm_log_mod._append(99, 'neu')
            data = atomic_read(dm_log_mod.DM_LOG_FILE)
            entries = data.get('99', [])
            check('append → alter Eintrag bereinigt',
                  len(entries) == 1 and entries[0]['text'] == 'neu')
        finally:
            dm_log_mod.DM_LOG_FILE = old_file
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_suppress_empty_fen():
    """Tests fuer core/log_setup.py _SuppressEmptyFen Filter."""
    print('[SuppressEmptyFen]')
    from core.log_setup import _SuppressEmptyFen
    import io as _io

    buf = _io.StringIO()
    filtered = _SuppressEmptyFen(buf)

    # Normaler Text passiert durch
    filtered.write('Hallo Welt')
    check('normaler Text durchgelassen', buf.getvalue() == 'Hallo Welt')

    # Unterdrueckte Muster
    buf.truncate(0)
    buf.seek(0)
    filtered.write('empty fen while parsing something')
    check('empty fen unterdrueckt', buf.getvalue() == '')

    buf.truncate(0)
    buf.seek(0)
    filtered.write('illegal san: Nf3')
    check('illegal san unterdrueckt', buf.getvalue() == '')

    buf.truncate(0)
    buf.seek(0)
    filtered.write('invalid san: e4')
    check('invalid san unterdrueckt', buf.getvalue() == '')

    buf.truncate(0)
    buf.seek(0)
    filtered.write('no matching legal move found')
    check('no matching legal move unterdrueckt', buf.getvalue() == '')

    buf.truncate(0)
    buf.seek(0)
    filtered.write('ambiguous san: Nc3')
    check('ambiguous san unterdrueckt', buf.getvalue() == '')

    # flush delegiert
    filtered.flush()
    check('flush funktioniert', True)

    # __getattr__ delegiert
    check('getattr delegiert', filtered.closed == buf.closed)

    print()



    """Tests dass Admin-Commands von Nicht-Admins abgelehnt werden."""
    print('[Admin-Enforcement]')

    # /puzzle user:@X als Nicht-Admin
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
            other_user = FakeMember(admin=False)
            other_user.id = 999
            other_user.mention = '<@999>'
            ia = make_interaction(admin=False)
            ia.user.id = 111
            run_async(cmd(ia, anzahl=1, buch=0, id=None, user=other_user))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('/puzzle user:@X non-admin → Fehler', 'admin' in content)
        else:
            check('/puzzle user:@X non-admin → Fehler', False, 'cmd nicht gefunden')
    finally:
        teardown_temp_config(tmpdir)

    # /blind Validierungen (anzahl, buch)
    cmd = _captured_commands.get('blind')
    if cmd:
        tmpdir = setup_temp_config()
        try:
            ia = make_interaction()
            run_async(cmd(ia, moves=4, anzahl=25, buch=0, user=None))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('/blind anzahl > 20 → Fehler', 'zwischen 1 und 20' in content)

            ia = make_interaction()
            run_async(cmd(ia, moves=4, anzahl=1, buch=-1, user=None))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('/blind buch:-1 → Fehler', 'negativ' in content)
        finally:
            teardown_temp_config(tmpdir)
    else:
        check('/blind Validierungen', False, 'cmd nicht gefunden')

    # /reminder buch:-1 → Fehler
    cmd = _captured_commands.get('reminder')
    if cmd:
        tmpdir = setup_temp_config()
        try:
            ia = make_interaction()
            run_async(cmd(ia, hours=4, puzzle_count=1, buch=-1))
            content = (ia.response.calls[0].get('content') or '').lower()
            check('/reminder buch:-1 → Fehler', 'negativ' in content)
        finally:
            teardown_temp_config(tmpdir)
    else:
        check('/reminder buch:-1', False, 'cmd nicht gefunden')

    # Moderator-Rolle wird wie Admin behandelt
    from core.permissions import is_privileged
    mod_user = FakeMember(admin=False, roles=[FakeRole('Moderator')])
    mod_ia = make_interaction(user=mod_user)
    check('Moderator → is_privileged', is_privileged(mod_ia))

    # Normaler User ohne Mod/Admin → kein Zugriff
    normal_user = FakeMember(admin=False, roles=[FakeRole('member')])
    normal_ia = make_interaction(user=normal_user)
    check('normaler User → nicht privileged', not is_privileged(normal_ia))

    # Admin ohne Mod-Rolle → weiterhin Zugriff
    admin_user = FakeMember(admin=True, roles=[])
    admin_ia = make_interaction(user=admin_user)
    check('Admin → is_privileged', is_privileged(admin_ia))
    print()
