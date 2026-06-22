"""Tests fuer /motivation + den stats-basierten Motivations-DM-Builder."""

from datetime import datetime, timedelta, timezone

import test_helpers as h
from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    make_interaction, _captured_commands, atomic_read, FakeUser,
)
import commands.motivation as mot


def _progress(puzzle_min=0, puzzle_done_min=0, book_min=0, book_done_min=0,
              play_games_target=0, play_games_done=0, elo=1500, streak=0):
    """Baut ein BotPlayerProgressDto-aehnliches dict (camelCase wie die API)."""
    def cat(target, done_min):
        return {'targetMinutes': target, 'doneSeconds': done_min * 60,
                'met': target > 0 and done_min >= target}
    return {
        'username': 'tester', 'displayName': 'Tester',
        'today': {
            'goal': {'puzzleMinutes': puzzle_min, 'bookMinutes': book_min,
                     'playGames': play_games_target, 'weeklyDaysTarget': 0,
                     'source': 'personal'},
            'puzzles': cat(puzzle_min, puzzle_done_min),
            'book': cat(book_min, book_done_min),
            'play': {'targetGames': play_games_target, 'doneGames': play_games_done,
                     'met': play_games_target > 0 and play_games_done >= play_games_target},
            'status': 'partial', 'weekDaysMet': 0, 'weeklyDaysTarget': 0,
        },
        'puzzles': {'totalAttempts': 10, 'solved': 8, 'accuracy': 0.8,
                    'currentStreak': streak, 'bestStreak': 5, 'puzzleElo': elo},
    }


def _patch_progress(value):
    """Patcht rookhub.get_player_progress (Callable(uid)->value) und gibt den Restore-Wert zurueck."""
    orig = mot.rookhub.get_player_progress
    mot.rookhub.get_player_progress = (value if callable(value) else (lambda uid: value))
    return orig


