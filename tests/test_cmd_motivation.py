"""Tests fuer /motivation + den stats-basierten Motivations-DM-Builder."""

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
