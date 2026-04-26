"""Tests fuer Info/Infra Commands: /help, /version, /release-notes, event_log, healthcheck."""

import os
import sys
import json
import shutil
import subprocess

import test_helpers as h
from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    make_interaction, _captured_commands, _help_fields_fn,
    bot_mod, parent_dir,
)
import core.version


def test_help():
    """Tests fuer /help Command."""
    print('[/help]')
    tmpdir = setup_temp_config()
    try:
        # Test: Uebersicht (kein Bereich)
        title, fields = _help_fields_fn('', False)
        check('kein Bereich → leerer Titel', title == '')
        check('kein Bereich → keine Felder', fields == [])

        # Test: Bereich puzzle
        title, fields = _help_fields_fn('puzzle', False)
        check('Bereich puzzle → Titel', 'Puzzles' in title)
        check('Bereich puzzle → hat Felder', len(fields) > 0)

        # Test: Bereich bibliothek
        title, fields = _help_fields_fn('bibliothek', False)
        check('Bereich bibliothek → Titel', 'Bibliothek' in title)

        # Test: Bereich community
        title, fields = _help_fields_fn('community', False)
        check('Bereich community → Titel', 'Community' in title)

        # Test: Bereich info
        title, fields = _help_fields_fn('info', False)
        check('Bereich info → Titel', 'Info' in title)

        # Test: unbekannter Bereich
        title, fields = _help_fields_fn('nonsense', False)
        check('unbekannter Bereich → leer', title == '' and fields == [])

        # Test: Admin-Bereich ohne Admin
        title, fields = _help_fields_fn('admin', False)
        check('admin ohne Admin → leer', title == '' and fields == [])

        # Test: Admin-Bereich mit Admin
        title, fields = _help_fields_fn('admin', True)
        check('admin mit Admin → Titel', 'Admin' in title)
        check('admin mit Admin → hat Felder', len(fields) > 0)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_version():
    """Tests fuer /version Command."""
    print('[/version]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('version')
        check('cmd_version gefunden', cmd is not None)
        if not cmd:
            return

        ia = make_interaction()
        run_async(cmd(ia))

        check('send_message aufgerufen', len(ia.response.calls) == 1)
        call = ia.response.calls[0]
        check('enthaelt Version',
              core.version.VERSION in (call.get('content') or ''))
        check('ephemeral', call.get('ephemeral') is True)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_release_notes():
    """Tests fuer /release-notes Command."""
    print('[/release-notes]')
    tmpdir = setup_temp_config()
    try:
        cmd = _captured_commands.get('release-notes')
        check('cmd_release_notes gefunden', cmd is not None)
        if not cmd:
            return

        # Test: Standard (letzte 3 Versionen)
        ia = make_interaction()
        run_async(cmd(ia, version=None, anzahl=3))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('Standard → Embed', embed is not None)
        check('Standard → hat Felder', embed is not None and len(embed.fields) > 0)
        check('Standard → max 3 Felder', embed is not None and len(embed.fields) <= 3)

        # Test: bestimmte Version
        ia = make_interaction()
        run_async(cmd(ia, version='1.0.0', anzahl=3))
        call = ia.response.calls[0]
        embed = call.get('embed')
        check('Version 1.0.0 → Embed', embed is not None)
        check('Version 1.0.0 → 1 Feld',
              embed is not None and len(embed.fields) == 1)

        # Test: nicht existierende Version
        ia = make_interaction()
        run_async(cmd(ia, version='99.99.99', anzahl=3))
        content = (ia.response.calls[0].get('content') or '').lower()
        check('Version nicht gefunden', 'nicht im changelog' in content)
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_event_log():
    """Tests fuer core/event_log.py rotate_log Atomizitaet."""
    print('[event_log]')
    tmpdir = setup_temp_config()
    try:
        import core.event_log as elog
        old_file = elog.REACTION_LOG_FILE
        elog.REACTION_LOG_FILE = os.path.join(tmpdir, 'reaction_log.jsonl')
        old_max = elog._MAX_LOG_LINES
        elog._MAX_LOG_LINES = 5  # klein halten

        try:
            # 8 Zeilen schreiben → rotate soll auf 5 kuerzen
            for i in range(8):
                elog.log_reaction(user_id=i, line_id=f'test:{i}',
                                 mode='normal', emoji='✅', delta=1)
            elog.rotate_log()

            with open(elog.REACTION_LOG_FILE, encoding='utf-8') as f:
                after = [l for l in f if l.strip()]
            check('rotate kuerzt auf MAX', len(after) == 5)

            # Pruefe dass die neuesten 5 erhalten sind (line_id test:3..test:7)
            ids = [json.loads(l)['line_id'] for l in after]
            check('rotate behaelt neueste', ids[0] == 'test:3')
            check('rotate behaelt letzte', ids[-1] == 'test:7')
        finally:
            elog.REACTION_LOG_FILE = old_file
            elog._MAX_LOG_LINES = old_max
    finally:
        teardown_temp_config(tmpdir)
    print()


def test_healthcheck():
    """Tests fuer _write_health() und healthcheck.py."""
    print('[healthcheck]')
    tmpdir = setup_temp_config()
    try:
        import bot as bot_mod
        old_health = bot_mod.HEALTH_FILE
        bot_mod.HEALTH_FILE = os.path.join(tmpdir, 'health.json')

        # Mock bot.latency (Klassenattribut, ueberschreibbar)
        old_latency = bot_mod.bot.latency
        bot_mod.bot.latency = 0.042

        # Test: _write_health erzeugt gueltige JSON
        bot_mod._write_health()
        check('health.json existiert', os.path.exists(bot_mod.HEALTH_FILE))

        with open(bot_mod.HEALTH_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        check('health status=ok', data.get('status') == 'ok')
        check('health version', data.get('version') == core.version.VERSION)
        check('health latency_ms', data.get('latency_ms') == 42)
        check('health guilds ist int', isinstance(data.get('guilds'), int))
        check('health ts vorhanden', 'ts' in data)

        # Test: healthcheck.py Exit 0 bei frischer Datei
        # healthcheck.py liest config/health.json relativ zum cwd
        hc_path = os.path.join(parent_dir, 'healthcheck.py')
        # health.json ins richtige Unterverz. kopieren
        hc_dir = os.path.join(tmpdir, 'config')
        os.makedirs(hc_dir, exist_ok=True)
        shutil.copy2(bot_mod.HEALTH_FILE, os.path.join(hc_dir, 'health.json'))
        result = subprocess.run(
            [sys.executable, hc_path],
            cwd=tmpdir,
            capture_output=True, text=True, timeout=5,
        )
        check('healthcheck exit 0 (frisch)', result.returncode == 0,
              result.stdout.strip())

        # Test: healthcheck.py Exit 1 bei stale Datei
        hf = os.path.join(hc_dir, 'health.json')
        with open(hf, 'w', encoding='utf-8') as f:
            json.dump({'status': 'ok', 'ts': '2020-01-01T00:00:00+00:00'}, f)
        result = subprocess.run(
            [sys.executable, hc_path],
            cwd=tmpdir,
            capture_output=True, text=True, timeout=5,
        )
        check('healthcheck exit 1 (stale)', result.returncode == 1,
              result.stdout.strip())

        # Test: healthcheck.py Exit 1 bei fehlender Datei
        os.remove(hf)
        result = subprocess.run(
            [sys.executable, hc_path],
            cwd=tmpdir,
            capture_output=True, text=True, timeout=5,
        )
        check('healthcheck exit 1 (missing)', result.returncode == 1,
              result.stdout.strip())

        bot_mod.HEALTH_FILE = old_health
        bot_mod.bot.latency = old_latency
    finally:
        teardown_temp_config(tmpdir)
    print()