def test_motivation_command():
    """Tests fuer /motivation an|aus|status."""
    print('[/motivation]')
    tmpdir = setup_temp_config()
    orig = mot.rookhub.get_player_progress
    try:
        cmd = _captured_commands.get('motivation')
        check('cmd_motivation gefunden', cmd is not None)
        if not cmd:
            return

        # 1) status ohne Abo
        ia = make_interaction()
        run_async(cmd(ia, aktion='status'))
        c = (ia.response.calls[0].get('content') or '')
        check('status ohne Abo → Hinweis', '/motivation an' in c)

        # 2) an OHNE Verknuepfung → trotzdem Abo + Verknuepfungs-Hinweis (neue Regel)
        _patch_progress(None)
        ia = make_interaction()
        run_async(cmd(ia, aktion='an', zeit='18'))
        c = (ia.response.calls[0].get('content') or '')
        check('an ohne Verknuepfung → abonniert', 'abonniert' in c)
        check('an ohne Verknuepfung → Verknuepfungs-Hinweis', 'verknuepf' in c.lower())
        sub = atomic_read(mot.MOTIVATION_SUB_FILE, default=dict)
        check('an ohne Verknuepfung → Abo trotzdem da', str(ia.user.id) in sub.get('subscribers', {}))

        # 3) an MIT Verknuepfung → Abo aktualisiert + persoenlicher Hinweis
        _patch_progress(_progress(puzzle_min=10))
        ia = make_interaction()
        run_async(cmd(ia, aktion='an', zeit='17:30'))
        c = (ia.response.calls[0].get('content') or '')
        check('an mit Verknuepfung → Bestaetigung', ('abonniert' in c or 'aktualisiert' in c) and '17:30' in c)
        check('an mit Verknuepfung → persoenlich', 'persoenlich' in c.lower())
        sub = atomic_read(mot.MOTIVATION_SUB_FILE, default=dict)
        uid = str(ia.user.id)
        check('Abo gespeichert', uid in sub.get('subscribers', {}))
        check('Abo-Zeit korrekt', sub['subscribers'][uid]['hour'] == 17
              and sub['subscribers'][uid]['minute'] == 30)

        # 4) status MIT Abo
        ia = make_interaction()
        run_async(cmd(ia, aktion='status'))
        c = (ia.response.calls[0].get('content') or '')
        check('status mit Abo → aktiv', 'aktiv' in c and '17:30' in c)

        # 5) ungueltige Zeit
        ia = make_interaction()
        run_async(cmd(ia, aktion='an', zeit='99'))
        c = (ia.response.calls[0].get('content') or '').lower()
        check('an ungueltige Zeit → Hinweis', 'ungueltig' in c or 'ungültig' in c)

        # 6) aus → Abo entfernt
        ia = make_interaction()
        run_async(cmd(ia, aktion='aus'))
        c = (ia.response.calls[0].get('content') or '')
        check('aus → Bestaetigung', 'abbestellt' in c)
        sub = atomic_read(mot.MOTIVATION_SUB_FILE, default=dict)
        check('Abo entfernt', uid not in sub.get('subscribers', {}))

        # --- Admin-Funktionen ---
        target = FakeUser(uid=777, name='Ziel')

        # 7) Nicht-Admin mit user → abgelehnt
        ia = make_interaction(admin=False)
        run_async(cmd(ia, aktion='an', user=target))
        c = (ia.response.calls[0].get('content') or '').lower()
        check('Nicht-Admin + user → abgelehnt', 'nur admin' in c)
        sub = atomic_read(mot.MOTIVATION_SUB_FILE, default=dict)
        check('Nicht-Admin → kein Fremd-Abo', '777' not in sub.get('subscribers', {}))

        # 8) Admin abonniert anderen User (unverknuepft) → Abo + Hinweis
        _patch_progress(None)
        ia = make_interaction(admin=True)
        run_async(cmd(ia, aktion='an', zeit='9', user=target))
        c = (ia.response.calls[0].get('content') or '')
        check('Admin an user → Bestaetigung mit Namen', 'Ziel' in c and 'abonniert' in c)
        sub = atomic_read(mot.MOTIVATION_SUB_FILE, default=dict)
        check('Fremd-Abo gespeichert', '777' in sub.get('subscribers', {}))

        # 9) Admin status ohne user → Liste aller Abos
        ia = make_interaction(admin=True)
        run_async(cmd(ia, aktion='status'))
        c = (ia.response.calls[0].get('content') or '')
        check('Admin status → Liste mit Anzahl', '1 aktive' in c)

        # 10) Admin status mit user → dessen Status
        ia = make_interaction(admin=True)
        run_async(cmd(ia, aktion='status', user=target))
        c = (ia.response.calls[0].get('content') or '')
        check('Admin status user → Ziel aktiv', 'Ziel' in c and 'aktiv' in c)

        # 11) Admin aus user → Fremd-Abo entfernt
        ia = make_interaction(admin=True)
        run_async(cmd(ia, aktion='aus', user=target))
        sub = atomic_read(mot.MOTIVATION_SUB_FILE, default=dict)
        check('Admin aus user → Fremd-Abo entfernt', '777' not in sub.get('subscribers', {}))

        # 12) /motivation_send → DM sofort senden (ohne zeit → KEIN Abo)
        send_cmd = _captured_commands.get('motivation_send')
        check('cmd_motivation_send gefunden', send_cmd is not None)
        if send_cmd:
            _patch_progress(None)   # unverknuepft → allgemeine Motivation + CTA
            ia = make_interaction(admin=True)
            run_async(send_cmd(ia, user=target))
            fu = (ia.followup.calls[0].get('content') or '') if ia.followup.calls else ''
            check('send → Bestaetigung (DM ohne Fehler gesendet)', 'gesendet' in fu)
            sub = atomic_read(mot.MOTIVATION_SUB_FILE, default=dict)
            check('send ohne zeit → kein Abo', '777' not in sub.get('subscribers', {}))

            # 13) /motivation_send mit zeit → DM + Abo zur Uhrzeit
            ia = make_interaction(admin=True)
            run_async(send_cmd(ia, user=target, zeit='8:15'))
            fu = (ia.followup.calls[0].get('content') or '') if ia.followup.calls else ''
            check('send mit zeit → abonniert-Hinweis', 'abonniert' in fu and '8:15' in fu)
            sub = atomic_read(mot.MOTIVATION_SUB_FILE, default=dict)
            check('send mit zeit → Abo angelegt', '777' in sub.get('subscribers', {}))
            if '777' in sub.get('subscribers', {}):
                check('send mit zeit → Uhrzeit korrekt',
                      sub['subscribers']['777']['hour'] == 8 and sub['subscribers']['777']['minute'] == 15)

            # 14) /motivation_send mit ungueltiger zeit → Fehler, kein Versand/Abo
            ia = make_interaction(admin=True)
            run_async(send_cmd(ia, user=FakeUser(uid=888, name='Z2'), zeit='99'))
            resp = (ia.response.calls[0].get('content') or '') if ia.response.calls else ''
            check('send ungueltige zeit → Fehler', 'ungueltig' in resp.lower() or 'ungültig' in resp.lower())
            sub = atomic_read(mot.MOTIVATION_SUB_FILE, default=dict)
            check('send ungueltige zeit → kein Abo', '888' not in sub.get('subscribers', {}))

    finally:
        mot.rookhub.get_player_progress = orig
        teardown_temp_config(tmpdir)
    print()


