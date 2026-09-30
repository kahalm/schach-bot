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
    """/help wird aus den registrierten Befehlen generiert (S4-013): Spiegeltest Registrierung ↔
    Hilfe, abgeloeste Stubs ausgeblendet und parameterlos, Begruessung ohne tote Befehle."""
    print('[/help]')
    import re
    import commands.help as help_mod
    tmpdir = setup_temp_config()
    try:
        meta = dict(h._captured_meta)
        check('Befehle erfasst (>= 40)', len(meta) >= 40, str(len(meta)))

        # 1) Jeder Befehl traegt einen gueltigen Bereich (None = bewusst ausgeblendet).
        bad = sorted(n for n, c in meta.items()
                     if 'help' not in c.extras
                     or (c.extras['help'] is not None and c.extras['help'] not in help_mod.BEREICHE))
        check('jeder Befehl hat extras[help] mit gueltigem Bereich', not bad, str(bad))

        # 2) Abgeloeste Stubs: nicht in /help, ohne Parameter.
        for stub in ('blind', 'train', 'next'):
            c = meta.get(stub)
            check(f'/{stub} registriert (Hinweis-Stub)', c is not None)
            if c is not None:
                check(f'/{stub} ausgeblendet', c.extras.get('help') is None)
                check(f'/{stub} parameterlos', c.parameters == [],
                      str([p.name for p in c.parameters]))

        # 3) Spiegel: Nicht-Admin-Hilfe == alle sichtbaren Nicht-Admin-Befehle, Admin-Hilfe ==
        #    alle Admin-Befehle; kein Eintrag ohne Registrierung.
        def _names(is_admin, areas):
            out = []
            for b in areas:
                out += [sig.split()[0][1:] for sig, _ in _help_fields_fn(b, is_admin)[1]]
            return out
        user_areas = [b for b in help_mod.BEREICHE if b != 'admin']
        user_help = _names(False, user_areas)
        expected_user = sorted(n for n, c in meta.items()
                               if c.extras.get('help') not in (None, 'admin'))
        check('Nicht-Admin-Hilfe = sichtbare Nicht-Admin-Befehle',
              sorted(user_help) == expected_user,
              str(set(user_help) ^ set(expected_user)))
        check('kein Befehl doppelt in der Hilfe', len(user_help) == len(set(user_help)))
        admin_help = _names(True, ['admin'])
        expected_admin = sorted(n for n, c in meta.items() if c.extras.get('help') == 'admin')
        check('Admin-Hilfe = Admin-Befehle', sorted(admin_help) == expected_admin,
              str(set(admin_help) ^ set(expected_admin)))
        for n in ('randompuzzle', 'blindpuzzle', 'bestenliste', 'reindex'):
            check(f'/{n} steht in der Hilfe', n in user_help + admin_help)
        for n in ('blind', 'train', 'next'):
            check(f'/{n} steht nicht in der Hilfe', n not in user_help + admin_help)
        check('/stats nur im Admin-Bereich', 'stats' in admin_help and 'stats' not in user_help)

        # Beschreibung + Parameter kommen aus der Registrierung.
        fields = dict(_help_fields_fn('puzzle', False)[1])
        puzzle_field = next((v for k, v in fields.items() if k.startswith('/puzzle ')), '')
        check('/puzzle-Eintrag nennt Beschreibung', meta['puzzle'].description in puzzle_field)
        check('/puzzle-Eintrag nennt Parameter anzahl', '`anzahl` —' in puzzle_field, puzzle_field)

        # 4) Bereiche ohne Rechte/unbekannt → leer.
        check('kein Bereich → leer', _help_fields_fn('', False) == ('', []))
        check('unbekannter Bereich → leer', _help_fields_fn('nonsense', False) == ('', []))
        check('admin ohne Admin → leer', _help_fields_fn('admin', False) == ('', []))
        title, fields = _help_fields_fn('admin', True)
        check('admin mit Admin → Titel', 'Admin' in title)

        # 5) Discord-Limits je Bereich (25 Felder, 6000 Zeichen, 1024 je Feld).
        for b in help_mod.BEREICHE:
            title, fields = _help_fields_fn(b, True)
            size = len(title) + sum(len(k) + len(v) for k, v in fields)
            check(f'Bereich {b} innerhalb der Embed-Limits',
                  len(fields) <= 25 and size <= 5800 and all(len(v) <= 1024 for _, v in fields),
                  f'{len(fields)} Felder, {size} Zeichen')

        # 6) /help ausfuehren: Uebersicht ohne Admin-Bereich fuer normale User.
        cmd = _captured_commands.get('help')
        check('cmd_help gefunden', cmd is not None)
        ia = make_interaction(admin=False)
        run_async(cmd(ia, bereich=''))
        embed = ia.response.calls[0].get('embed')
        names = [f['name'] for f in embed.fields] if embed else []
        check('Uebersicht: 4 Bereiche fuer normale User', len(names) == 4, str(names))
        check('Uebersicht: kein Admin-Bereich', not any('admin' in n for n in names))
        overview = ' '.join(f['value'] for f in embed.fields) if embed else ''
        check('Uebersicht ohne /train, /next, /blind',
              not re.search(r'`/(train|next|blind)`', overview), overview)
        ia = make_interaction(admin=True)
        run_async(cmd(ia, bereich=''))
        embed = ia.response.calls[0].get('embed')
        check('Uebersicht: Admin sieht Admin-Bereich',
              embed is not None and any('admin' in f['name'] for f in embed.fields))
        ia = make_interaction(admin=False)
        run_async(cmd(ia, bereich='xyz'))
        content = ia.response.calls[0].get('content') or ''
        check('unbekannter Bereich → Liste ohne admin',
              'Unbekannter Bereich' in content and '`puzzle`' in content and 'admin' not in content,
              content)

        # 7) Begruessung: keine abgeloesten/Admin-Befehle, nur registrierte.
        welcome = bot_mod.WELCOME_MESSAGE
        mentioned = re.findall(r'`/([\w-]+)`', welcome)
        check('Begruessung nennt Befehle', len(mentioned) >= 10, str(mentioned))
        for n in ('blind', 'train', 'next', 'stats'):
            check(f'Begruessung ohne /{n}', n not in mentioned)
        dead = [n for n in mentioned
                if n not in meta or meta[n].extras.get('help') in (None, 'admin')]
        check('Begruessung nennt nur sichtbare Nicht-Admin-Befehle', not dead, str(dead))
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
