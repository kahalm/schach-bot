"""Tests fuer Library Commands: /bibliothek, /tag, /autor, /reindex, parse, auto-tag, catalog."""

import os
import json
import asyncio
import tempfile
import shutil
from unittest.mock import MagicMock

import test_helpers as h
from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    make_interaction, _captured_commands, FakeView,
)


def test_bibliothek():
    """Smoke-Tests fuer /bibliothek Command."""
    print('[/bibliothek]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('bibliothek')
        check('cmd_bibliothek gefunden', cmd is not None)
        if not cmd:
            return

        import library as lib_mod

        orig_pag = lib_mod.LibraryPaginationView
        lib_mod.LibraryPaginationView = lambda pages, query, sizes=None: FakeView()

        orig_search = lib_mod._search_library
        lib_mod._search_library = lambda q, limit=25: [
            {
                'id': 'test--testbook',
                'title': 'Testbook',
                'author': 'TestAutor',
                'year': 2020,
                'tags': ['Taktik'],
                'file_type': 'pdf',
                'files': [],
            },
        ]

        try:
            ia = make_interaction()
            run_async(cmd(ia, suche='test'))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('followup gesendet', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('Ergebnis → Embed mit Feld',
                  embed is not None and len(embed.fields) > 0)
        finally:
            lib_mod._search_library = orig_search
            lib_mod.LibraryPaginationView = orig_pag
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_tag():
    """Smoke-Tests fuer /tag Command."""
    print('[/tag]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('tag')
        check('cmd_tag gefunden', cmd is not None)
        if not cmd:
            return

        import library as lib_mod

        # LibraryPaginationView ist ein MagicMock → ersetzen
        orig_pag = lib_mod.LibraryPaginationView
        lib_mod.LibraryPaginationView = lambda pages, query, sizes=None: FakeView()

        orig_ensure = lib_mod._ensure_library
        lib_mod._ensure_library = lambda: [
            {
                'id': 'test--taktikbook',
                'title': 'Taktik Buch',
                'author': 'Autor',
                'year': 2021,
                'tags': ['Taktik'],
                'file_type': 'pdf',
                'files': [],
            },
        ]

        try:
            ia = make_interaction()
            run_async(cmd(ia, tag='Taktik'))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('followup gesendet', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('Tag-Ergebnis → Embed',
                  embed is not None and len(embed.fields) > 0)

            # Test: Tag nicht gefunden
            ia = make_interaction()
            run_async(cmd(ia, tag='Nonexistent'))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('Tag nicht gefunden', 'keine bücher' in content or 'keine b' in content)
        finally:
            lib_mod._ensure_library = orig_ensure
            lib_mod.LibraryPaginationView = orig_pag
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_autor():
    """Smoke-Tests fuer /autor Command."""
    print('[/autor]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('autor')
        check('cmd_autor gefunden', cmd is not None)
        if not cmd:
            return

        import library as lib_mod

        orig_pag = lib_mod.LibraryPaginationView
        lib_mod.LibraryPaginationView = lambda pages, query, sizes=None: FakeView()

        orig_ensure = lib_mod._ensure_library
        lib_mod._ensure_library = lambda: [
            {
                'id': 'kasparov--mygreat',
                'title': 'My Great Predecessors',
                'author': 'Kasparov',
                'year': 2003,
                'tags': [],
                'file_type': 'pdf',
                'files': [],
            },
        ]

        try:
            ia = make_interaction()
            run_async(cmd(ia, autor='Kasparov'))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('followup gesendet', len(ia.followup.calls) > 0)
            embed = ia.followup.calls[0].get('embed')
            check('Autor-Ergebnis → Embed',
                  embed is not None and len(embed.fields) > 0)

            # Test: Autor nicht gefunden
            ia = make_interaction()
            run_async(cmd(ia, autor='Unbekannt'))
            content = (ia.followup.calls[0].get('content') or '').lower()
            check('Autor nicht gefunden',
                  'keine bücher' in content or 'keine b' in content)
        finally:
            lib_mod._ensure_library = orig_ensure
            lib_mod.LibraryPaginationView = orig_pag
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_reindex():
    """Smoke-Tests fuer /reindex Command."""
    print('[/reindex]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('reindex')
        check('cmd_reindex gefunden', cmd is not None)
        if not cmd:
            return

        import library as lib_mod
        import puzzle.selection as sel_mod

        orig_build = lib_mod.build_library_catalog
        orig_reload = lib_mod._reload_library
        orig_clear = sel_mod.clear_lines_cache
        orig_load = sel_mod.load_all_lines

        lib_mod.build_library_catalog = lambda: (100, 50, 5, 3, 2)
        lib_mod._reload_library = lambda: None
        sel_mod.clear_lines_cache = lambda: None
        sel_mod.load_all_lines = lambda: [('a.pgn:1', None)] * 42

        # LIBRARY_INDEX muss gesetzt sein damit der Bibliotheks-Teil laeuft
        orig_index = lib_mod.LIBRARY_INDEX
        lib_mod.LIBRARY_INDEX = '/fake/index.txt'

        try:
            ia = make_interaction(admin=True)
            run_async(cmd(ia))
            check('defer aufgerufen', ia.response.calls[0].get('type') == 'defer')
            check('followup gesendet', len(ia.followup.calls) > 0)
            content = ia.followup.calls[0].get('content') or ''
            check('Reindex-Ergebnis enthaelt Zahlen',
                  '50' in content and '42' in content)
        finally:
            lib_mod.build_library_catalog = orig_build
            lib_mod._reload_library = orig_reload
            sel_mod.clear_lines_cache = orig_clear
            sel_mod.load_all_lines = orig_load
            lib_mod.LIBRARY_INDEX = orig_index
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_reindex_requires_admin():
    """Nicht-Admins duerfen /reindex nicht ausloesen (Runtime-Guard, nicht nur UI)."""
    print('[/reindex admin-guard]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('reindex')
        check('cmd_reindex gefunden', cmd is not None)
        if not cmd:
            return

        import library as lib_mod
        called = {'build': False}

        def fake_build():
            called['build'] = True
            return (0, 0, 0, 0, 0)

        orig_build = lib_mod.build_library_catalog
        lib_mod.build_library_catalog = fake_build
        try:
            ia = make_interaction(admin=False)
            run_async(cmd(ia))
            content = (ia.response.calls[0].get('content') or '').lower() if ia.response.calls else ''
            check('non-admin /reindex abgelehnt', 'admin' in content)
            check('non-admin /reindex baut Katalog NICHT', not called['build'])
        finally:
            lib_mod.build_library_catalog = orig_build
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_parse_index_entry():
    """Tests fuer _parse_index_entry (library.py)."""
    print('[_parse_index_entry]')
    from library import _parse_index_entry

    # Normaler Eintrag
    result = _parse_index_entry('/data/schach/Kasparov/My Great Predecessors (2003).pdf')
    check('normaler Eintrag', result is not None)
    check('Autor', result[0] == 'Kasparov')
    check('Jahr extrahiert', result[2] == 2003)
    check('Extension', result[3] == 'pdf')

    # Eintrag mit Bracket-Jahr
    result = _parse_index_entry('/data/schach/Author/Title [Other, 1999].epub')
    check('Bracket-Jahr', result is not None and result[2] == 1999)

    # Leere Zeile
    check('leere Zeile → None', _parse_index_entry('') is None)

    # Kein /schach/ Pfad
    check('ohne schach → None', _parse_index_entry('/data/music/file.mp3') is None)

    # Zu wenig Pfadteile
    check('zu kurz → None', _parse_index_entry('/data/schach/file.pdf') is None)

    # Ohne Extension
    check('ohne Ext → None', _parse_index_entry('/data/schach/Author/NoExt') is None)
    print()


def test_auto_tag():
    """Tests fuer _auto_tag (library.py)."""
    print('[_auto_tag]')
    from library import _auto_tag

    # Taktik-Buch
    tags = _auto_tag('1001 Tactical Puzzles', 'Author', 'pdf')
    check('Taktik-Tag', 'Taktik' in tags)
    check('eBook-Tag', 'eBook' in tags)

    # Eroeffnungsbuch
    tags = _auto_tag('The Sicilian Defense', 'Kasparov', 'pgn')
    check('Sizilianisch-Tag', 'Sizilianisch' in tags)
    check('PGN-Tag', 'PGN' in tags)

    # Endspiel (Regex \bendgame\b matcht Singular)
    tags = _auto_tag('Endgame Strategy', 'Mueller', 'epub')
    check('Endspiel-Tag', 'Endspiel' in tags)

    # Ohne Matches
    tags = _auto_tag('Untitled', 'Nobody', 'xyz')
    check('Keine Tags', len(tags) == 0)

    # Deutsche Sprach-Erkennung
    tags = _auto_tag('Chess Book (german)', 'Author', 'pdf')
    check('Deutsch-Tag', 'Deutsch' in tags)
    print()


def test_build_library_catalog():
    """Tests fuer build_library_catalog (library.py)."""
    print('[build_library_catalog]')
    import library

    tmpdir = tempfile.mkdtemp(prefix='lib_test_')
    try:
        index_file = os.path.join(tmpdir, 'index.txt')
        lib_file = os.path.join(tmpdir, 'library.json')

        # Speichere original-Werte
        orig_index = library.LIBRARY_INDEX
        orig_file = library.LIBRARY_FILE

        library.LIBRARY_INDEX = index_file
        library.LIBRARY_FILE = lib_file

        # Ohne index.txt → (0,0,0,0,0)
        library.LIBRARY_INDEX = ''
        result = library.build_library_catalog()
        check('ohne Index → alles 0', result == (0, 0, 0, 0, 0))

        # Mit index.txt
        library.LIBRARY_INDEX = index_file
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write('/data/schach/Kasparov/My Great Predecessors (2003).pdf\n')
            f.write('/data/schach/Mueller/Basic Endgames.epub\n')

        result = library.build_library_catalog()
        check('Dateien gezaehlt', result[0] == 2)
        check('Buecher erstellt', result[1] == 2)
        check('Neue Eintraege', result[2] == 2)

        # Nochmal aufrufen → updates statt neu
        result2 = library.build_library_catalog()
        check('Wiederholung → 0 neue', result2[2] == 0)
        check('Wiederholung → 2 aktualisiert', result2[3] == 2)

    finally:
        library.LIBRARY_INDEX = orig_index
        library.LIBRARY_FILE = orig_file
        shutil.rmtree(tmpdir, ignore_errors=True)
    print()


def test_public_domain_from():
    """publicDomainFrom: Lock-Logik, Sidecar→Katalog-Durchreichung, Embed-🔒."""
    print('[public_domain_from]')
    import library

    orig_enforce = library.LIBRARY_ENFORCE_PD

    # --- Default AUS: nichts gesperrt, auch bei Zukunftsdatum ---
    library.LIBRARY_ENFORCE_PD = False
    check('Enforcement aus → nichts gesperrt', not library._is_locked({'publicDomainFrom': '2999-01-01'}))

    # --- Mit Enforcement: reine Helfer ---
    library.LIBRARY_ENFORCE_PD = True
    check('Zukunftsdatum → gesperrt', library._is_locked({'publicDomainFrom': '2999-01-01'}))
    check('Vergangenheit → frei', not library._is_locked({'publicDomainFrom': '1900-01-01'}))
    check('ohne Feld → frei', not library._is_locked({}))
    check('unparsebar → frei (mit Warnung)', not library._is_locked({'publicDomainFrom': 'kaputt'}))
    check('lock_note enthält Datum', '01.01.2999' in library._lock_note({'publicDomainFrom': '2999-01-01'}))
    check('lock_note leer wenn frei', library._lock_note({'publicDomainFrom': '1900-01-01'}) == '')

    # --- Sidecar-Feld landet im Katalog (unabhängig vom Schalter) ---
    tmpdir = tempfile.mkdtemp(prefix='pd_test_')
    orig_index, orig_file, orig_base = library.LIBRARY_INDEX, library.LIBRARY_FILE, library._LOCAL_BASE
    try:
        index_file = os.path.join(tmpdir, 'index.txt')
        library.LIBRARY_INDEX = index_file
        library.LIBRARY_FILE = os.path.join(tmpdir, 'library.json')
        library._LOCAL_BASE = tmpdir
        bookdir = os.path.join(tmpdir, 'Tartakower')
        os.makedirs(bookdir, exist_ok=True)
        with open(os.path.join(bookdir, 'Some Book.json'), 'w', encoding='utf-8') as f:
            json.dump({'title': 'Some Book', 'author': 'Tartakower',
                       'publicDomainFrom': '2999-01-01'}, f)
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write('/data/schach/Tartakower/Some Book.pdf\n')

        library.build_library_catalog()
        entry = next((e for e in library._load_library() if 'Some Book' in e['title']), None)
        check('Katalog-Eintrag vorhanden', entry is not None)
        check('publicDomainFrom durchgereicht', entry and entry.get('publicDomainFrom') == '2999-01-01')
        check('Katalog-Eintrag gesperrt', entry and library._is_locked(entry))

        # --- Embed markiert gesperrte Bücher mit 🔒 + "frei ab" ---
        emb = library._build_library_embed([entry], 1, 1, 'q')
        check('Embed-Name mit 🔒', '🔒' in emb.fields[0]['name'])
        check('Embed-Wert „frei ab"', 'frei ab' in emb.fields[0]['value'])
    finally:
        library.LIBRARY_INDEX, library.LIBRARY_FILE, library._LOCAL_BASE = orig_index, orig_file, orig_base
        library.LIBRARY_ENFORCE_PD = orig_enforce
        shutil.rmtree(tmpdir, ignore_errors=True)
    print()


def test_sftpgo_password_separated():
    """SFTPGo-Passwort steht NICHT im Link-Block, sondern in einer separaten Nachricht."""
    print('[sftpgo_password_separated]')
    import library

    tmpdir = tempfile.mkdtemp(prefix='sftp_test_')
    orig_base = library._SFTPGO_BASE_URL
    orig_share = library._SFTPGO_SHARE_ID
    orig_pw = library._SFTPGO_SHARE_PASSWORD
    try:
        f = os.path.join(tmpdir, 'book.pdf')
        with open(f, 'wb') as fh:
            fh.write(b'x' * 1024)
        entry = {'title': 'Mega Buch', 'author': 'Autor'}

        library._SFTPGO_BASE_URL = 'https://sftp.example'
        library._SFTPGO_SHARE_ID = 'abc'
        library._SFTPGO_SHARE_PASSWORD = 'geheim123'

        link_msg = library._sftpgo_message(entry, f, 'pdf')
        pw_msg = library._sftpgo_password_message()
        check('Link-Nachricht enthaelt KEIN Passwort', 'geheim123' not in link_msg)
        check('Link-Nachricht verweist auf separate PW-Nachricht', 'separat' in link_msg)
        check('PW-Nachricht enthaelt das Passwort', pw_msg and 'geheim123' in pw_msg)
        check('PW-Nachricht maskiert per Spoiler', pw_msg and '||' in pw_msg)

        # Ohne gesetztes Passwort → keine PW-Nachricht, kein Hinweis
        library._SFTPGO_SHARE_PASSWORD = ''
        link_msg2 = library._sftpgo_message(entry, f, 'pdf')
        check('ohne PW → keine PW-Nachricht', library._sftpgo_password_message() is None)
        check('ohne PW → kein Hinweis im Link', 'separat' not in link_msg2)
    finally:
        library._SFTPGO_BASE_URL = orig_base
        library._SFTPGO_SHARE_ID = orig_share
        library._SFTPGO_SHARE_PASSWORD = orig_pw
        shutil.rmtree(tmpdir, ignore_errors=True)
    print()


def test_pd_lock_share_link():
    """Review W4s S4-022: bei aktiver Gemeinfreiheits-Sperre keinen Share-Link.

    Der SFTPGo-Share deckt die ganze Bibliothek ab; der Browse-Link fuer ein
    FREIES grosses Buch oeffnet mit dem gemeinsamen Passwort den Web-Client, in
    dem man zu jedem gesperrten Buch navigieren kann. Solange der Katalog ein
    gesperrtes Buch enthaelt, darf der Bot den Link deshalb nicht ausgeben."""
    print('[pd_lock_share_link]')
    import library

    tmpdir = tempfile.mkdtemp(prefix='pd_share_')
    orig = (library.LIBRARY_ENFORCE_PD, library.LIBRARY_FILE, library._SFTPGO_BASE_URL,
            library._SFTPGO_SHARE_ID, library._SFTPGO_SHARE_PASSWORD)
    orig_inc = library.stats.inc
    try:
        big = os.path.join(tmpdir, 'frei.pdf')
        with open(big, 'wb') as f:
            f.truncate(9 * 1024 * 1024)   # > 8 MB → Share-Pfad
        free = {'id': 'a--frei', 'title': 'Freies Buch', 'author': 'A',
                'files': [big], 'publicDomainFrom': '1900-01-01'}
        locked = {'id': 'b--gesperrt', 'title': 'Gesperrtes Buch', 'author': 'B',
                  'files': [os.path.join(tmpdir, 'gesperrt.pdf')],
                  'publicDomainFrom': '2999-01-01'}

        def _catalog(entries):
            library.LIBRARY_FILE = os.path.join(tmpdir, 'library.json')
            with open(library.LIBRARY_FILE, 'w', encoding='utf-8') as f:
                json.dump(entries, f)
            library._reload_library()

        def _send(entry):
            ia = make_interaction()
            run_async(library._send_book(ia, entry, big, 'pdf'))
            return ' '.join(str(c.get('content') or '') for c in ia.followup.calls)

        library._SFTPGO_BASE_URL = 'https://sftp.example'
        library._SFTPGO_SHARE_ID = 'share1'
        library._SFTPGO_SHARE_PASSWORD = 'geheim123'
        library.stats.inc = lambda *a, **k: None
        _catalog([free, locked])

        # --- Sperre an + gesperrtes Buch im Katalog: kein Link, kein Passwort ---
        library.LIBRARY_ENFORCE_PD = True
        out = _send(free)
        check('Sperre an: freies grosses Buch bekommt KEINEN Share-Link',
              'pubshares' not in out, out[:200])
        check('Sperre an: kein Share-Passwort', 'geheim123' not in out, out[:200])
        check('Sperre an: Meldung „zu groß“ mit Grund', 'zu groß' in out and 'Sperre' in out,
              out[:200])
        view = library._FormatView(free, {'pdf': big}, {'pdf': 9 * 1024 * 1024})
        btn = view.children[0] if view.children else None
        check('Sperre an: Format-Button ohne 🔗 (kein Link-Stil)',
              btn is not None and '🔗' not in btn.label
              and btn.style is not library.discord.ButtonStyle.success,
              getattr(btn, 'label', None))
        if btn is not None:
            ia = make_interaction()
            run_async(btn.callback(ia))
            out = ' '.join(str(c.get('content') or '')
                           for c in ia.response.calls + ia.followup.calls)
            check('Sperre an: Button-Klick liefert keinen Share-Link',
                  'pubshares' not in out and 'geheim123' not in out, out[:200])

        # --- gesperrtes Buch nur per ignore.json ausgeblendet: liegt trotzdem im Share ---
        orig_excl = library._is_excluded
        try:
            library._is_excluded = lambda e: e['id'] == 'b--gesperrt'
            library._reload_library()
            check('ausgeblendetes gesperrtes Buch zaehlt mit (kein Link)',
                  'pubshares' not in _send(free))
        finally:
            library._is_excluded = orig_excl

        # --- Sperre an, aber nichts (mehr) gesperrt: Link wie bisher ---
        _catalog([free, dict(locked, publicDomainFrom='1901-01-01')])
        check('Sperre an, nichts gesperrt: Share-Link wie bisher', 'pubshares' in _send(free))

        # --- Sperre aus (Default): Link wie bisher, auch mit Zukunftsdatum im Katalog ---
        _catalog([free, locked])
        library.LIBRARY_ENFORCE_PD = False
        out = _send(free)
        check('Sperre aus: Share-Link wie bisher', 'pubshares' in out, out[:200])
        view = library._FormatView(free, {'pdf': big}, {'pdf': 9 * 1024 * 1024})
        check('Sperre aus: Format-Button mit 🔗',
              view.children and '🔗' in view.children[0].label)
    finally:
        (library.LIBRARY_ENFORCE_PD, library.LIBRARY_FILE, library._SFTPGO_BASE_URL,
         library._SFTPGO_SHARE_ID, library._SFTPGO_SHARE_PASSWORD) = orig
        library.stats.inc = orig_inc
        library._reload_library()
        shutil.rmtree(tmpdir, ignore_errors=True)
    print()


def test_library_view_no_loop_io():
    """Review W4s S4-025 (Rest von PD-124): Bibliotheks-Seiten bauen ohne stat im Event-Loop.

    _BookSelect las je Eintrag os.path.isfile/getsize im Konstruktor, und der lief
    im Loop (nach dem to_thread der Suche und bei jedem Vor/Zurueck), ebenso
    _build_library_embed → _collect_formats. Haengt der Bibliotheks-Mount, stand
    der ganze Bot. Hier wirft jeder Datei-stat aus dem Loop-Thread (Hauptthread)."""
    print('[library view no loop io]')
    import threading
    import library as lib_mod

    cmd = _captured_commands.get('bibliothek')
    check('cmd_bibliothek gefunden', cmd is not None)
    if not cmd:
        return
    tmpdir = tempfile.mkdtemp(prefix='lib_loopio_')
    orig_search = lib_mod._search_library
    orig_isfile, orig_getsize = os.path.isfile, os.path.getsize
    orig_sftp = (lib_mod._SFTPGO_BASE_URL, lib_mod._SFTPGO_SHARE_ID)
    orig_base, orig_lstat = lib_mod._LOCAL_BASE, os.lstat
    orig_inc = lib_mod.stats.inc
    loop_calls = []

    def _guard(real, name):
        def _wrapped(p, *a, **kw):
            if threading.current_thread() is threading.main_thread() and str(p).startswith(tmpdir):
                loop_calls.append((name, os.path.basename(str(p))))
            return real(p, *a, **kw)
        return _wrapped

    try:
        entries = []
        for i in range(12):   # 2 Seiten
            f = os.path.join(tmpdir, f'buch{i:02d}.pdf')
            with open(f, 'wb') as fh:
                fh.truncate((i + 1) * 1024 * 1024)
            entries.append({'id': f'b{i}', 'title': f'Buch {i:02d}', 'author': 'A',
                            'tags': [], 'file_type': 'pdf', 'files': [f]})
        lib_mod._search_library = lambda q, limit=25: entries
        os.path.isfile = _guard(orig_isfile, 'isfile')
        os.path.getsize = _guard(orig_getsize, 'getsize')

        ia = make_interaction()
        run_async(cmd(ia, suche='buch'))
        sent = ia.followup.calls[0] if ia.followup.calls else {}
        view, embed = sent.get('view'), sent.get('embed')
        check('/bibliothek: kein Datei-stat im Event-Loop', not loop_calls, str(loop_calls[:4]))
        check('/bibliothek: Embed zeigt Formate (stat lief im Thread)',
              embed is not None and 'PDF' in embed.fields[0]['value'])
        select = next((c for c in getattr(view, 'children', [])
                       if isinstance(c, lib_mod._BookSelect)), None)
        descs = [o.description for o in getattr(select, 'options', [])] if select else []
        check('/bibliothek: Auswahl zeigt weiter die Dateigroesse',
              len(descs) == 10 and '1.0 MB' in descs[0] and '10.0 MB' in descs[9], str(descs[:2]))

        loop_calls.clear()
        ia2 = make_interaction()
        if view is not None:
            run_async(view.next_button(ia2, None))
        edit = ia2.response.calls[0] if ia2.response.calls else {}
        check('Weiter: kein Datei-stat im Event-Loop', not loop_calls, str(loop_calls[:4]))
        select2 = next((c for c in getattr(view, 'children', [])
                        if isinstance(c, lib_mod._BookSelect)), None)
        descs2 = [o.description for o in getattr(select2, 'options', [])] if select2 else []
        check('Weiter: Seite 2 mit Groessen und neuem Embed',
              edit.get('type') == 'edit_message' and len(descs2) == 2 and '11.0 MB' in descs2[0]
              and edit.get('embed') is not None and 'Seite 2/2' in edit['embed'].footer.text,
              str(descs2))
        check('Weiter: genau eine Auswahl in der View',
              sum(isinstance(c, lib_mod._BookSelect) for c in getattr(view, 'children', [])) == 1)

        # Format-Button mit SFTPGo-Link: Groesse kommt aus dem View-Bau, kein getsize im Loop;
        # der Link-Bau (_sftpgo_rel_path -> Path.resolve, ein lstat je Pfadteil) laeuft im Thread.
        lib_mod._SFTPGO_BASE_URL, lib_mod._SFTPGO_SHARE_ID = 'https://sftp.example', 's1'
        lib_mod._LOCAL_BASE = tmpdir
        os.lstat = _guard(orig_lstat, 'lstat')
        lib_mod.stats.inc = lambda *a, **k: None
        big = entries[9]['files'][0]
        fv = lib_mod._FormatView(entries[9], {'pdf': big}, {'pdf': 10 * 1024 * 1024})
        loop_calls.clear()
        ia3 = make_interaction()
        run_async(fv.children[0].callback(ia3))
        msg = str(ia3.response.calls[0].get('content') if ia3.response.calls else '')
        check('SFTPGo-Link per Button: kein getsize/lstat im Event-Loop, Groesse stimmt',
              not loop_calls and 'pubshares' in msg and '10.0 MB' in msg
              and 'path=/buch09.pdf' in msg, f'{loop_calls} {msg[:160]}')
    finally:
        os.path.isfile, os.path.getsize = orig_isfile, orig_getsize
        os.lstat = orig_lstat
        lib_mod._LOCAL_BASE = orig_base
        lib_mod._search_library = orig_search
        lib_mod._SFTPGO_BASE_URL, lib_mod._SFTPGO_SHARE_ID = orig_sftp
        lib_mod.stats.inc = orig_inc
        shutil.rmtree(tmpdir, ignore_errors=True)
    print()


def test_library_view_page_race():
    """Review W4s S4-025 (Nacharbeit): schnelle Klicks auf Weiter/Zurueck ueberholen sich nicht.

    Seit _library_page im Thread laeuft, gibt jeder Klick den Loop frei; discord.py startet
    je Klick einen eigenen Task ohne Sperre je View. Setzte der Klick self.current VOR dem
    await, las _update_select danach den Index des spaeteren Klicks: Embed von Seite 2,
    Auswahl mit den Buechern von Seite 3 und den Groessen von Seite 2. Hier ist der Thread
    fuer Seite 2 langsam, zwei Klicks laufen nebenlaeufig."""
    print('[library view page race]')
    import time
    import library as lib_mod

    tmpdir = tempfile.mkdtemp(prefix='lib_race_')
    orig_sizes = lib_mod._first_file_sizes
    try:
        entries = []
        for i in range(25):   # 3 Seiten: 10 / 10 / 5
            f = os.path.join(tmpdir, f'r{i:02d}.pdf')
            with open(f, 'wb') as fh:
                fh.truncate((i + 1) * 1024 * 1024)
            entries.append({'id': f'r{i}', 'title': f'Race {i:02d}', 'author': 'A',
                            'tags': [], 'file_type': 'pdf', 'files': [f]})
        pages = [entries[i:i + 10] for i in range(0, len(entries), 10)]
        first_sizes = orig_sizes(pages[0])

        def _slow_page2(ents):
            if ents and ents[0]['id'] == 'r10':
                time.sleep(0.3)
            return orig_sizes(ents)
        lib_mod._first_file_sizes = _slow_page2

        for steps, want_page in (((1, 1), 3), ((1, -1), 1)):
            label = '+'.join('Weiter' if st > 0 else 'Zurueck' for st in steps)
            view = lib_mod.LibraryPaginationView(pages, query='race', sizes=first_sizes)
            edits = []   # (Embed-Seite, Embed-Titel, Auswahl-Labels, Auswahl-Beschreibungen)

            def _ia():
                ia = make_interaction()
                orig_edit = ia.response.edit_message

                async def _edit(**kw):
                    # Stand im Moment des Edits festhalten (discord.py serialisiert die View hier)
                    emb, v = kw.get('embed'), kw.get('view')
                    sel = next((c for c in v.children if isinstance(c, lib_mod._BookSelect)), None)
                    foot = emb.footer.text if emb is not None and emb.footer else ''
                    edits.append((foot, [fl['name'] for fl in emb.fields],
                                  [o.label for o in sel.options] if sel else [],
                                  [o.description for o in sel.options] if sel else []))
                    await orig_edit(**kw)
                ia.response.edit_message = _edit
                return ia

            ias = [_ia() for _ in steps]

            async def _clicks():
                btn = {1: view.next_button, -1: view.prev_button}
                await asyncio.gather(*(btn[st](ia, None) for st, ia in zip(steps, ias)))
            run_async(_clicks())

            check(f'{label}: jeder Klick beantwortet',
                  all(len(ia.response.calls) == 1 for ia in ias) and len(edits) == len(steps),
                  str([ia.response.calls for ia in ias]))
            consistent = True
            for foot, names, labels, descs in edits:
                shown = int(foot.split()[1].split('/')[0]) - 1 if foot else -1
                page = pages[shown] if 0 <= shown < len(pages) else []
                want_labels = [e['title'] for e in page]
                want_mb = [f'{(int(e["id"][1:]) + 1):.1f} MB' for e in page]
                if (labels != want_labels or len(names) != len(page)
                        or any(t not in n for t, n in zip(want_labels, names))
                        or len(descs) != len(want_mb)
                        or any(mb not in d for mb, d in zip(want_mb, descs))):
                    consistent = False
            check(f'{label}: Auswahl (Buecher + Groessen) passt in jedem Edit zur Embed-Seite',
                  consistent, str([(f, l[:2], d[:2]) for f, _, l, d in edits]))
            last = edits[-1][0] if edits else ''
            check(f'{label}: letzter Edit zeigt Seite {want_page}/3, view.current passt',
                  last == f'Seite {want_page}/3' and view.current == want_page - 1,
                  f'{last!r} current={view.current}')
            check(f'{label}: genau eine Auswahl in der View',
                  sum(isinstance(c, lib_mod._BookSelect) for c in view.children) == 1)
    finally:
        lib_mod._first_file_sizes = orig_sizes
        shutil.rmtree(tmpdir, ignore_errors=True)
    print()


def test_library_cache_threadsafe():
    """Bug-First: _ensure_library darf bei nebenläufigen Aufrufen (asyncio.to_thread liest aus
    mehreren Worker-Threads) NUR EINMAL laden und einen konsistenten Cache liefern — ohne Lock
    baut ein Race einen teilgefüllten Cache. Deckt den Lock in library._ensure_library ab."""
    print('[library cache threadsafe]')
    import threading
    import time
    import library as lib_mod

    orig_load = lib_mod._load_library
    orig_excl = lib_mod._is_excluded
    try:
        calls = {'n': 0}
        lock = threading.Lock()

        def _slow_load():
            with lock:
                calls['n'] += 1
            time.sleep(0.05)   # Fenster für die Race
            return [{'id': f'b{i}', 'title': f'B{i}'} for i in range(5)]

        lib_mod._load_library = _slow_load
        lib_mod._is_excluded = lambda e: False
        lib_mod._reload_library()   # Cache invalidieren (loaded=False)

        results = []
        rlock = threading.Lock()

        def _worker():
            r = lib_mod._ensure_library()
            with rlock:
                results.append(r)

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        check('nur EINMAL geladen trotz 8 nebenläufiger Aufrufe', calls['n'] == 1)
        check('alle Aufrufe liefern denselben Cache', all(r is results[0] for r in results))
        check('Cache vollständig (5 Einträge)', len(results[0]) == 5)
    finally:
        lib_mod._load_library = orig_load
        lib_mod._is_excluded = orig_excl
        lib_mod._reload_library()
    print()


def test_format_view_missing_file():
    """_FormatView darf nicht crashen (und nicht den Event-Loop blockieren),
    wenn eine Buchdatei zwischen _collect_formats und View-Bau verschwindet —
    genau das Szenario, das library.py selbst als real dokumentiert."""
    print('[_FormatView missing file]')
    import library as lib_mod

    entry = {'title': 'Test', 'author': 'A', 'files': [], 'tags': []}
    try:
        view = lib_mod._FormatView(entry, {'pdf': '/nonexistent/dir/gone.pdf'})
        check('View-Bau ohne Datei crasht nicht', True)
        check('Button vorhanden', len(getattr(view, 'children', [])) == 1)
    except OSError as e:
        check('View-Bau ohne Datei crasht nicht', False, f'OSError: {e}')
    print()


# ---------------------------------------------------------------------------
# Charakterisierung (Vorarbeit Zerlegung library.py, Review W1 S4-017)
# ---------------------------------------------------------------------------
# Golden fuer die Katalog-Seite (index.txt-Parsing, Gruppierung, Sidecar,
# Auto-Tags, Update/Entfernen, ignore.json, Suche): library.json muss bei der
# spaeteren Aufteilung in library/catalog.py & Co. byte-gleich bleiben.

_GOLDEN_INDEX = [
    '/data/schach/Kasparov, Garry/My Great Predecessors (2003).epub',
    '/data/schach/Kasparov, Garry/My Great Predecessors (2003).pdf',
    '/data/schach/Silman/Complete Endgame Course [Siles Press, 2007].djvu',
    '/data/schach/Mueller/Sicilian Attack - Disc 2.mp4',
    '/data/schach/Mueller/Sicilian Attack - Disc 1.mp4',
    '/data/schach/Tartakower/Some Book.pdf',
    '/data/schach/Unknown/Chess Tactics for Kids 1999.pdf',
    '/data/schach/Murray Chandler/Chess Tactics for Kids 1999.pdf',
    '/data/schach/Privat/secret.pgn',
    '/data/schach/Nunn/Understanding Chess Endgames (German).pdf',
    '/data/other/Fremd/x.pdf',                                              # kein /schach/
    '/data/schach/NoExt/README',                                            # ohne Endung
    '/data/schach/toplevel.pdf',                                            # ohne Autor-Ordner
    '/data/schach/Silman/Complete Endgame Course [Siles Press, 2007].djvu',  # Duplikat
    '',
]

_GOLDEN_LIBRARY = [
    {'id': 'kasparov garry--my great predecessors', 'title': 'My Great Predecessors',
     'author': 'Kasparov, Garry', 'year': 2003, 'tags': ['eBook'], 'note': 'bleibt',
     'manual_tags': [], 'file_type': 'pdf', 'publicDomainFrom': None,
     'files': ['/data/schach/Kasparov, Garry/My Great Predecessors (2003).pdf',
               '/data/schach/Kasparov, Garry/My Great Predecessors (2003).epub']},
    {'id': 'mueller--sicilian attack', 'title': 'Sicilian Attack', 'author': 'Mueller',
     'year': None, 'tags': ['Sizilianisch', 'Angriff', 'Video'], 'manual_tags': [],
     'file_type': 'mp4', 'publicDomainFrom': None,
     'files': ['/data/schach/Mueller/Sicilian Attack - Disc 2.mp4',
               '/data/schach/Mueller/Sicilian Attack - Disc 1.mp4']},
    {'id': 'nunn--understanding chess endgames german',
     'title': 'Understanding Chess Endgames (German)', 'author': 'Nunn', 'year': None,
     'tags': ['eBook', 'Deutsch'], 'manual_tags': [], 'file_type': 'pdf',
     'publicDomainFrom': None,
     'files': ['/data/schach/Nunn/Understanding Chess Endgames (German).pdf']},
    {'id': 'privat--secret', 'title': 'secret', 'author': 'Privat', 'year': None,
     'tags': ['PGN'], 'manual_tags': [], 'file_type': 'pgn', 'publicDomainFrom': None,
     'files': ['/data/schach/Privat/secret.pgn']},
    {'id': 'savielly tartakower julius du mont--some book', 'title': 'Best Games',
     'author': 'Savielly Tartakower, Julius du Mont', 'year': 1950,
     'tags': ['Klassiker', 'eBook'], 'manual_tags': ['Klassiker'], 'file_type': 'pdf',
     'targetMinElo': 1600, 'favorite': [42], 'size': 123, 'publicDomainFrom': '2027-01-01',
     'files': ['/data/schach/Tartakower/Some Book.pdf']},
    {'id': 'silman--complete endgame course', 'title': 'Complete Endgame Course',
     'author': 'Silman', 'year': 2007, 'tags': ['Endspiel', 'eBook'], 'manual_tags': [],
     'file_type': 'djvu', 'publicDomainFrom': None,
     'files': ['/data/schach/Silman/Complete Endgame Course [Siles Press, 2007].djvu']},
    {'id': 'unknown--chess tactics for kids 1999', 'title': 'Chess Tactics for Kids 1999',
     'author': 'Unknown', 'year': 1999, 'tags': ['Taktik', 'eBook'], 'manual_tags': [],
     'file_type': 'pdf', 'publicDomainFrom': None,
     'files': ['/data/schach/Unknown/Chess Tactics for Kids 1999.pdf',
               '/data/schach/Murray Chandler/Chess Tactics for Kids 1999.pdf']},
]


def test_library_catalog_golden():
    """Golden: library.json aus fester index.txt + Sidecar + ignore.json, danach Suche."""
    print('[library_catalog_golden]')
    import library

    tmpdir = tempfile.mkdtemp(prefix='lib_golden_')
    orig = (library.LIBRARY_INDEX, library.LIBRARY_FILE, library._LOCAL_BASE)
    try:
        library.LIBRARY_INDEX = os.path.join(tmpdir, 'index.txt')
        library.LIBRARY_FILE = os.path.join(tmpdir, 'library.json')
        library._LOCAL_BASE = tmpdir
        os.makedirs(os.path.join(tmpdir, 'Tartakower'))
        with open(os.path.join(tmpdir, 'Tartakower', 'Some Book.json'), 'w', encoding='utf-8') as f:
            json.dump({'title': 'Best Games', 'author': ['Savielly Tartakower', 'Julius du Mont'],
                       'year': 1950, 'tags': ['Klassiker'], 'targetMinElo': 1600,
                       'favorite': [42], 'size': 123, 'publicDomainFrom': '2027-01-01'}, f)
        os.makedirs(os.path.join(tmpdir, 'Privat'))
        with open(os.path.join(tmpdir, 'Privat', 'ignore.json'), 'w', encoding='utf-8') as f:
            json.dump(['*.pgn'], f)
        with open(library.LIBRARY_INDEX, 'w', encoding='utf-8') as f:
            f.write('\n'.join(_GOLDEN_INDEX) + '\n')
        # Alter Katalog: ein Eintrag wird aktualisiert (Zusatzfeld bleibt), einer entfernt
        with open(library.LIBRARY_FILE, 'w', encoding='utf-8') as f:
            json.dump([
                {'id': 'kasparov garry--my great predecessors', 'title': 'alt',
                 'author': 'Kasparov, Garry', 'year': 1999, 'tags': ['alt'], 'note': 'bleibt'},
                {'id': 'weg--nicht mehr da', 'title': 'Weg', 'author': 'Weg',
                 'files': ['/data/schach/Weg/x.pdf']},
            ], f)
        library._reload_library()

        result = library.build_library_catalog()
        check('golden: (dateien, buecher, neu, aktualisiert, entfernt)',
              result == (13, 7, 6, 1, 1), detail=str(result))
        with open(library.LIBRARY_FILE, encoding='utf-8') as f:
            written = f.read()
        check('golden: library.json byte-gleich',
              written == json.dumps(_GOLDEN_LIBRARY, ensure_ascii=False, indent=2),
              detail=written[:400])

        # ignore.json blendet aus der Suche aus, library.json bleibt vollstaendig
        library._reload_library()
        ids = [e['id'] for e in library._ensure_library()]
        check('ignore.json: *.pgn im Ordner Privat ausgeblendet',
              'privat--secret' not in ids and len(ids) == 6, detail=str(ids))
        check('Tags ohne ausgeblendete Eintraege',
              library._all_tags() == ['Angriff', 'Deutsch', 'Endspiel', 'Klassiker',
                                      'Sizilianisch', 'Taktik', 'Video', 'eBook'],
              detail=str(library._all_tags()))
        check('Autoren sortiert',
              library._all_authors() == ['Kasparov, Garry', 'Mueller', 'Nunn',
                                         'Savielly Tartakower, Julius du Mont', 'Silman',
                                         'Unknown'],
              detail=str(library._all_authors()))

        def _ids(q):
            return [e['id'] for e in library._search_library(q)]

        check('Suche: sicilian', _ids('sicilian') == ['mueller--sicilian attack'])
        check('Suche: endgame (Gleichstand → Autor)',
              _ids('endgame') == ['nunn--understanding chess endgames german',
                                  'silman--complete endgame course'], detail=str(_ids('endgame')))
        check('Suche: alle Woerter muessen passen',
              _ids('chess tactics') == ['unknown--chess tactics for kids 1999'])
        check('Suche: ueber Autor', _ids('kasparov') == ['kasparov garry--my great predecessors'])
        check('Suche: ausgeblendet → nichts', _ids('secret') == [])
        check('Suche: nur Satzzeichen → nichts', _ids('!!') == [])
    finally:
        library.LIBRARY_INDEX, library.LIBRARY_FILE, library._LOCAL_BASE = orig
        library._reload_library()
        shutil.rmtree(tmpdir, ignore_errors=True)
    print()