def test_motivation_builder():
    """Tests fuer _build_motivation_text + _analyze_progress (Ton je nach Fortschritt)."""
    print('[motivation builder]')
    tmpdir = setup_temp_config()
    try:
        # --- _analyze_progress ---
        cats, has_goal, all_met = mot._analyze_progress(
            _progress(puzzle_min=10, puzzle_done_min=12))
        check('analyze: Ziel erkannt', has_goal)
        check('analyze: erfuelltes Tagesziel → all_met', all_met)

        cats, has_goal, all_met = mot._analyze_progress(
            _progress(puzzle_min=10, puzzle_done_min=3))
        check('analyze: offenes Ziel → nicht all_met', has_goal and not all_met)

        cats, has_goal, all_met = mot._analyze_progress(_progress())
        check('analyze: kein Ziel → has_goal False', not has_goal and not all_met)

        # --- Builder (kein Claude-Client in Tests → Fallback-Template) ---
        # a) alle Ziele erfuellt → Lob, KEIN Daily-Link (kein "mach mehr")
        text = run_async(mot._build_motivation_text(
            42, _progress(puzzle_min=10, puzzle_done_min=15)))
        check('Lob-Text vorhanden', isinstance(text, str) and len(text) > 0)
        check('Lob → kein "Heutiges Puzzle"-Link', 'Heutiges Puzzle' not in text)
        check('Lob → erreicht erwaehnt', 'erreicht' in text.lower())

        # b) offenes Ziel → Nudge mit konkretem Rueckstand
        text = run_async(mot._build_motivation_text(
            42, _progress(puzzle_min=10, puzzle_done_min=2,
                          play_games_target=3, play_games_done=1)))
        check('Nudge → Puzzle-Rueckstand', 'Puzzle' in text)
        check('Nudge → Spielen-Rueckstand', 'Spielen' in text)

        # c) NICHT verknuepft → allgemeine Motivation + Registrier-/Verknuepfungs-CTA
        unlinked = run_async(mot._build_unlinked_text(FakeUser(uid=55, name='Neu')))
        check('Unlinked-Text vorhanden', isinstance(unlinked, str) and len(unlinked) > 0)
        check('Unlinked → Verknuepfungs-/Registrier-Hinweis',
              'link' in unlinked.lower() or 'registr' in unlinked.lower())

    finally:
        teardown_temp_config(tmpdir)
    print()


