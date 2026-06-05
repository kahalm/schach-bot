"""Tests fuer /motivation + den stats-basierten Motivations-DM-Builder."""

import test_helpers as h
from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    make_interaction, _captured_commands, atomic_read,
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

        # 2) an OHNE Verknuepfung → Link-Hinweis, KEIN Abo
        _patch_progress(None)
        ia = make_interaction()
        run_async(cmd(ia, aktion='an', zeit='18'))
        c = (ia.response.calls[0].get('content') or '').lower()
        check('an ohne Verknuepfung → Hinweis', 'verkn' in c or '/link' in c)
        sub = atomic_read(mot.MOTIVATION_SUB_FILE, default=dict)
        check('an ohne Verknuepfung → kein Abo', not sub.get('subscribers'))

        # 3) an MIT Verknuepfung → Abo angelegt
        _patch_progress(_progress(puzzle_min=10))
        ia = make_interaction()
        run_async(cmd(ia, aktion='an', zeit='17:30'))
        c = (ia.response.calls[0].get('content') or '')
        check('an mit Verknuepfung → Bestaetigung', 'abonniert' in c and '17:30' in c)
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

    finally:
        teardown_temp_config(tmpdir)
    print()


def test_motivation_random_spruch():
    """_random_spruch (aus wochenpost wiederverwendet) liefert formatierte Sprueche."""
    print('[motivation spruch]')
    import commands.wochenpost as wp
    old = wp._sprueche_cache
    try:
        wp._sprueche_cache = []
        check('spruch leer → leerer String', mot._random_spruch() == '')

        wp._sprueche_cache = [{'text': 'Testspruch', 'autor': 'TestAutor'}]
        r = mot._random_spruch()
        check('spruch mit Autor → _" enthalten', '_"' in r and 'TestAutor' in r)

        wp._sprueche_cache = [{'text': 'NurText', 'autor': None}]
        r = mot._random_spruch()
        check('spruch ohne Autor → kein —', '_"' in r and '—' not in r)
    finally:
        wp._sprueche_cache = old
    print()
