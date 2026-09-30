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


def test_collection_embed_size_limit():
    """Discords kombiniertes 6000-Zeichen-Limit pro Nachricht: grosse Sammlungen
    mit langen Feldern muessen auf mehrere Nachrichten verteilt werden, sonst
    wirft send_message(embeds=...) HTTPException 400 und /resourcen ist tot."""
    print('[collection_embed_size]')
    import commands._collection as col

    def _embed_size(em):
        n = len(getattr(em, 'title', '') or '')
        for f in em.fields:
            n += len(f.get('name') or '') + len(f.get('value') or '')
        return n

    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('resourcen')
        json_file = col._json_path('resourcen.json')
        # 30 Eintraege mit maximal langen Feldern (~770 Zeichen pro Feld)
        prefill = [{'url': 'https://example.com/' + 'x' * 480,
                    'beschreibung': 'B' * 250,
                    'user': 'Tester', 'datum': '2026-01-01'}
                   for _ in range(30)]
        atomic_write(json_file, prefill)

        ia = make_interaction()
        run_async(cmd(ia, url=None, beschreibung=None))

        # Alle gesendeten Nachrichten einsammeln (response + followups)
        messages = list(ia.response.calls) + list(ia.followup.calls)
        sizes = []
        total_fields = 0
        for call in messages:
            embeds = call.get('embeds') or ([call['embed']] if call.get('embed') else [])
            if not embeds:
                continue
            sizes.append(sum(_embed_size(e) for e in embeds))
            total_fields += sum(len(e.fields) for e in embeds)
        check('alle 30 Eintraege gelistet', total_fields == 30, f'got {total_fields}')
        check('jede Nachricht <= 6000 Zeichen (kombiniert)',
              sizes and all(s <= 6000 for s in sizes), f'sizes={sizes}')
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

        # Regression: Eintrag OHNE 'hours'-Key darf nicht die ganze Runde killen.
        # Vorher: entry['hours'] -> KeyError -> Schleife bricht ab, alle danach
        # werden nicht mehr bedient.
        import puzzle as _leg
        import commands.reminder as reminder_mod
        from test_helpers import FakeChannel as _FakeChannel
        _orig_post = _leg.post_puzzle
        _orig_bot = reminder_mod._bot
        _calls = []

        async def _fake_post(channel, count=1, book_idx=0, user_id=None, show_board=True):
            _calls.append(user_id)
            return count

        class _FakeDMUser:
            async def create_dm(self):
                return _FakeChannel()

        class _FakeBot:
            async def fetch_user(self, uid):
                return _FakeDMUser()

        try:
            _leg.post_puzzle = _fake_post
            reminder_mod._bot = _FakeBot()
            atomic_write(RF, {
                '11111': {'puzzle': 1, 'buch': 0, 'next': past},              # KEIN 'hours' -> vorher KeyError
                '22222': {'hours': 4, 'puzzle': 1, 'buch': 0, 'next': past},  # valide, kommt danach
            })
            run_async(_reminder_loop())
            check('Loop ueberlebt fehlenden hours-Key', True)
            check('valider Eintrag nach kaputtem wird trotzdem bedient', 22222 in _calls)

            # Regression: korrupter 'next'-String (nicht parsebar) darf nicht die
            # ganze Runde killen. Vorher: _parse_utc -> ValueError -> Pass bricht
            # ab, alle User danach verhungern UND bereits bediente Eintraege
            # bekommen kein next-Update -> Duplikat-DMs jede Minute.
            _calls.clear()
            atomic_write(RF, {
                '11111': {'hours': 4, 'puzzle': 1, 'buch': 0, 'next': past},      # valide, VOR dem kaputten
                '22222': {'hours': 4, 'puzzle': 1, 'buch': 0, 'next': 'kaputt'},  # korruptes next
                '33333': {'hours': 4, 'puzzle': 1, 'buch': 0, 'next': past},      # valide, NACH dem kaputten
            })
            run_async(_reminder_loop())
            check('Loop ueberlebt korruptes next', True)
            check('User vor kaputtem Eintrag bedient', 11111 in _calls)
            check('User nach kaputtem Eintrag bedient', 33333 in _calls)
            data_after = atomic_read(RF, dict)
            check('next-Update trotz kaputtem Eintrag geschrieben',
                  data_after['11111']['next'] != past)
        finally:
            _leg.post_puzzle = _orig_post
            reminder_mod._bot = _orig_bot
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_reminder_delivery_policy():
    """N10-002: Unzustellbar/Fehler im Reminder-Loop → kein Versuch in jeder Minute mehr.
    Zustellpolitik wie /motivation (core/dm_delivery)."""
    print('[/reminder Zustellpolitik]')
    import discord
    import puzzle as _leg
    import commands.reminder as reminder_mod
    from core import dm_delivery

    tmpdir = setup_temp_config()
    from commands.reminder import _reminder_loop, REMINDER_FILE as RF   # nach dem Temp-Pfad
    _orig_post, _orig_bot = _leg.post_puzzle, reminder_mod._bot
    calls = {'fetch': 0, 'dm': [], 'post': 0}
    mode = {'fetch': None, 'dm': None, 'post': None}   # je Stufe: Ausnahme oder None

    class _DM:
        async def send(self, content=None, **kw):
            if mode['dm']:
                raise mode['dm']
            calls['dm'].append(content)

    class _User:
        async def create_dm(self):
            return _DM()

    class _Bot:
        async def fetch_user(self, uid):
            calls['fetch'] += 1
            if mode['fetch']:
                raise mode['fetch']
            return _User()

    async def _post(channel, count=1, book_idx=0, user_id=None, show_board=True):
        calls['post'] += 1
        if mode['post']:
            raise mode['post']
        return count

    def _reset(**m):
        calls.update(fetch=0, dm=[], post=0)
        mode.update(fetch=None, dm=None, post=None)
        mode.update(m)

    def _entry(uid='44444'):
        return (atomic_read(RF, dict) or {}).get(uid)

    try:
        _leg.post_puzzle = _post
        reminder_mod._bot = _Bot()
        now = datetime.now(timezone.utc)
        long_ago = (now - timedelta(hours=9)).isoformat()   # hours=4 → missed=2 → Nachhol-Zweig
        just_due = (now - timedelta(minutes=1)).isoformat()

        # A) Nachhol-Zweig, DMs gesperrt → Termin rueckt vor, unreachable=1, naechste Minute Ruhe.
        _reset(dm=discord.Forbidden('403'))
        atomic_write(RF, {'44444': {'hours': 4, 'puzzle': 1, 'buch': 0, 'next': long_ago}})
        run_async(_reminder_loop())
        e = _entry()
        check('Forbidden im Nachhol-Zweig → Termin vorgerueckt', reminder_mod._parse_utc(e['next']) > now)
        check('Forbidden → unreachable=1', e.get('unreachable') == 1)
        fetches = calls['fetch']
        run_async(_reminder_loop())
        check('naechste Minute kein Discord-Aufruf', calls['fetch'] == fetches)

        # B) Nachhol-Zweig: Hinweis-DM raus, dann Fehler → Termin rueckt trotzdem vor
        #    (vorher: „Ich war leider offline" jede Minute erneut).
        _reset(post=RuntimeError('pick_random_lines kaputt'))
        atomic_write(RF, {'44444': {'hours': 4, 'puzzle': 1, 'buch': 0, 'next': long_ago}})
        run_async(_reminder_loop())
        run_async(_reminder_loop())
        check('Offline-Hinweis nur einmal', len(calls['dm']) == 1)
        check('nach erster DM vorgerueckt', reminder_mod._parse_utc(_entry()['next']) > now)

        # C) Konto weg (NotFound) am Limit → Eintrag entfernt (taeglich: 5. Mal wie /motivation).
        _reset(fetch=discord.NotFound('404'))
        atomic_write(RF, {'44444': {'hours': 24, 'puzzle': 1, 'buch': 0, 'next': just_due,
                                    'unreachable': dm_delivery.MAX_UNREACHABLE_DAYS - 1},
                          '55555': {'hours': 24, 'puzzle': 1, 'buch': 0,
                                    'next': (now + timedelta(hours=3)).isoformat()}})
        run_async(_reminder_loop())
        check('unzustellbar am Limit → Eintrag entfernt', _entry() is None)
        check('andere Eintraege bleiben', _entry('55555') is not None)

        # D) voruebergehender Fehler → hoechstens MAX_TRANSIENT_RETRIES Minuten-Retries, dann vor.
        _reset(fetch=RuntimeError('503'))
        atomic_write(RF, {'44444': {'hours': 4, 'puzzle': 1, 'buch': 0, 'next': just_due}})
        run_async(_reminder_loop())
        check('transient → Termin bleibt, retries=1',
              _entry()['next'] == just_due and _entry().get('retries') == 1)
        for _ in range(dm_delivery.MAX_TRANSIENT_RETRIES - 1):
            run_async(_reminder_loop())
        check('nach MAX_TRANSIENT_RETRIES vorgerueckt, retries zurueck',
              reminder_mod._parse_utc(_entry()['next']) > now and 'retries' not in _entry())
        fetches = calls['fetch']
        run_async(_reminder_loop())
        check('danach kein Minuten-Versuch mehr', calls['fetch'] == fetches == dm_delivery.MAX_TRANSIENT_RETRIES)

        # E) Erfolg setzt die Zaehler zurueck.
        _reset()
        atomic_write(RF, {'44444': {'hours': 4, 'puzzle': 1, 'buch': 0, 'next': just_due,
                                    'unreachable': 3, 'retries': 1}})
        run_async(_reminder_loop())
        e = _entry()
        check('Erfolg → Zaehler weg, Termin vor',
              'unreachable' not in e and 'retries' not in e and reminder_mod._parse_utc(e['next']) > now)

        # Gemeinsame Regel: taeglich ab dem 5. Mal, Wochen-Reminder ab dem 2., 4 h ab dem 25.
        check('unreachable_expired taeglich 4/5',
              not dm_delivery.unreachable_expired(4, 24) and dm_delivery.unreachable_expired(5, 24))
        check('unreachable_expired woechentlich 1/2',
              not dm_delivery.unreachable_expired(1, 168) and dm_delivery.unreachable_expired(2, 168))
        check('unreachable_expired 4 h 24/25',
              not dm_delivery.unreachable_expired(24, 4) and dm_delivery.unreachable_expired(25, 4))
        check('outcome_of', dm_delivery.outcome_of(None) == dm_delivery.SENT
              and dm_delivery.outcome_of(discord.Forbidden('x')) == dm_delivery.UNREACHABLE
              and dm_delivery.outcome_of(discord.NotFound('x')) == dm_delivery.UNREACHABLE
              and dm_delivery.outcome_of(RuntimeError('x')) == dm_delivery.TRANSIENT)
    finally:
        _leg.post_puzzle, reminder_mod._bot = _orig_post, _orig_bot
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
