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



def test_guild_order_home_first():
    """Heim-Guild zuerst (Review W4s S4-021): eine Reihenfolge fuer Member-/Namensaufloesung,
    Spieler-Tagging bei der Turnier-Freigabe nur ueber die Heim-Guild."""
    print('[guild_order_home_first]')
    from commands.turnier_buttons import _resolve_player_names
    from commands import motivation as mot
    from core import permissions

    class _Guild:
        def __init__(self, gid, members):
            self.id = gid
            self.members = members

        def get_member(self, uid):
            return next((m for m in self.members if m.id == uid), None)

    home_max = FakeMember(uid=2001, name='Max')
    foreign_max = FakeMember(uid=3001, name='Max')
    foreign_only = FakeMember(uid=3002, name='Fremd')
    home = _Guild(111, [home_max, FakeMember(uid=2002, name='Lisa')])
    # dieselbe User-ID in beiden Guilds, fremder Nick
    foreign = _Guild(222, [foreign_max, foreign_only, FakeMember(uid=2002, name='Lisa (Spiegel)')])

    bot = MagicMock()
    bot.guilds = [foreign, home]          # fremde Guild liefert bot.guilds zuerst
    bot.get_guild = lambda gid: {111: home, 222: foreign}.get(gid)
    bot.get_user = lambda uid: None

    old_gid, old_bot = permissions._guild_id, mot._bot
    try:
        permissions._guild_id = 111
        order = list(permissions.iter_guilds_home_first(bot))
        check('Reihenfolge: Heim zuerst, jede Guild einmal', order == [home, foreign])
        check('home_only: nur die Heim-Guild',
              list(permissions.iter_guilds_home_first(bot, home_only=True)) == [home])

        ids, missing = _resolve_player_names(bot, ['Max', 'Fremd'])
        check('Tagging: gleichnamiger Max → Heim-Mitglied, nicht der fremde',
              ids == [2001], f'ids={ids}')
        check('Tagging: nur in fremder Guild → „Nicht gefunden"',
              missing == ['Fremd'], f'missing={missing}')

        check('display_name_cached: Heim-Nick vor fremdem',
              permissions.display_name_cached(bot, 2002) == 'Lisa')
        mot._bot = bot
        check('motivation._get_member: Heim-Member vor fremdem',
              mot._get_member(2002) is home.members[1])

        # Heim-Guild nicht im Cache → kein Fallback auf fremde Guilds beim Tagging
        bot.get_guild = lambda gid: None
        ids2, missing2 = _resolve_player_names(bot, ['Max'])
        check('Tagging: Heim-Guild fehlt → nichts getaggt', ids2 == [] and missing2 == ['Max'])

        # Ohne GUILD_ID gibt es keinen Heim-Server → alle Guilds (Ein-Guild-Betrieb)
        permissions._guild_id = 0
        check('ohne GUILD_ID: bot.guilds-Reihenfolge',
              list(permissions.iter_guilds_home_first(bot, home_only=True)) == [foreign, home])
    finally:
        permissions._guild_id, mot._bot = old_gid, old_bot
    print()


# ---------------------------------------------------------------------------
# Charakterisierung (Vorarbeit Zerlegung schachrallye.py, Review W1 S4-016)
# ---------------------------------------------------------------------------
# Halten das heutige Verhalten fest, damit die spaetere Aufteilung in
# termine.py / turnier_store.py / turnier_loops.py byte-gleich nachweisbar ist.
# Bis hierher war der Reminder-Loop (7-Tage-Fenster, reminded-Flag, Retry nach
# Sendefehler) in keinem Test erreichbar.

