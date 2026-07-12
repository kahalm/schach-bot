"""Tests fuer Library Commands: /bibliothek, /tag, /autor, /reindex, parse, auto-tag, catalog."""

import os
import json
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
        lib_mod.LibraryPaginationView = lambda pages, query: FakeView()

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
        lib_mod.LibraryPaginationView = lambda pages, query: FakeView()

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
        lib_mod.LibraryPaginationView = lambda pages, query: FakeView()

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
