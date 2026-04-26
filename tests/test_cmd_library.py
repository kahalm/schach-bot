"""Tests fuer Library Commands: /bibliothek, /tag, /autor, /reindex, parse, auto-tag, catalog."""

import os
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