_GOLDEN_TERMINE_HTML = (
    '<html><body><p>Vorspann ohne Tabelle</p>'
    '<table>'
    '<tr><th>Datum</th><th>Veranstaltung</th><th>Ort</th></tr>'
    '<tr><td>14.05.2027</td>'
    '<td>Schachrallye Jenbach <a href="https://example.com/rallye.pdf">Ausschreibung</a></td>'
    '<td>SK Jenbach, Turnsaal</td></tr>'
    '<tr><td>20.-24.05.2027</td>'
    '<td>Tiroler Jugendmeisterschaft U10 Start: 10 Uhr</td>'
    '<td>Innsbruck<br>Congress</td></tr>'
    '<tr><td>22.05.-25.05.2027</td>'
    '<td><a href="https://chess-results.com/tnr1.aspx">Kufstein Open Schnellschach</a>'
    ' 10:00 Uhr Turnierbeginn</td>'
    '<td>Kufstein</td></tr>'
    '<tr><td>20. + 21.06.2027</td>'
    '<td>Blitz 960 Senioren Cup auf Chess-Results</td>'
    '<td>Wörgl</td></tr>'
    '<tr><td>31.07.-02.08.2027</td><td>Rallye Finale</td><td>Hall</td></tr>'
    '<tr><td>03.09.2027</td><td>Kadertraining Gruppe A</td><td>Schwaz</td></tr>'
    '<tr><td>04.09.2027</td><td>Österreichische Meisterschaften U12/U14</td><td>Graz</td></tr>'
    '<tr><td>demnaechst</td><td>Vereinsabend</td><td>Lienz</td></tr>'
    '<tr><td>05.09.2027</td><td>Nur zwei Zellen</td></tr>'
    '</table></body></html>'
)

_GOLDEN_TERMINE = [
    {'datum': '2027-05-14', 'datum_text': '14.05.2027',
     'name': 'Schachrallye Jenbach', 'ort': 'SK Jenbach, Turnsaal',
     'link': 'https://example.com/rallye.pdf', 'tags': ['schachrallye']},
    {'datum': '2027-05-20', 'datum_text': '20.-24.05.2027',
     'name': 'Tiroler Jugendmeisterschaft U10', 'ort': 'Innsbruck Congress',
     'link': '', 'tags': ['jugend']},
    {'datum': '2027-05-22', 'datum_text': '22.05.-25.05.2027',
     'name': 'Kufstein Open Schnellschach', 'ort': 'Kufstein',
     'link': 'https://chess-results.com/tnr1.aspx', 'tags': ['schnellschach', 'klassisch']},
    {'datum': '2027-06-20', 'datum_text': '20. + 21.06.2027',
     'name': 'Blitz 960 Senioren Cup', 'ort': 'Wörgl',
     'link': '', 'tags': ['blitz', '960', 'senioren']},
    {'datum': '2027-07-31', 'datum_text': '31.07.-02.08.2027',
     'name': 'Rallye Finale', 'ort': 'Hall',
     'link': '', 'tags': ['schachrallye']},
]


def test_fetch_termine_golden():
    """Golden: _fetch_termine liefert aus einer festen Termin-Seite genau diese Liste."""
    print('[fetch_termine_golden]')
    import sys as _sys
    from core.version import VERSION
    fake_resp = MagicMock()
    fake_resp.text = _GOLDEN_TERMINE_HTML
    fake_resp.raise_for_status = MagicMock()
    fake_get = MagicMock(return_value=fake_resp)
    with _mock.patch.object(_sys.modules['requests'], 'get', fake_get):
        events = schachrallye_mod._fetch_termine()
    check('golden: Event-Liste unveraendert', events == _GOLDEN_TERMINE,
          detail=json.dumps(events, ensure_ascii=False))
    args, kwargs = fake_get.call_args
    check('golden: URL = tirol.chess.at/termine/',
          args == ('https://tirol.chess.at/termine/',), detail=str(args))
    check('golden: timeout 15 + User-Agent mit Version',
          kwargs == {'timeout': 15, 'headers': {'User-Agent': f'schach-bot/{VERSION}'}},
          detail=str(kwargs))
    print()


class _FlakyChannel(FakeChannel):
    """FakeChannel, dessen send() auf Wunsch scheitert."""

    def __init__(self, channel_id):
        super().__init__(channel_id=channel_id)
        self.fail = False

    async def send(self, content=None, **kwargs):
        if self.fail:
            raise RuntimeError('Discord weg')
        return await super().send(content=content, **kwargs)