def test_motivation_tournaments():
    """Turnier-Block: _fmt_points/_days_phrase/_tournament_facts + Einbindung in _build_motivation_text."""
    print('[motivation tournaments]')
    tmpdir = setup_temp_config()
    try:
        check('fmt 2.5 -> 2,5', mot._fmt_points(2.5) == '2,5')
        check('fmt 3.0 -> 3', mot._fmt_points(3.0) == '3')
        check('days 0 -> heute', mot._days_phrase(0) == 'heute')
        check('days 1 -> morgen', mot._days_phrase(1) == 'morgen')
        check('days 4 -> in 4 Tagen', mot._days_phrase(4) == 'in 4 Tagen')

        prog = _progress(puzzle_min=10, puzzle_done_min=2)
        prog['tournaments'] = [
            {'name': 'Stadt-Open', 'status': 'upcoming', 'daysUntil': 3, 'location': 'Wien'},
            {'name': 'Vereinsmeisterschaft', 'status': 'finished', 'daysUntil': -1,
             'resultPoints': 4.5, 'resultGames': 7},
        ]
        cats, has_goal, _ = mot._analyze_progress(prog)
        facts = mot._facts_summary(prog, cats, has_goal)
        check('facts → anstehendes Turnier', 'Stadt-Open' in facts and 'in 3 Tagen' in facts)
        check('facts → Ergebnis 4,5 aus 7', '4,5 aus 7 Partien' in facts)

        # Builder ohne Claude → Fallback zieht die zeitnaechste Turnier-Notiz mit rein.
        text = run_async(mot._build_motivation_text(7, prog))
        check('builder fallback → Turnier erwaehnt', 'Stadt-Open' in text)

        # Keine Turniere → kein Turnier-Rauschen im Fallback.
        plain = run_async(mot._build_motivation_text(7, _progress(puzzle_min=10, puzzle_done_min=2)))
        check('keine Turniere → keine Turnier-Zeile', 'Turnier' not in plain)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_motivation_random_spruch():
    """random_spruch (aus core.sprueche, vom Motivations-Builder genutzt) liefert formatierte Sprueche."""
    print('[motivation spruch]')
    import core.sprueche as sp
    old = sp._sprueche_cache
    try:
        sp._sprueche_cache = []
        check('spruch leer → leerer String', mot._random_spruch() == '')

        sp._sprueche_cache = [{'text': 'Testspruch', 'autor': 'TestAutor'}]
        r = mot._random_spruch()
        check('spruch mit Autor → _" enthalten', '_"' in r and 'TestAutor' in r)

        sp._sprueche_cache = [{'text': 'NurText', 'autor': None}]
        r = mot._random_spruch()
        check('spruch ohne Autor → kein —', '_"' in r and '—' not in r)
    finally:
        sp._sprueche_cache = old
    print()


def test_parse_zeit():
    """parse_zeit (aus core.datetime_utils, vom /motivation-Command genutzt)."""
    print('[parse_zeit]')
    pz = mot._parse_zeit
    check('parse "17" → (17,0)', pz('17') == (17, 0))
    check('parse "1730" → (17,30)', pz('1730') == (17, 30))
    check('parse "17:30" → (17,30)', pz('17:30') == (17, 30))
    check('parse "17 30" → (17,30)', pz('17 30') == (17, 30))
    check('parse "25" → None', pz('25') is None)
    check('parse "" → None', pz('') is None)
    check('parse "abc" → None', pz('abc') is None)
    print()


# ---------------------------------------------------------------------------
# Helpers fuer Activity-Watch-Tests
# ---------------------------------------------------------------------------

class _FakeActivityType:
    playing = 'playing'


class _FakeActivity:
    def __init__(self, name, act_type='playing', start=None):
        self.name = name
        self.type = act_type
        self.start = start


class _FakeMember:
    def __init__(self, activities=()):
        self.activities = activities
        self.display_name = 'Tester'
        self.id = 42
        self.name = 'tester'


