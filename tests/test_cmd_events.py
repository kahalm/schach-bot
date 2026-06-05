"""Tests fuer Event Commands: /schachrallye, /turnier (+ Buttons)."""

import os
import json
import tempfile
import shutil
import unittest.mock as _mock
from unittest.mock import MagicMock, AsyncMock
from datetime import date, datetime, timedelta, timezone

import test_helpers as h
from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    make_interaction, _captured_commands, _discord,
    FakeMember, FakeChannel, FakeMessage, FakeView,
    atomic_read, atomic_write,
    schachrallye_mod, turnier_buttons_mod,
)


def test_schachrallye():
    """Tests fuer /schachrallye, /schachrallye_add, _del, _sub, _unsub."""
    print('[/schachrallye]')
    tmpdir = setup_temp_config()
    try:
        cmd_rallye = _captured_commands.get('schachrallye')
        cmd_add = _captured_commands.get('schachrallye_add')
        cmd_del = _captured_commands.get('schachrallye_del')
        cmd_sub = _captured_commands.get('schachrallye_sub')
        cmd_unsub = _captured_commands.get('schachrallye_unsub')

        check('cmd_schachrallye gefunden', cmd_rallye is not None)
        check('cmd_schachrallye_add gefunden', cmd_add is not None)
        check('cmd_schachrallye_del gefunden', cmd_del is not None)
        check('cmd_schachrallye_sub gefunden', cmd_sub is not None)
        check('cmd_schachrallye_unsub gefunden', cmd_unsub is not None)
        if not all([cmd_rallye, cmd_add, cmd_del, cmd_sub, cmd_unsub]):
            return

        # Test: Leere Liste → Hinweis
        ia = make_interaction()
        run_async(cmd_rallye(ia))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('leere Liste → Hinweis', 'keine' in content)

        # Test: Termin anlegen (Zukunftsdatum)
        from datetime import date, timedelta
        future = date.today() + timedelta(days=30)
        datum_str = future.strftime('%d.%m.%Y')
        ia = make_interaction(admin=True)
        run_async(cmd_add(ia, datum=datum_str, ort='Berlin'))
        content = ia.response.calls[0].get('content') or ''
        check('Termin anlegen → Bestaetigung',
              '#1' in content and 'Berlin' in content)

        # Test: Termin in JSON gespeichert (mit schachrallye-Tag)
        tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
        check('Termin in JSON', len(tdata.get('events', [])) == 1)
        check('Termin hat schachrallye-Tag',
              'schachrallye' in tdata['events'][0].get('tags', []))

        # Test: Zweiter Termin am selben Datum aber anderem Ort → muss akzeptiert werden
        ia = make_interaction(admin=True)
        run_async(cmd_add(ia, datum=datum_str, ort='Wien'))
        content = ia.response.calls[0].get('content') or ''
        check('Zweiter Termin selbes Datum → Bestaetigung',
              '#2' in content and 'Wien' in content)
        tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
        check('Zwei Termine am selben Datum', len(tdata.get('events', [])) == 2)

        # Test: Termine anzeigen → Embed mit Termin
        ia = make_interaction()
        run_async(cmd_rallye(ia))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('Termine anzeigen → Embed', embed is not None)
        check('Embed enthaelt Berlin',
              embed is not None and 'Berlin' in (embed.description or ''))

        # Test: Subscriben
        sub_user = FakeMember(uid=55555, name='SubUser')
        sub_dm_channel = FakeChannel()
        sub_user.create_dm = AsyncMock(return_value=sub_dm_channel)
        ia = make_interaction(user=sub_user)
        run_async(cmd_sub(ia, user=None))
        content = ia.response.calls[0].get('content') or ''
        check('Subscriben → Bestaetigung', 'subscribed' in content.lower())
        check('Subscriben → DM gesendet', len(sub_dm_channel.sent) == 1)
        dm_text = sub_dm_channel.sent[0].content or ''
        check('Subscriben → DM enthaelt unsub-Hinweis', '/schachrallye_unsub' in dm_text)

        # Test: DM fehlgeschlagen (Forbidden) → kein Crash, Warning geloggt
        forbidden_user = FakeMember(uid=66666, name='NoDM')

        async def _raise_forbidden():
            raise _discord.Forbidden(MagicMock(status=403), 'Cannot send DM')
        forbidden_user.create_dm = _raise_forbidden
        # Erst unsubscriben falls vorhanden, dann sub mit Forbidden-User
        ia = make_interaction(user=forbidden_user)
        with _mock.patch('logging.Logger.warning') as mock_warn:
            run_async(cmd_sub(ia, user=None))
            content = ia.response.calls[0].get('content') or ''
            check('Sub trotz DM-Fehler → Bestaetigung', 'subscribed' in content.lower())
            check('DM-Fehler → Warning geloggt',
                  any('66666' in str(c) for c in mock_warn.call_args_list))
        # User wieder unsubscriben fuer sauberen State
        ia = make_interaction(user=forbidden_user)
        run_async(cmd_unsub(ia, user=None))

        # Test: Doppelt subscriben
        ia = make_interaction(user=sub_user)
        run_async(cmd_sub(ia, user=None))
        content = ia.response.calls[0].get('content') or ''
        check('Doppelt sub → bereits', 'bereits' in content.lower())

        # Test: Unsubscriben (gleicher User der vorher subscribed hat)
        ia = make_interaction(user=sub_user)
        run_async(cmd_unsub(ia, user=None))
        content = ia.response.calls[0].get('content') or ''
        check('Unsub → Bestaetigung', 'abbestellt' in content.lower())

        # Test: Unsub wenn nicht subscribed
        ia = make_interaction(user=sub_user)
        run_async(cmd_unsub(ia, user=None))
        content = ia.response.calls[0].get('content') or ''
        check('Unsub nicht subscribed', 'nicht subscribed' in content.lower())

        # Test: Termin loeschen
        ia = make_interaction(admin=True)
        run_async(cmd_del(ia, id=1))
        content = ia.response.calls[0].get('content') or ''
        check('Termin loeschen → Bestaetigung', '#1' in content)

        # Test: Termin loeschen nicht gefunden
        ia = make_interaction(admin=True)
        run_async(cmd_del(ia, id=999))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('Termin loeschen nicht gefunden', 'nicht gefunden' in content)

        # Test: Datum-Validierung falsches Format
        ia = make_interaction(admin=True)
        run_async(cmd_add(ia, datum='2026-05-15', ort='Test'))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('Falsches Datumsformat → Fehler', 'ungueltig' in content or 'format' in content)

        # Test: Datum in der Vergangenheit
        ia = make_interaction(admin=True)
        run_async(cmd_add(ia, datum='01.01.2020', ort='Test'))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('Vergangenheit → Fehler', 'vergangenheit' in content)

        # Test: Sub mit user-Param als Nicht-Admin
        other = FakeMember(uid=99999, name='Other')
        ia = make_interaction(admin=False)
        run_async(cmd_sub(ia, user=other))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('Sub user ohne Admin → Fehler', 'admin' in content)

        # --- /turnier_parse + /turnier Tests ---
        cmd_parse = _captured_commands.get('turnier_parse')
        cmd_turnier = _captured_commands.get('turnier')
        check('cmd_turnier_parse gefunden', cmd_parse is not None)
        check('cmd_turnier gefunden', cmd_turnier is not None)
        if cmd_parse and cmd_turnier:
            # Fake-HTML mit Rallye, Turnier+Link, Training, OeM (letzte 2 = rausgefiltert)
            future2 = (date.today() + timedelta(days=60)).strftime('%d.%m.%Y')
            future3 = (date.today() + timedelta(days=90)).strftime('%d.%m.%Y')
            future4 = date.today() + timedelta(days=70)
            future4_str = future4.strftime('%d.%m.%Y')
            future5_start = date.today() + timedelta(days=80)
            future5_end = future5_start + timedelta(days=4)
            future5_range = f'{future5_start.day}.-{future5_end.day}.{future5_end.strftime("%m.%Y")}'
            past_date = (date.today() - timedelta(days=30)).strftime('%d.%m.%Y')
            past_range_start = date.today() - timedelta(days=20)
            past_range_end = past_range_start + timedelta(days=3)
            past_range = f'{past_range_start.strftime("%d.%m.")}-{past_range_end.strftime("%d.%m.%Y")}'  # z.B. "30.04.-03.05.2026"
            fake_html = (
                '<table>'
                '<tr><th>Datum</th><th>Veranstaltung</th><th>Ort</th></tr>'
                f'<tr><td>{future2}</td><td>5. Jugendschachrallye</td>'
                '<td>SK Jenbach</td></tr>'
                f'<tr><td>{future4_str}</td>'
                '<td><a href="https://example.com/ausschreibung.pdf">'
                'Staatsmeisterschaft Schnellschach</a></td>'
                '<td>PlusCity Linz</td></tr>'
                f'<tr><td>{future5_range}</td><td>Mannschaftsturnier</td>'
                '<td>Leutasch</td></tr>'
                f'<tr><td>{future3}</td><td>Offenes Blitzturnier</td>'
                '<td>Innsbruck</td></tr>'
                f'<tr><td>{future3}</td><td>Chess960 Open</td>'
                '<td>Schwaz</td></tr>'
                f'<tr><td>{future3}</td><td>Tiroler Senioren Einzelmeisterschaft</td>'
                '<td>Schwaz</td></tr>'
                f'<tr><td>{future2}</td><td>Blitzschach-Einzelmeisterschaft U08-U18</td>'
                '<td>Innsbruck</td></tr>'
                f'<tr><td>{past_date}</td><td>Kadertraining Gruppe Bauer</td>'
                '<td>Kufstein</td></tr>'
                f'<tr><td>{past_range}</td>'
                '<td>Österreichische Meisterschaften U08/ U10</td>'
                '<td>Fuerstenfeld</td></tr>'
                '</table>'
            )
            fake_resp = MagicMock()
            fake_resp.text = fake_html
            fake_resp.raise_for_status = MagicMock()
            old_fetch = schachrallye_mod.requests.get
            schachrallye_mod.requests.get = MagicMock(return_value=fake_resp)
            try:
                # Parse: importiert Rallye + Turniere, filtert Training
                ia = make_interaction(admin=True)
                run_async(cmd_parse(ia))
                check('parse → defer', any(c['type'] == 'defer' for c in ia.response.calls))
                fu_call = ia.followup.calls[0]
                fu_embed = fu_call.get('embed')
                fu_desc = fu_embed.description if fu_embed else ''
                # Fallback auf content (z.B. bei "bereits vorhanden")
                if not fu_desc:
                    fu_desc = fu_call.get('content') or ''
                check('parse → Rallye importiert', 'Jugendschachrallye' in fu_desc)
                check('parse → Turniere importiert', 'Staatsmeisterschaft' in fu_desc)
                check('parse → Training gefiltert', 'Kadertraining' not in fu_desc)
                check('parse → OeM gefiltert', 'Meisterschaften U08' not in fu_desc)

                # Alles in einer turnier.json?
                tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
                all_events = tdata.get('events', [])
                # Rallye (1) + manueller Termin von oben (1, bereits geloescht) + 2 Turniere = 3
                # Aber der manuell angelegte wurde geloescht → Rallye(1) + Turniere(2) = 3
                rallye_events = [e for e in all_events if 'schachrallye' in e.get('tags', [])]
                turnier_events = [e for e in all_events if 'schachrallye' not in e.get('tags', [])]
                check('parse → Rallye in JSON', len(rallye_events) >= 1)
                check('parse → Turniere in JSON', len(turnier_events) == 6)
                check('parse → Tags korrekt',
                      all('schachrallye' in e.get('tags', []) for e in rallye_events))

                # Schnellschach/Blitz/960 Tags
                staats_tags = [e for e in all_events if 'Staatsmeisterschaft' in e.get('name', '')]
                check('parse → Schnellschach-Tag',
                      len(staats_tags) == 1 and 'schnellschach' in staats_tags[0].get('tags', []))
                blitz_evts = [e for e in all_events if 'Blitz' in e.get('name', '')]
                check('parse → Blitz-Tag',
                      len(blitz_evts) >= 1 and all('blitz' in e.get('tags', []) for e in blitz_evts))
                c960_evts = [e for e in all_events if '960' in e.get('name', '')]
                check('parse → 960-Tag',
                      len(c960_evts) == 1 and '960' in c960_evts[0].get('tags', []))

                # Jugend-Tag
                jugend_rallye = [e for e in all_events if 'Jugendschachrallye' in e.get('name', '')]
                check('parse → Jugend-Tag auf Rallye',
                      len(jugend_rallye) >= 1 and 'jugend' in jugend_rallye[0].get('tags', []))
                jugend_u18 = [e for e in all_events if 'U08-U18' in e.get('name', '')]
                check('parse → Jugend-Tag auf U08-U18',
                      len(jugend_u18) == 1 and 'jugend' in jugend_u18[0].get('tags', []))
                # Senioren-Tag
                senior_evts = [e for e in all_events if 'Senioren' in e.get('name', '')]
                check('parse → Senioren-Tag',
                      len(senior_evts) == 1 and 'senioren' in senior_evts[0].get('tags', []))
                # Klassisch-Tag (Open)
                open_evts = [e for e in all_events if 'Open' in e.get('name', '')]
                check('parse → Klassisch-Tag',
                      len(open_evts) >= 1 and all('klassisch' in e.get('tags', []) for e in open_evts))
                # URL-Validierung: ungueltige URLs nicht als Embed-URL
                check('_is_valid_url gueltig',
                      schachrallye_mod._is_valid_url('https://example.com/foo.pdf'))
                check('_is_valid_url ungueltig (Leerzeichen)',
                      not schachrallye_mod._is_valid_url('http://Rallye Jenbach: https://foo.com'))
                check('_is_valid_url ungueltig (leer)',
                      not schachrallye_mod._is_valid_url(''))

                # Link korrekt erfasst?
                staats = [e for e in all_events if 'Staatsmeisterschaft' in e.get('name', '')]
                check('parse → Link erfasst',
                      len(staats) == 1 and staats[0].get('link') == 'https://example.com/ausschreibung.pdf')

                # Datumsbereich korrekt geparst?
                mannschaft = [e for e in all_events if 'Mannschaft' in e.get('name', '')]
                check('parse → Datumsbereich geparst',
                      len(mannschaft) == 1 and mannschaft[0].get('datum_text') == future5_range)
                check('parse → kein Link wenn keiner da',
                      len(mannschaft) == 1 and mannschaft[0].get('link', '') == '')

                # Nochmal parsen → keine Duplikate (gleiche Events)
                ia = make_interaction(admin=True)
                run_async(cmd_parse(ia))
                fu_content = (ia.followup.calls[0].get('content') or '').lower()
                check('parse erneut → keine Duplikate', 'bereits vorhanden' in fu_content)

                # Neues Event am selben Datum wie bestehendes → muss trotzdem importiert werden
                future3_iso = (date.today() + timedelta(days=90)).strftime('%Y-%m-%d')
                events_before = len(atomic_read(schachrallye_mod.TURNIER_FILE, default=dict).get('events', []))
                new_html = (
                    '<table>'
                    '<tr><th>Datum</th><th>Veranstaltung</th><th>Ort</th></tr>'
                    f'<tr><td>{future3}</td><td>Neues Abendturnier</td>'
                    '<td>Hall</td></tr>'
                    '</table>'
                )
                fake_resp2 = MagicMock()
                fake_resp2.text = new_html
                fake_resp2.raise_for_status = MagicMock()
                schachrallye_mod.requests.get = MagicMock(return_value=fake_resp2)
                ia = make_interaction(admin=True)
                run_async(cmd_parse(ia))
                events_after = len(atomic_read(schachrallye_mod.TURNIER_FILE, default=dict).get('events', []))
                check('neues Event selbes Datum → importiert', events_after == events_before + 1)

                # Events freigeben fuer /turnier-Anzeige
                from core.json_store import atomic_update as _au
                def _approve_imported(data):
                    for e in data.get('events', []):
                        e['approved'] = True
                    return data
                _au(schachrallye_mod.TURNIER_FILE, _approve_imported)

                # /turnier zeigt Turniere mit Link
                ia = make_interaction()
                run_async(cmd_turnier(ia))
                call = ia.response.calls[0]
                embed = call.get('embed')
                check('/turnier → Embed', embed is not None)
                desc = embed.description if embed else ''
                check('/turnier → enthaelt Turnier', 'Staatsmeisterschaft' in desc)
                check('/turnier → Link im Embed', 'example.com/ausschreibung.pdf' in desc)
                check('/turnier → kein Training', 'Kadertraining' not in desc)
                check('/turnier → keine OeM', 'Meisterschaften U08' not in desc)

                # /turnier leer
                atomic_write(schachrallye_mod.TURNIER_FILE, {"events": [], "subscribers": {}, "next_id": 1})
                ia = make_interaction()
                run_async(cmd_turnier(ia))
                content = (ia.response.calls[0].get('content') or '').lower()
                check('/turnier leer → Hinweis', 'keine' in content)
            finally:
                schachrallye_mod.requests.get = old_fetch
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_turnier_sub():
    """Tests fuer /turnier_sub und /turnier_unsub."""
    print('[/turnier_sub]')
    tmpdir = setup_temp_config()
    try:
        cmd_sub = _captured_commands.get('turnier_sub')
        cmd_unsub = _captured_commands.get('turnier_unsub')
        check('cmd_turnier_sub gefunden', cmd_sub is not None)
        check('cmd_turnier_unsub gefunden', cmd_unsub is not None)
        if not cmd_sub or not cmd_unsub:
            return

        # Sub fuer Tag → Bestaetigung + in JSON
        sub_user = FakeMember(uid=77777, name='TagUser')
        sub_dm_channel = FakeChannel()
        sub_user.create_dm = AsyncMock(return_value=sub_dm_channel)
        ia = make_interaction(user=sub_user)
        run_async(cmd_sub(ia, tag='blitz', user=None))
        content = ia.response.calls[0].get('content') or ''
        check('turnier_sub → Bestaetigung', 'blitz' in content.lower() and 'gepingt' in content.lower())

        # DM gesendet?
        check('turnier_sub → DM gesendet', len(sub_dm_channel.sent) == 1)
        dm_text = sub_dm_channel.sent[0].content or ''
        check('turnier_sub → DM enthaelt unsub-Hinweis', '/turnier_unsub' in dm_text)

        # In JSON gespeichert?
        tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
        blitz_subs = tdata.get('subscribers', {}).get('blitz', [])
        check('turnier_sub → in JSON unter subscribers.blitz', 77777 in blitz_subs)

        # Doppelt sub → bereits
        ia = make_interaction(user=sub_user)
        run_async(cmd_sub(ia, tag='blitz', user=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_sub doppelt → bereits', 'bereits' in content)

        # Unsub → Bestaetigung + entfernt
        ia = make_interaction(user=sub_user)
        run_async(cmd_unsub(ia, tag='blitz', user=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_unsub → Bestaetigung', 'abbestellt' in content)

        tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
        blitz_subs = tdata.get('subscribers', {}).get('blitz', [])
        check('turnier_unsub → aus JSON entfernt', 77777 not in blitz_subs)

        # Unsub wenn nicht subscribed
        ia = make_interaction(user=sub_user)
        run_async(cmd_unsub(ia, tag='blitz', user=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_unsub nicht subscribed → Hinweis', 'nicht' in content)

        # Ohne Tag → eigene Subs anzeigen (leer)
        ia = make_interaction(user=sub_user)
        run_async(cmd_sub(ia, tag='', user=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_sub ohne tag leer → Hinweis', 'keine' in content)

        # Sub fuer 2 Tags, dann ohne Tag → Liste
        sub_user2 = FakeMember(uid=77777, name='TagUser')
        sub_user2.create_dm = AsyncMock(return_value=FakeChannel())
        ia = make_interaction(user=sub_user2)
        run_async(cmd_sub(ia, tag='blitz', user=None))
        ia = make_interaction(user=sub_user2)
        run_async(cmd_sub(ia, tag='960', user=None))
        ia = make_interaction(user=sub_user2)
        run_async(cmd_sub(ia, tag='', user=None))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_sub ohne tag → zeigt Tags', '`blitz`' in content and '`960`' in content)

        # Aufraumen
        ia = make_interaction(user=sub_user2)
        run_async(cmd_unsub(ia, tag='blitz', user=None))
        ia = make_interaction(user=sub_user2)
        run_async(cmd_unsub(ia, tag='960', user=None))

        # Nicht-Admin mit user → Fehler
        other = FakeMember(uid=88888, name='Other')
        ia = make_interaction(admin=False)
        run_async(cmd_sub(ia, tag='blitz', user=other))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_sub user ohne Admin → Fehler', 'admin' in content)

        ia = make_interaction(admin=False)
        run_async(cmd_unsub(ia, tag='blitz', user=other))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('turnier_unsub user ohne Admin → Fehler', 'admin' in content)

    finally:
        teardown_temp_config(tmpdir)

    # schachrallye_sub Message erwaehnt Ping-Feature
    tmpdir = setup_temp_config()
    try:
        cmd_rallye_sub = _captured_commands.get('schachrallye_sub')
        if cmd_rallye_sub:
            ping_user = FakeMember(uid=44444, name='PingCheck')
            ping_dm = FakeChannel()
            ping_user.create_dm = AsyncMock(return_value=ping_dm)
            ia = make_interaction(user=ping_user)
            run_async(cmd_rallye_sub(ia, user=None))
            content = ia.response.calls[0].get('content') or ''
            check('schachrallye_sub → erwaehnt Ping', 'gepingt' in content.lower())
            check('schachrallye_sub → erwaehnt 7 Tage', '7 tage' in content.lower())
            dm_text = ping_dm.sent[0].content or '' if ping_dm.sent else ''
            check('schachrallye_sub DM → erwaehnt Ping', 'gepingt' in dm_text.lower())
        else:
            check('schachrallye_sub Ping-Feature', False, 'cmd nicht gefunden')
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_turnier_prune():
    """Test dass _prune_old_events alte Events entfernt."""
    print('[turnier_prune]')
    tmpdir = setup_temp_config()
    try:
        from commands.schachrallye import _prune_old_events, TURNIER_FILE, _PRUNE_DAYS
        import commands.schachrallye as rallye_mod
        old_file = rallye_mod.TURNIER_FILE
        rallye_mod.TURNIER_FILE = os.path.join(tmpdir, 'turnier.json')

        try:
            old_date = str(date.today() - timedelta(days=_PRUNE_DAYS + 10))
            recent_date = str(date.today() + timedelta(days=5))
            data = {
                "events": [
                    {"id": 1, "datum": old_date, "name": "Alt"},
                    {"id": 2, "datum": recent_date, "name": "Neu"},
                ],
                "subscribers": {},
                "next_id": 3,
            }
            atomic_write(rallye_mod.TURNIER_FILE, data)

            _prune_old_events()

            result = atomic_read(rallye_mod.TURNIER_FILE, default=dict)
            events = result.get('events', [])
            check('prune → 1 Event uebrig', len(events) == 1)
            check('prune → neues bleibt', events[0]['name'] == 'Neu')
        finally:
            rallye_mod.TURNIER_FILE = old_file
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_turnier_review():
    """Tests fuer Turnier-Review-Flow: approved-Flag, Reviewer-Toggle, Pending."""
    print('[turnier_review]')
    tmpdir = setup_temp_config()
    try:
        cmd_review = _captured_commands.get('turnier_review')
        cmd_pending = _captured_commands.get('turnier_pending')
        cmd_turnier = _captured_commands.get('turnier')
        cmd_parse = _captured_commands.get('turnier_parse')

        check('cmd_turnier_review gefunden', cmd_review is not None)
        check('cmd_turnier_pending gefunden', cmd_pending is not None)
        if not cmd_review or not cmd_pending:
            return

        # --- Reviewer Toggle ---
        # Sub als Admin
        admin_user = FakeMember(uid=11111, name='Admin', admin=True)
        ia = make_interaction(user=admin_user)
        run_async(cmd_review(ia))
        content = ia.response.calls[0].get('content') or ''
        check('review sub → Bestaetigung', 'reviewer' in content.lower())

        # In JSON?
        tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
        check('reviewer in JSON', 11111 in tdata.get('reviewers', []))

        # Unsub (nochmal aufrufen → Toggle)
        ia = make_interaction(user=admin_user)
        run_async(cmd_review(ia))
        content = ia.response.calls[0].get('content') or ''
        check('review unsub → Bestaetigung', 'abbestellt' in content.lower())

        tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
        check('reviewer aus JSON entfernt', 11111 not in tdata.get('reviewers', []))

        # Nicht-Admin → Fehler
        ia = make_interaction(admin=False)
        run_async(cmd_review(ia))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('review ohne Admin → Fehler', 'admin' in content)

        # --- Neue Events mit approved=false wenn Reviewer vorhanden ---
        # Erst Reviewer subscriben
        ia = make_interaction(user=admin_user)
        run_async(cmd_review(ia))

        # Fake Parse mit Reviewer
        future_d = (date.today() + timedelta(days=45)).strftime('%d.%m.%Y')
        future_iso = (date.today() + timedelta(days=45)).strftime('%Y-%m-%d')
        fake_html = (
            '<table>'
            '<tr><th>Datum</th><th>Veranstaltung</th><th>Ort</th></tr>'
            f'<tr><td>{future_d}</td><td>Testturnier Review</td>'
            '<td>Innsbruck</td></tr>'
            '</table>'
        )
        fake_resp = MagicMock()
        fake_resp.text = fake_html
        fake_resp.raise_for_status = MagicMock()
        old_fetch = schachrallye_mod.requests.get
        schachrallye_mod.requests.get = MagicMock(return_value=fake_resp)
        try:
            ia = make_interaction(admin=True)
            run_async(cmd_parse(ia))

            # Event in JSON mit approved=false?
            tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
            review_events = [e for e in tdata.get('events', [])
                             if e.get('name') == 'Testturnier Review']
            check('neues Event hat approved=false',
                  len(review_events) == 1 and review_events[0].get('approved') is False)

            # /turnier zeigt pending Events NICHT an
            if cmd_turnier:
                ia = make_interaction()
                run_async(cmd_turnier(ia))
                call = ia.response.calls[0]
                embed = call.get('embed')
                content = call.get('content') or ''
                desc = embed.description if embed else content
                check('/turnier filtert pending Events',
                      'Testturnier Review' not in desc)

            # /turnier_pending zeigt pending Events (pro Event ein Embed mit Buttons)
            ia = make_interaction(admin=True)
            run_async(cmd_pending(ia))
            check('/turnier_pending → defer', ia.response.calls[0].get('type') == 'defer')
            check('/turnier_pending → followup', len(ia.followup.calls) >= 1)
            fu = ia.followup.calls[0]
            embed = fu.get('embed')
            check('/turnier_pending → Embed', embed is not None)
            check('/turnier_pending zeigt pending Event',
                  'Testturnier Review' in (embed.title if embed else ''))
            check('/turnier_pending → View', fu.get('view') is not None)
            footer = embed.footer.text if embed and embed.footer else ''
            check('/turnier_pending → Footer Event #', footer.startswith('Event #'))

            # /turnier_parse zeigt "pending" im Text
            fu_call = None
            for c in ia.followup.calls:
                if c.get('type') == 'send':
                    fu_call = c
                    break
            # Parse-Antwort pruefen (vom vorherigen parse-Aufruf)
            # Nochmal parsen (liefert "bereits vorhanden")
            ia2 = make_interaction(admin=True)
            run_async(cmd_parse(ia2))

        finally:
            schachrallye_mod.requests.get = old_fetch

        # --- Kein Reviewer → auto-approve ---
        # Reviewer entfernen
        ia = make_interaction(user=admin_user)
        run_async(cmd_review(ia))  # Toggle → unsub

        # Neues Event parsen ohne Reviewer
        future_d2 = (date.today() + timedelta(days=55)).strftime('%d.%m.%Y')
        fake_html2 = (
            '<table>'
            '<tr><th>Datum</th><th>Veranstaltung</th><th>Ort</th></tr>'
            f'<tr><td>{future_d2}</td><td>Auto-Approve Turnier</td>'
            '<td>Schwaz</td></tr>'
            '</table>'
        )
        fake_resp2 = MagicMock()
        fake_resp2.text = fake_html2
        fake_resp2.raise_for_status = MagicMock()
        schachrallye_mod.requests.get = MagicMock(return_value=fake_resp2)
        try:
            ia = make_interaction(admin=True)
            run_async(cmd_parse(ia))

            tdata = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
            auto_events = [e for e in tdata.get('events', [])
                           if e.get('name') == 'Auto-Approve Turnier']
            check('kein Reviewer → approved=false (Review noetig)',
                  len(auto_events) == 1 and auto_events[0].get('approved') is False)
        finally:
            schachrallye_mod.requests.get = old_fetch

        # --- /turnier_pending leer → Hinweis ---
        # Erst alle pending Events entfernen (approved setzen)
        def _approve_all(data):
            for e in data.get('events', []):
                e['approved'] = True
            return data
        from core.json_store import atomic_update
        atomic_update(schachrallye_mod.TURNIER_FILE, _approve_all)

        ia = make_interaction(admin=True)
        run_async(cmd_pending(ia))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('/turnier_pending leer → Hinweis', 'keine' in content)

        # --- Abwaertskompatibilitaet: Events ohne approved-Feld gelten als approved ---
        data_compat = {
            "events": [
                {"id": 99, "datum": str(date.today() + timedelta(days=10)),
                 "name": "Legacy Event", "ort": "Wien"}
            ],
            "subscribers": {},
            "reviewers": [],
            "next_id": 100,
        }
        atomic_write(schachrallye_mod.TURNIER_FILE, data_compat)
        if cmd_turnier:
            ia = make_interaction()
            run_async(cmd_turnier(ia))
            call = ia.response.calls[0]
            embed = call.get('embed')
            desc = embed.description if embed else ''
            check('Legacy Event ohne approved → sichtbar',
                  'Legacy Event' in desc)

    finally:
        teardown_temp_config(tmpdir)
    print()


def test_turnier_approve_modal():
    """Tests fuer Spieler-Tagging bei Turnier-Freigabe (Modal)."""
    print('[turnier_approve_modal]')
    tmpdir = setup_temp_config()
    try:
        from commands.turnier_buttons import (
            _handle_review, _execute_approve, _resolve_player_names,
            TurnierApproveModal, configure as _configure_buttons,
        )
        from core.json_store import atomic_update, atomic_write

        # Setup: Bot mit Guild-Members konfigurieren
        fake_channel = FakeChannel(channel_id=55555)

        class FakeGuild:
            def __init__(self, members):
                self.members = members

        member_max = FakeMember(uid=1001, name='Max')
        member_lisa = FakeMember(uid=1002, name='Lisa')
        member_thomas = FakeMember(uid=1003, name='Thomas')
        fake_guild = FakeGuild([member_max, member_lisa, member_thomas])

        fake_bot = MagicMock()
        fake_bot.guilds = [fake_guild]
        fake_bot.get_channel = lambda cid: fake_channel if cid == 55555 else None
        fake_bot.get_user = lambda uid: FakeMember(uid=uid, name=f'User_{uid}')
        _configure_buttons(fake_bot, 55555)

        # Auch schachrallye Modul konfigurieren
        old_bot = schachrallye_mod._bot
        old_cid = schachrallye_mod._tournament_channel_id
        schachrallye_mod._bot = fake_bot
        schachrallye_mod._tournament_channel_id = 55555

        # Event anlegen (pending)
        event_data = {
            "events": [
                {"id": 42, "datum": "2026-07-01", "datum_text": "01.07.2026",
                 "name": "Testturnier Modal", "ort": "Innsbruck",
                 "link": "", "tags": ["schnellschach"], "approved": False},
            ],
            "subscribers": {"schnellschach": [9999]},
            "reviewers": [11111],
            "next_id": 43,
        }
        atomic_write(schachrallye_mod.TURNIER_FILE, event_data)

        # --- Test 1: Approve-Button oeffnet Modal (statt direktem Approve) ---
        fake_embed = h.FakeEmbed(title='Testturnier Modal')
        fake_embed.set_footer(text='Event #42')
        fake_msg = MagicMock()
        fake_msg.embeds = [fake_embed]

        ia = make_interaction(user=FakeMember(uid=11111, name='Admin', admin=True))
        ia.message = fake_msg
        run_async(_handle_review(ia, 'approve'))
        check('Approve → Modal geoeffnet',
              len(ia.response.calls) == 1
              and ia.response.calls[0].get('type') == 'send_modal')
        modal = ia.response.calls[0].get('modal')
        check('Modal ist TurnierApproveModal',
              isinstance(modal, TurnierApproveModal))

        # --- Test 2: _resolve_player_names findet Guild-Member ---
        found_ids, not_found = _resolve_player_names(fake_bot, ['Max', 'Lisa'])
        check('resolve findet Max + Lisa',
              1001 in found_ids and 1002 in found_ids and len(not_found) == 0)

        # Case-insensitive
        found_ids2, not_found2 = _resolve_player_names(fake_bot, ['max', 'THOMAS'])
        check('resolve case-insensitive',
              1001 in found_ids2 and 1003 in found_ids2)

        # Nicht-aufloesbar
        found_ids3, not_found3 = _resolve_player_names(fake_bot, ['Max', 'Xyz'])
        check('resolve nicht-aufloesbar',
              1001 in found_ids3 and 'Xyz' in not_found3)

        # --- Test 3: Leeres Spieler-Feld → normales Approve ohne extra Mentions ---
        # Reset event to pending
        atomic_write(schachrallye_mod.TURNIER_FILE, event_data)
        fake_channel.sent.clear()

        fake_embed2 = h.FakeEmbed(title='Testturnier Modal')
        fake_embed2.set_footer(text='Event #42')
        fake_msg2 = MagicMock()
        fake_msg2.embeds = [fake_embed2]

        ia2 = make_interaction(user=FakeMember(uid=11111, name='Admin', admin=True))
        ia2.edit_original_response = AsyncMock()
        run_async(_execute_approve(ia2, fake_msg2, 42, ''))

        # Channel-Post gesendet?
        check('Leeres Feld → Channel-Post gesendet', len(fake_channel.sent) >= 1)
        # Nur Subscriber-Mentions, keine extra
        post_content = fake_channel.sent[-1].content or '' if fake_channel.sent else ''
        check('Leeres Feld → nur Subscriber-Mentions',
              '<@9999>' in post_content)
        check('Leeres Feld → kein extra Mention',
              '<@1001>' not in post_content and '<@1002>' not in post_content)

        # DM-Embed: freigegeben ohne Spieler-Suffix
        check('Leeres Feld → Titel "freigegeben"',
              'freigegeben' in (fake_embed2.title or ''))
        check('Leeres Feld → kein Spieler im Titel',
              'Spieler' not in (fake_embed2.title or ''))

        # --- Test 4: Mit Spielernamen → extra Mentions im Channel-Post ---
        # Reset
        def _reset(data):
            for e in data.get('events', []):
                if e['id'] == 42:
                    e['approved'] = False
            return data
        atomic_update(schachrallye_mod.TURNIER_FILE, _reset)
        fake_channel.sent.clear()

        fake_embed3 = h.FakeEmbed(title='Testturnier Modal')
        fake_embed3.set_footer(text='Event #42')
        fake_msg3 = MagicMock()
        fake_msg3.embeds = [fake_embed3]

        ia3 = make_interaction(user=FakeMember(uid=11111, name='Admin', admin=True))
        ia3.edit_original_response = AsyncMock()
        run_async(_execute_approve(ia3, fake_msg3, 42, 'Max, Lisa'))

        check('Mit Spielern → Channel-Post gesendet', len(fake_channel.sent) >= 1)
        post_content3 = fake_channel.sent[-1].content or '' if fake_channel.sent else ''
        check('Mit Spielern → Max getaggt', '<@1001>' in post_content3)
        check('Mit Spielern → Lisa getaggt', '<@1002>' in post_content3)
        check('Mit Spielern → Subscriber auch getaggt', '<@9999>' in post_content3)

        # DM-Embed: freigegeben mit Spieler-Suffix
        check('Mit Spielern → Titel enthaelt Spieler',
              'Spieler: Max, Lisa' in (fake_embed3.title or ''))

        # --- Test 5: Nicht-aufloesbare Namen → Warnung im DM-Embed ---
        def _reset2(data):
            for e in data.get('events', []):
                if e['id'] == 42:
                    e['approved'] = False
            return data
        atomic_update(schachrallye_mod.TURNIER_FILE, _reset2)
        fake_channel.sent.clear()

        fake_embed4 = h.FakeEmbed(title='Testturnier Modal')
        fake_embed4.set_footer(text='Event #42')
        fake_msg4 = MagicMock()
        fake_msg4.embeds = [fake_embed4]

        ia4 = make_interaction(user=FakeMember(uid=11111, name='Admin', admin=True))
        ia4.edit_original_response = AsyncMock()
        run_async(_execute_approve(ia4, fake_msg4, 42, 'Max, Xyz'))

        check('Nicht-aufloesbar → Warnung in Description',
              'Nicht gefunden: Xyz' in (fake_embed4.description or ''))
        check('Nicht-aufloesbar → Max trotzdem getaggt',
              '<@1001>' in (fake_channel.sent[-1].content or '') if fake_channel.sent else False)
        check('Nicht-aufloesbar → Titel zeigt nur aufgeloeste Spieler',
              'Spieler: Max' in (fake_embed4.title or '')
              and 'Xyz' not in (fake_embed4.title or '').split('Spieler:')[1] if 'Spieler:' in (fake_embed4.title or '') else False)

        # --- Test 6 (Regression): erneutes Approve eines bereits freigegebenen
        # Events postet NICHT erneut (Doppelklick / zwei Reviewer). ---
        fake_channel.sent.clear()
        fake_embed5 = h.FakeEmbed(title='Testturnier Modal')
        fake_embed5.set_footer(text='Event #42')
        fake_msg5 = MagicMock()
        fake_msg5.embeds = [fake_embed5]
        ia5 = make_interaction(user=FakeMember(uid=11111, name='Admin', admin=True))
        ia5.edit_original_response = AsyncMock()
        run_async(_execute_approve(ia5, fake_msg5, 42, ''))  # 42 ist bereits approved
        check('Doppel-Approve → kein erneuter Channel-Post', len(fake_channel.sent) == 0)
        check('Doppel-Approve → DM "bereits bearbeitet"',
              'bereits bearbeitet' in (fake_embed5.title or ''))

        # Aufraumen
        schachrallye_mod._bot = old_bot
        schachrallye_mod._tournament_channel_id = old_cid

    finally:
        teardown_temp_config(tmpdir)
    print()

