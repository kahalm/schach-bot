"""Tests fuer Community Commands: /elo, /resourcen, /youtube, /reminder, /wanted."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock

import test_helpers as h
from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    make_interaction, _captured_commands, FakeMember,
    atomic_write, atomic_read,
)


def test_elo():
    """Tests fuer /elo Command."""
    print('[/elo]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('elo')
        check('cmd_elo gefunden', cmd is not None)
        if not cmd:
            return

        # Test: ohne Wert, keine Historie
        ia = make_interaction()
        run_async(cmd(ia, wert=None))
        check('keine Elo → Hinweis',
              'noch keine elo' in (ia.response.calls[0].get('content') or '').lower())

        # Test: Wert setzen
        ia = make_interaction()
        run_async(cmd(ia, wert=1500))
        check('Elo setzen → Bestaetigung',
              '1500' in (ia.response.calls[0].get('content') or ''))

        # Test: Wert anzeigen (nach setzen)
        ia = make_interaction()
        run_async(cmd(ia, wert=None))
        check('Elo anzeigen → aktuelle Elo',
              '1500' in (ia.response.calls[0].get('content') or ''))

        # Test: Historie (zweiten Wert setzen)
        ia = make_interaction()
        run_async(cmd(ia, wert=1600))
        ia = make_interaction()
        run_async(cmd(ia, wert=None))
        check('Elo Historie → zeigt Historie',
              'Historie' in (ia.response.calls[0].get('content') or ''))

        # Test: Validierung < 100
        ia = make_interaction()
        run_async(cmd(ia, wert=50))
        check('Elo < 100 → Fehler',
              '100' in (ia.response.calls[0].get('content') or '') and
              '3500' in (ia.response.calls[0].get('content') or ''))

        # Test: Validierung > 3500
        ia = make_interaction()
        run_async(cmd(ia, wert=4000))
        check('Elo > 3500 → Fehler',
              '100' in (ia.response.calls[0].get('content') or '') and
              '3500' in (ia.response.calls[0].get('content') or ''))
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_resourcen():
    """Tests fuer /resourcen Command."""
    print('[/resourcen]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('resourcen')
        check('cmd_resourcen gefunden', cmd is not None)
        if not cmd:
            return

        # Test: Liste leer
        ia = make_interaction()
        run_async(cmd(ia, url=None, beschreibung=None))
        check('leere Liste → Hinweis',
              'keine Ressourcen' in (ia.response.calls[0].get('content') or '').lower()
              or 'keine ressourcen' in (ia.response.calls[0].get('content') or '').lower())

        # Test: hinzufuegen ohne Beschreibung
        ia = make_interaction()
        run_async(cmd(ia, url='https://example.com', beschreibung=None))
        check('ohne Beschreibung → Warnung',
              'beschreibung' in (ia.response.calls[0].get('content') or '').lower())

        # Test: hinzufuegen mit Beschreibung
        ia = make_interaction()
        run_async(cmd(ia, url='https://example.com', beschreibung='Test-Ressource'))
        check('hinzufuegen → Bestaetigung',
              'Test-Ressource' in (ia.response.calls[0].get('content') or ''))

        # Test: Liste mit Eintrag
        ia = make_interaction()
        run_async(cmd(ia, url=None, beschreibung=None))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('Liste → Embed mit Eintrag',
              embed is not None and len(embed.fields) > 0)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_collection_limits():
    """Tests fuer _collection.py _MAX_ENTRIES Limit."""
    print('[collection_limits]')
    import commands._collection as col

    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('resourcen')
        if not cmd:
            check('cmd_resourcen fuer limits', False, 'cmd nicht gefunden')
            return

        # Pre-fill mit 100 Eintraegen
        json_file = col._json_path('resourcen.json')
        prefill = [{'url': f'https://example.com/{i}',
                     'beschreibung': f'res{i}',
                     'user': 'Test', 'datum': '2025-01-01'}
                    for i in range(100)]
        atomic_write(json_file, prefill)

        # 101. Eintrag muss abgelehnt werden
        ia = make_interaction()
        run_async(cmd(ia, url='https://example.com/overflow',
                      beschreibung='Overflow'))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('max entries → Warnung', 'maximum' in content)

        # Pruefen dass kein 101. Eintrag drin ist
        entries = atomic_read(json_file, default=list)
        check('max entries → count=100', len(entries) == 100)

        # URL-Validierung: kein Schema
        ia = make_interaction()
        run_async(cmd(ia, url='not-a-url', beschreibung='Bad'))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('invalid URL → Warnung', 'gueltige url' in content)

        # Truncation: lange URL + Beschreibung
        ia = make_interaction()
        # Zuerst Platz schaffen (auf 99 kuerzen)
        atomic_write(json_file, prefill[:99])
        long_url = 'https://example.com/' + 'x' * 600
        long_desc = 'D' * 600
        run_async(cmd(ia, url=long_url, beschreibung=long_desc))
        entries = atomic_read(json_file, default=list)
        last = entries[-1]
        check('truncation → url <= 500', len(last['url']) <= 500)
        check('truncation → beschreibung <= 500', len(last['beschreibung']) <= 500)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_youtube():
    """Tests fuer /youtube Command."""
    print('[/youtube]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('youtube')
        check('cmd_youtube gefunden', cmd is not None)
        if not cmd:
            return

        # Test: Liste leer
        ia = make_interaction()
        run_async(cmd(ia, url=None, beschreibung=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('leere Liste → Hinweis',
              'keine youtube' in content or 'keine youtube-links' in content)

        # Test: hinzufuegen ohne Beschreibung
        ia = make_interaction()
        run_async(cmd(ia, url='https://youtube.com/test', beschreibung=None))
        check('ohne Beschreibung → Warnung',
              'beschreibung' in (ia.response.calls[0].get('content') or '').lower())

        # Test: hinzufuegen mit Beschreibung
        ia = make_interaction()
        run_async(cmd(ia, url='https://youtube.com/test', beschreibung='Test-Kanal'))
        check('hinzufuegen → Bestaetigung',
              'Test-Kanal' in (ia.response.calls[0].get('content') or ''))

        # Test: Liste mit Eintrag
        ia = make_interaction()
        run_async(cmd(ia, url=None, beschreibung=None))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('Liste → Embed mit Eintrag',
              embed is not None and len(embed.fields) > 0)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_reminder():
    """Tests fuer /reminder Command."""
    print('[/reminder]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('reminder')
        check('cmd_reminder gefunden', cmd is not None)
        if not cmd:
            return

        # Test: Status ohne Reminder
        ia = make_interaction()
        run_async(cmd(ia, hours=None, puzzle_count=1, buch=0))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('kein Reminder → Hinweis',
              'keinen aktiven reminder' in content or 'kein' in content)

        # Test: Reminder aktivieren
        ia = make_interaction()
        run_async(cmd(ia, hours=4, puzzle_count=3, buch=0))
        content = ia.response.calls[0].get('content') or ''
        check('aktivieren → Bestaetigung', '4' in content and '3' in content)

        # Test: Status mit Reminder
        ia = make_interaction()
        run_async(cmd(ia, hours=None, puzzle_count=1, buch=0))
        content = ia.response.calls[0].get('content') or ''
        check('Status → zeigt Details', '4' in content)

        # Test: Reminder stoppen
        ia = make_interaction()
        run_async(cmd(ia, hours=0, puzzle_count=1, buch=0))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('stoppen → Bestaetigung', 'gestoppt' in content)

        # Test: Validierung hours
        ia = make_interaction()
        run_async(cmd(ia, hours=200, puzzle_count=1, buch=0))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('hours > 168 → Fehler', '168' in content)

        # Test: Validierung puzzle_count
        ia = make_interaction()
        run_async(cmd(ia, hours=4, puzzle_count=25, buch=0))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('puzzle_count > 20 → Fehler', '20' in content)

        # Test: _parse_utc robust mit verschiedenen Formaten
        from commands.reminder import _parse_utc
        dt1 = _parse_utc('2026-04-25T18:00:00+00:00')
        check('_parse_utc +00:00', dt1.tzinfo is not None)
        dt2 = _parse_utc('2026-04-25T18:00:00Z')
        check('_parse_utc Z-Suffix', dt2.tzinfo is not None)
        dt3 = _parse_utc('2026-04-25T18:00:00')
        check('_parse_utc naive → UTC', dt3.tzinfo is not None)

        # Test: _reminder_loop ueberlebt hours:0 in JSON (korrupter Eintrag)
        from commands.reminder import _reminder_loop, REMINDER_FILE as RF
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        atomic_write(RF, {
            '11111': {'hours': 0, 'puzzle': 1, 'buch': 0, 'next': past},
            '22222': {'hours': 4, 'puzzle': 1, 'buch': 0, 'next': past},
        })
        # Darf keinen ZeroDivisionError werfen
        try:
            run_async(_reminder_loop())
            check('reminder_loop ueberlebt hours:0', True)
        except ZeroDivisionError:
            check('reminder_loop ueberlebt hours:0', False)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_wanted():
    """Tests fuer /wanted, /wanted_list, /wanted_vote, /wanted_delete."""
    print('[/wanted]')
    tmpdir = setup_temp_config()
    try:
        cmd_wanted = _captured_commands.get('wanted')
        cmd_wanted_list = _captured_commands.get('wanted_list')
        cmd_wanted_vote = _captured_commands.get('wanted_vote')
        cmd_wanted_delete = _captured_commands.get('wanted_delete')

        check('cmd_wanted gefunden', cmd_wanted is not None)
        check('cmd_wanted_list gefunden', cmd_wanted_list is not None)
        check('cmd_wanted_vote gefunden', cmd_wanted_vote is not None)
        check('cmd_wanted_delete gefunden', cmd_wanted_delete is not None)
        if not all([cmd_wanted, cmd_wanted_list, cmd_wanted_vote, cmd_wanted_delete]):
            return

        # Test: wanted ohne Beschreibung → zeigt leere Liste
        ia = make_interaction()
        run_async(cmd_wanted(ia, beschreibung=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('wanted leer → Hinweis',
              'keine feature' in content or 'keine feature-wünsche' in content
              or 'keine feature-w' in content)

        # Test: wanted_list leer
        ia = make_interaction()
        run_async(cmd_wanted_list(ia))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('wanted_list leer → Hinweis',
              'keine feature' in content or 'keine feature-w' in content)

        # Test: Feature einreichen
        ia = make_interaction()
        run_async(cmd_wanted(ia, beschreibung='Dark Mode'))
        content = ia.response.calls[0].get('content') or ''
        check('wanted einreichen → Bestaetigung',
              'Dark Mode' in content and '#1' in content)

        # Test: Zweites Feature einreichen
        ia = make_interaction(user=FakeMember(uid=99999, name='User2'))
        run_async(cmd_wanted(ia, beschreibung='Mobile App'))
        content = ia.response.calls[0].get('content') or ''
        check('wanted zweites Feature → #2',
              'Mobile App' in content and '#2' in content)

        # Test: wanted_list zeigt Eintraege
        ia = make_interaction()
        run_async(cmd_wanted_list(ia))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('wanted_list → Embed', embed is not None)
        check('wanted_list → hat Beschreibung',
              embed is not None and 'Dark Mode' in (embed.description or ''))

        # Test: wanted_vote +1
        ia = make_interaction(user=FakeMember(uid=99999, name='User2'))
        run_async(cmd_wanted_vote(ia, id=1))
        content = (ia.response.calls[0].get('content') or '')
        check('wanted_vote +1', '+1' in content or '✅' in content)

        # Test: wanted_vote Toggle (zuruecknehmen)
        ia = make_interaction(user=FakeMember(uid=99999, name='User2'))
        run_async(cmd_wanted_vote(ia, id=1))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('wanted_vote Toggle → zurueckgenommen',
              'zurück' in content or 'zuruck' in content or '↩' in content)

        # Test: wanted_vote nicht gefunden
        ia = make_interaction()
        run_async(cmd_wanted_vote(ia, id=999))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('wanted_vote nicht gefunden', 'nicht gefunden' in content)

        # Test: wanted_delete
        ia = make_interaction(admin=True)
        run_async(cmd_wanted_delete(ia, id=1))
        content = ia.response.calls[0].get('content') or ''
        check('wanted_delete → Bestaetigung', '#1' in content)

        # Test: wanted_delete nicht gefunden
        ia = make_interaction(admin=True)
        run_async(cmd_wanted_delete(ia, id=999))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('wanted_delete nicht gefunden', 'nicht gefunden' in content)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_collection_duplicate_url():
    """Test dass doppelte URLs in _collection abgelehnt werden."""
    print('[collection_duplicate_url]')
    import commands._collection as col

    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('resourcen')
        if not cmd:
            check('cmd_resourcen fuer duplicates', False, 'cmd nicht gefunden')
            return

        # Ersten Eintrag anlegen
        ia = make_interaction()
        run_async(cmd(ia, url='https://example.com/dup', beschreibung='Erster'))
        content = (ia.response.calls[0].get('content') or '')
        check('erster Eintrag → OK', 'Erster' in content)

        # Gleiche URL nochmal
        ia = make_interaction()
        run_async(cmd(ia, url='https://example.com/dup', beschreibung='Zweiter'))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('duplicate URL → Warnung', 'existiert bereits' in content)

        # Andere URL geht
        ia = make_interaction()
        run_async(cmd(ia, url='https://example.com/other', beschreibung='Andere'))
        content = (ia.response.calls[0].get('content') or '')
        check('andere URL → OK', 'Andere' in content)
    finally:
        teardown_temp_config(tmpdir)
    print()