def test_activity_watcher():
    """Tests fuer _get_current_game und _check_activities."""
    print('[activity watcher]')
    tmpdir = setup_temp_config()

    # Patch discord.ActivityType.playing im Modul
    import discord as _discord_mod
    orig_at = getattr(_discord_mod, 'ActivityType', None)
    _discord_mod.ActivityType = _FakeActivityType()

    orig_progress = mot.rookhub.get_player_progress

    try:
        # --- _get_current_game ---

        # 1) kein Member → None
        check('get_game None member → None', mot._get_current_game(None) is None)

        # 2) Member ohne Aktivitaeten → None
        check('get_game keine Aktivitaet → None',
              mot._get_current_game(_FakeMember()) is None)

        # 3) Nicht-playing-Typ → None
        m = _FakeMember([_FakeActivity('Spotify', 'listening')])
        check('get_game listening → None', mot._get_current_game(m) is None)

        # 4) playing-Spiel ohne Discord-Start → (Name, None)
        m = _FakeMember([_FakeActivity('Valorant', 'playing')])
        check('get_game Valorant → ("Valorant", None)', mot._get_current_game(m) == ('Valorant', None))

        # 4b) playing-Spiel mit Discord-Start → (Name, start)
        fake_start = datetime.now(timezone.utc) - timedelta(minutes=90)
        m = _FakeMember([_FakeActivity('Valorant', 'playing', start=fake_start)])
        result = mot._get_current_game(m)
        check('get_game mit Discord-Start → Name korrekt', result is not None and result[0] == 'Valorant')
        check('get_game mit Discord-Start → Start-Zeit korrekt', result is not None and result[1] == fake_start)

        # 5) Schach-Spiel wird ignoriert
        m = _FakeMember([_FakeActivity('Chess.com', 'playing')])
        check('get_game chess.com → None', mot._get_current_game(m) is None)

        # 6) playing mit leerem Namen → None
        m = _FakeMember([_FakeActivity('', 'playing')])
        check('get_game leerer Name → None', mot._get_current_game(m) is None)

        # --- _check_activities (End-to-End mit gemocktem Bot) ---

        # Mock-Bot mit Guild-Member aufsetzen
        import unittest.mock as mock
        fake_uid = 42
        fake_member = _FakeMember([_FakeActivity('Valorant', 'playing')])
        fake_guild = mock.MagicMock()
        fake_guild.get_member = lambda uid: fake_member if uid == fake_uid else None
        fake_bot = mock.MagicMock()
        fake_bot.get_guild.return_value = fake_guild
        fake_bot.guilds = [fake_guild]

        from core import permissions as perm
        orig_guild_id = perm._guild_id
        perm._guild_id = 99  # irgendeine Guild-ID

        orig_bot = mot._bot
        mot._bot = fake_bot

        # Abo anlegen
        from core.json_store import atomic_write
        atomic_write(mot.MOTIVATION_SUB_FILE, {
            'subscribers': {str(fake_uid): {'hour': 18, 'minute': 0, 'next': '2099-01-01T00:00:00+00:00'}}
        })

        # 7) Neues Spiel → Watch-State wird angelegt, keine DM (< 60 min)
        mot.rookhub.get_player_progress = lambda uid: _progress(puzzle_min=10, puzzle_done_min=0)
        run_async(mot._check_activities())
        from core.json_store import atomic_read
        watch = atomic_read(mot.ACTIVITY_WATCH_FILE, default=dict)
        state = watch.get('watching', {}).get(str(fake_uid), {})
        check('neues Spiel → Watch-State angelegt', state.get('name') == 'Valorant')
        check('neues Spiel → dm_sent=False', state.get('dm_sent') is False)

        # 7b) Discord-Start-Timestamp wird als since uebernommen
        discord_start = datetime.now(timezone.utc) - timedelta(minutes=90)
        fake_member.activities = [_FakeActivity('Valorant', 'playing', start=discord_start)]
        # Watch-State loeschen damit neues Tracking beginnt
        from core.json_store import atomic_write as _aw
        _aw(mot.ACTIVITY_WATCH_FILE, {'watching': {}})
        run_async(mot._check_activities())
        watch_b = atomic_read(mot.ACTIVITY_WATCH_FILE, default=dict)
        state_b = watch_b.get('watching', {}).get(str(fake_uid), {})
        stored_since = state_b.get('since', '')
        check('Discord-Start → since entspricht act.start',
              stored_since == discord_start.isoformat())
        # Activity ohne Start zuruecksetzen fuer folgende Tests
        fake_member.activities = [_FakeActivity('Valorant', 'playing')]

        # 8) Noch keine Stunde → keine DM
        state['since'] = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        state['dm_sent'] = False
        atomic_write(mot.ACTIVITY_WATCH_FILE, {'watching': {str(fake_uid): state}})
        sent_dms = []
        async def _fake_send(text):
            sent_dms.append(text)
        fake_dm = mock.MagicMock()
        fake_dm.send = _fake_send
        fake_member.create_dm = mock.AsyncMock(return_value=fake_dm)
        run_async(mot._check_activities())
        check('<60 min → keine DM gesendet', len(sent_dms) == 0)

        # 9) Ueber eine Stunde, Ziele offen → DM wird gesendet
        state['since'] = (datetime.now(timezone.utc) - timedelta(minutes=75)).isoformat()
        state['dm_sent'] = False
        atomic_write(mot.ACTIVITY_WATCH_FILE, {'watching': {str(fake_uid): state}})
        sent_dms.clear()
        run_async(mot._check_activities())
        check('>60 min + offene Ziele → DM gesendet', len(sent_dms) == 1)
        check('DM enthaelt Spielname', 'Valorant' in (sent_dms[0] if sent_dms else ''))
        watch2 = atomic_read(mot.ACTIVITY_WATCH_FILE, default=dict)
        dm_sent_val = watch2.get('watching', {}).get(str(fake_uid), {}).get('dm_sent')
        check('dm_sent nach Versand = Timestamp', isinstance(dm_sent_val, str) and 'T' in dm_sent_val)

        # 10) DM gerade erst gesendet → kein Duplikat (< 3h)
        sent_dms.clear()
        run_async(mot._check_activities())
        check('dm_sent < 3h → kein Duplikat', len(sent_dms) == 0)

        # 10b) DM vor > 3h gesendet → erneut senden
        state_r = watch2.get('watching', {}).get(str(fake_uid), {})
        state_r['dm_sent'] = (datetime.now(timezone.utc) - timedelta(hours=3, minutes=5)).isoformat()
        state_r['since'] = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        atomic_write(mot.ACTIVITY_WATCH_FILE, {'watching': {str(fake_uid): state_r}})
        sent_dms.clear()
        mot.rookhub.get_player_progress = lambda uid: _progress(puzzle_min=10, puzzle_done_min=0)
        run_async(mot._check_activities())
        check('dm_sent > 3h → erneut gesendet', len(sent_dms) == 1)

        # 11) Alle Ziele erfuellt → keine DM
        mot.rookhub.get_player_progress = lambda uid: _progress(puzzle_min=10, puzzle_done_min=15)
        state2 = {'name': 'CS2', 'since': (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat(), 'dm_sent': False}
        atomic_write(mot.ACTIVITY_WATCH_FILE, {'watching': {str(fake_uid): state2}})
        sent_dms.clear()
        run_async(mot._check_activities())
        check('Ziele erfuellt → keine Slacker-DM', len(sent_dms) == 0)

        # 12) Nicht verknuepft → DM mit Registrierungs-CTA
        mot.rookhub.get_player_progress = lambda uid: None
        # Gleiche Aktivitaet wie member (Valorant), >60 min
        state3 = {'name': 'Valorant', 'since': (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat(), 'dm_sent': False}
        atomic_write(mot.ACTIVITY_WATCH_FILE, {'watching': {str(fake_uid): state3}})
        sent_dms.clear()
        run_async(mot._check_activities())
        check('nicht verknuepft + >60min → DM gesendet', len(sent_dms) == 1)
        dm_text = sent_dms[0] if sent_dms else ''
        check('nicht verknuepft DM → Spielname enthalten', 'Valorant' in dm_text)
        check('nicht verknuepft DM → Registrier-CTA enthalten',
              'registr' in dm_text.lower() or 'rookhub' in dm_text.lower() or 'link' in dm_text.lower())

        # 13) Kein Spiel aktiv → Watch-State wird geloescht
        fake_member.activities = []
        atomic_write(mot.ACTIVITY_WATCH_FILE, {'watching': {str(fake_uid): state3}})
        run_async(mot._check_activities())
        watch3 = atomic_read(mot.ACTIVITY_WATCH_FILE, default=dict)
        check('kein Spiel → Watch-State leer',
              str(fake_uid) not in watch3.get('watching', {}))

    finally:
        mot.rookhub.get_player_progress = orig_progress
        mot._bot = orig_bot
        perm._guild_id = orig_guild_id
        if orig_at is not None:
            _discord_mod.ActivityType = orig_at
        teardown_temp_config(tmpdir)
    print()


def test_motivation_dm_retry():
    """_run_motivation_dms: Retry-/Erreichbarkeits-Logik (kein endloser Stunden-Retry)."""
    print('[motivation dm-retry]')
    import unittest.mock as mock
    from core.json_store import atomic_write
    tmpdir = setup_temp_config()
    orig_send = mot._send_motivation_to
    orig_bot = mot._bot
    try:
        mot._bot = mock.MagicMock()
        uid = '777'
        now = datetime.now(timezone.utc)

        def _set_sub(**extra):
            info = {'hour': 18, 'minute': 0, 'next': '2000-01-01T00:00:00+00:00'}
            info.update(extra)
            atomic_write(mot.MOTIVATION_SUB_FILE, {'subscribers': {uid: info}})

        def _get_info():
            d = atomic_read(mot.MOTIVATION_SUB_FILE, default=dict)
            return d.get('subscribers', {}).get(uid)

        class _FakeResp:
            status = 403
            reason = 'Forbidden'

        # A) Erfolg → naechster Termin morgen, Zaehler zurueckgesetzt
        mot._send_motivation_to = mock.AsyncMock(return_value=True)
        _set_sub(retries=2, unreachable=1)
        run_async(mot._run_motivation_dms())
        info = _get_info()
        check('Erfolg → next ~morgen (>12h)',
              mot._parse_utc(info['next']) - now > timedelta(hours=12))
        check('Erfolg → retries=0', info.get('retries', 0) == 0)
        check('Erfolg → unreachable=0', info.get('unreachable', 0) == 0)

        # B) transienter Fehler → Retry in ~60min, retries hochgezaehlt
        async def _boom(uid_int, user_obj=None):
            raise RuntimeError('boom')
        mot._send_motivation_to = _boom
        _set_sub()
        run_async(mot._run_motivation_dms())
        info = _get_info()
        delta = mot._parse_utc(info['next']) - now
        check('transient → next ~+60min (<2h)', timedelta(minutes=30) < delta < timedelta(hours=2))
        check('transient → retries=1', info.get('retries') == 1)

        # C) transient am Limit → erst morgen wieder, retries zurueckgesetzt
        _set_sub(retries=mot._MAX_TRANSIENT_RETRIES - 1)
        run_async(mot._run_motivation_dms())
        info = _get_info()
        check('transient Cap → next ~morgen (>12h)',
              mot._parse_utc(info['next']) - now > timedelta(hours=12))
        check('transient Cap → retries zurueckgesetzt', info.get('retries') == 0)

        # D) Forbidden (DMs gesperrt) → KEIN 60-min-Retry, sondern morgen; unreachable hoch
        async def _forbidden(uid_int, user_obj=None):
            raise mot.discord.Forbidden(_FakeResp(), 'blocked')
        mot._send_motivation_to = _forbidden
        _set_sub()
        run_async(mot._run_motivation_dms())
        info = _get_info()
        check('Forbidden → next ~morgen (kein Stunden-Retry)',
              mot._parse_utc(info['next']) - now > timedelta(hours=12))
        check('Forbidden → unreachable=1', info.get('unreachable') == 1)

        # E) Forbidden am Erreichbarkeits-Limit → Abo wird automatisch entfernt
        _set_sub(unreachable=mot._MAX_UNREACHABLE_DAYS - 1)
        run_async(mot._run_motivation_dms())
        check('Forbidden am Limit → Abo automatisch beendet', _get_info() is None)
    finally:
        mot._send_motivation_to = orig_send
        mot._bot = orig_bot
        teardown_temp_config(tmpdir)
    print()


def test_slacker_text():
    """_build_slacker_text/_build_slacker_unlinked_text (Fallback, kein Claude)."""
    print('[slacker text]')
    cats = [('Puzzle', 3, 10, False, 'min'), ('Spielen', 1, 3, False, 'Partien diese Woche')]
    text = run_async(mot._build_slacker_text('Valorant', cats, 75))
    check('slacker text → Spielname enthalten', 'Valorant' in text)
    check('slacker text → Puzzle-Rueckstand', 'Puzzle' in text)
    check('slacker text → Spielen-Rueckstand', 'Spielen' in text)

    user = FakeUser(uid=99, name='test')
    utext = run_async(mot._build_slacker_unlinked_text('Minecraft', 42, user))
    check('unlinked slacker → Spielname enthalten', 'Minecraft' in utext)
    check('unlinked slacker → Registrier-CTA enthalten',
          'registr' in utext.lower() or 'rookhub' in utext.lower() or 'link' in utext.lower())
    print()