def test_rallye_loops():
    """Charakterisierung Reminder-Loop (6 h) + Auto-Parse-Loop (18:00) aus setup()."""
    print('[rallye_loops]')
    import sys as _sys
    from core.datetime_utils import noon_utc_ts
    tmpdir = setup_temp_config()
    old_bot = schachrallye_mod._bot
    old_cid = schachrallye_mod._tournament_channel_id
    old_btn = (turnier_buttons_mod._bot, turnier_buttons_mod._tournament_channel_id)
    old_cmds = dict(_captured_commands)
    try:
        channel = _FlakyChannel(channel_id=55555)

        class _LoopBot(h._CapturingBot):
            def __init__(self):
                super().__init__()
                self._task_loops = {}

            def get_channel(self, cid):
                return channel if cid == 55555 else None

        bot = _LoopBot()
        schachrallye_mod.setup(bot, tournament_channel_id=55555)
        reminder = bot._task_loops.get('rallye_reminder')
        auto_parse = bot._task_loops.get('auto_parse')
        check('setup registriert rallye_reminder + auto_parse in bot._task_loops',
              reminder is not None and auto_parse is not None)
        if reminder is None or auto_parse is None:
            return

        today = date.today()

        def _in(days):
            return (today + timedelta(days=days)).isoformat()

        def _ev(eid, datum, tags=('schachrallye',), **kw):
            e = {'id': eid, 'datum': datum, 'datum_text': '', 'name': f'Rallye {eid}',
                 'ort': 'Ort', 'link': '', 'tags': list(tags), 'reminded': False}
            e.update(kw)
            return e

        events = [
            _ev(1, _in(3), name='5. Rallye', ort='SK Jenbach, Turnsaal'),
            _ev(2, _in(3), reminded=True),
            _ev(3, _in(3), approved=False),
            _ev(4, _in(10)),
            _ev(5, _in(0)),
            _ev(6, _in(3), tags=('blitz',)),
            _ev(7, _in(7), name='', ort='Wörgl'),
            _ev(8, 'kaputt'),
            _ev(9, _in(8)),
        ]
        atomic_write(schachrallye_mod.TURNIER_FILE, {
            'events': events,
            'subscribers': {'schachrallye': [111, 222], 'blitz': [333]},
            'reviewers': [], 'next_id': 10,
        })

        def _reminded():
            data = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
            return {e['id']: e.get('reminded') for e in data.get('events', [])}

        # --- due_reminders (rein): dieselbe Auswahl, die der Loop gleich postet (W4s S4-020) ---
        stored = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
        due, subs = schachrallye_mod.due_reminders(stored, today)
        check('due_reminders: #1 und #7 faellig, Rallye-Subscriber',
              [e['id'] for e in due] == [1, 7] and subs == [111, 222],
              detail=f'{[e["id"] for e in due]} {subs}')
        check('due_reminders: ohne Rallye-Subscriber nichts faellig',
              schachrallye_mod.due_reminders(
                  {**stored, 'subscribers': {'blitz': [333]}}, today)[0] == [])
        check('due_reminders: kaputte Datei → nichts', schachrallye_mod.due_reminders([], today) == ([], []))
        check('due_reminders: morgen rueckt #9 (dann 7 Tage) nach, #4 (9 Tage) nicht',
              [e['id'] for e in schachrallye_mod.due_reminders(stored, today + timedelta(days=1))[0]]
              == [1, 7, 9])

        # --- Lauf 1: nur #1 (3 Tage) und #7 (genau 7 Tage) werden erinnert ---
        run_async(reminder())
        check('Reminder: 2 Posts (#1 und #7)', len(channel.sent) == 2,
              detail=str(len(channel.sent)))
        if len(channel.sent) == 2:
            m1, m7 = channel.sent
            ts1 = noon_utc_ts(today + timedelta(days=3))
            ts7 = noon_utc_ts(today + timedelta(days=7))
            e1, e7 = m1.kwargs.get('embed'), m7.kwargs.get('embed')
            check('Reminder: Mentions aller Rallye-Subscriber',
                  m1.content == '<@111> <@222>' and m7.content == '<@111> <@222>',
                  detail=f'{m1.content!r} {m7.content!r}')
            check('Reminder: Embed-Titel',
                  e1.title == '\U0001f3c7 Schachrallye — Erinnerung', detail=e1.title)
            check('Reminder: Beschreibung mit Name + gekuerztem Ort',
                  e1.description == f'**Termin #1** — **5. Rallye** am <t:{ts1}:D> · SK Jenbach',
                  detail=e1.description)
            check('Reminder: Beschreibung ohne Name',
                  e7.description == f'**Termin #7** am <t:{ts7}:D> · Wörgl',
                  detail=e7.description)
        r = _reminded()
        check('Reminder: #1 und #7 als erinnert markiert', r[1] is True and r[7] is True, detail=str(r))
        check('Reminder: uebrige unveraendert',
              r[2] is True and all(r[i] is False for i in (3, 4, 5, 6, 8, 9)), detail=str(r))

        # --- Lauf 2: nichts Neues ---
        run_async(reminder())
        check('Reminder: zweiter Lauf postet nichts', len(channel.sent) == 2)

        # --- Sendefehler: nicht markieren, naechster Lauf holt nach ---
        from core.json_store import atomic_update

        def _add10(data):
            data['events'].append(_ev(10, _in(2)))
            return data

        atomic_update(schachrallye_mod.TURNIER_FILE, _add10)
        channel.fail = True
        run_async(reminder())
        check('Sendefehler: #10 bleibt unerinnert', _reminded()[10] is False)
        channel.fail = False
        run_async(reminder())
        check('Sendefehler: naechster Lauf postet #10', len(channel.sent) == 3)
        check('Sendefehler: danach markiert', _reminded()[10] is True)

        # --- ohne Rallye-Subscriber / ohne Channel: nichts ---
        def _add11_nosubs(data):
            data['events'].append(_ev(11, _in(1)))
            data['subscribers'] = {'blitz': [333]}
            return data

        atomic_update(schachrallye_mod.TURNIER_FILE, _add11_nosubs)
        run_async(reminder())
        check('ohne Subscriber: kein Post, #11 unerinnert',
              len(channel.sent) == 3 and _reminded()[11] is False)

        def _subs_back(data):
            data['subscribers'] = {'schachrallye': [111]}
            return data

        atomic_update(schachrallye_mod.TURNIER_FILE, _subs_back)
        schachrallye_mod._tournament_channel_id = 0
        run_async(reminder())
        check('ohne Channel-ID: kein Post', len(channel.sent) == 3)
        schachrallye_mod._tournament_channel_id = 55555

        # --- Auto-Parse: importiert als pending + pruned Altes ---
        old = (today - timedelta(days=schachrallye_mod._PRUNE_DAYS + 10)).isoformat()
        atomic_write(schachrallye_mod.TURNIER_FILE, {
            'events': [_ev(20, old)],
            'subscribers': {}, 'reviewers': [], 'next_id': 21,
        })
        fake_resp = MagicMock()
        fake_resp.text = _GOLDEN_TERMINE_HTML
        fake_resp.raise_for_status = MagicMock()
        with _mock.patch.object(_sys.modules['requests'], 'get', MagicMock(return_value=fake_resp)):
            run_async(auto_parse())
        data = atomic_read(schachrallye_mod.TURNIER_FILE, default=dict)
        evs = data.get('events', [])
        check('Auto-Parse: altes Event entfernt', all(e['id'] != 20 for e in evs))
        check('Auto-Parse: 5 Termine importiert (IDs 21-25)',
              [e['id'] for e in evs] == [21, 22, 23, 24, 25], detail=str([e['id'] for e in evs]))
        check('Auto-Parse: next_id = 26', data.get('next_id') == 26)
        check('Auto-Parse: alle pending', all(e.get('approved') is False for e in evs))
        check('Auto-Parse: reminded nur bei Rallye',
              [('reminded' in e) for e in evs] == [True, False, False, False, True])
        check('Auto-Parse: kein Channel-Post vor Freigabe', len(channel.sent) == 3)
    finally:
        schachrallye_mod._bot = old_bot
        schachrallye_mod._tournament_channel_id = old_cid
        turnier_buttons_mod.configure(*old_btn)
        _captured_commands.clear()
        _captured_commands.update(old_cmds)
        teardown_temp_config(tmpdir)
    print()
