"""Slash-Command /test – Diagnose-Modi fuer Bot-Health, Files, PGN, Lichess, Rendering, Assets und Snapshots."""

import asyncio
import json
import logging
import os
import re
import io
from datetime import datetime, timezone
from typing import NamedTuple

import chess
import chess.pgn
import discord

from core.json_store import atomic_read
from core.paths import CONFIG_DIR
from core.permissions import is_privileged
from core.version import VERSION, START_TIME, EMBED_COLOR
from puzzle.selection import find_line_by_id
from puzzle.processing import (
    _trim_to_training_position, _strip_pgn_annotations, _prelude_pgn,
    _flatten_null_move_variations,
)
from puzzle.embed import build_puzzle_embed
from puzzle.rendering import _render_board
from puzzle.state import _load_books_config
from puzzle.lichess import upload_to_lichess
from puzzle.posting import _lichess_executor

log = logging.getLogger('schach-bot')

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(_ROOT, 'books')
SNAPSHOTS_FILE = os.path.join(_ROOT, 'tests', 'trim_snapshots.json')


# ---------------------------------------------------------------------------
# CheckResult + Embed-Builder
# ---------------------------------------------------------------------------

class CheckResult(NamedTuple):
    name: str
    ok: bool
    detail: str


def _build_result_embed(title: str, checks: list[CheckResult]) -> discord.Embed:
    """Baut ein gruenes/rotes Embed aus einer Liste von CheckResults."""
    ok_count = sum(1 for c in checks if c.ok)
    total = len(checks)
    all_ok = ok_count == total
    colour = EMBED_COLOR if all_ok else 0xe74c3c

    embed = discord.Embed(title=title, colour=colour)
    for c in checks[:25]:  # Discord max 25 Fields
        icon = '\u2705' if c.ok else '\u274c'
        embed.add_field(name=f'{icon} {c.name}', value=c.detail or '\u200b', inline=False)
    embed.set_footer(text=f'{ok_count}/{total} OK')
    return embed


# ---------------------------------------------------------------------------
# Modus: status — Bot-Vitals
# ---------------------------------------------------------------------------

def _run_status(bot) -> list[CheckResult]:
    checks = []

    # Latenz
    latency_ms = round(bot.latency * 1000) if bot.latency else 0
    checks.append(CheckResult(
        'Latenz', latency_ms < 500,
        f'{latency_ms} ms'))

    # Guilds
    guild_count = len(bot.guilds)
    checks.append(CheckResult(
        'Guilds', guild_count >= 1,
        str(guild_count)))

    # Uptime
    now = datetime.now(timezone.utc)
    delta = now - START_TIME
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    checks.append(CheckResult(
        'Uptime', True,
        f'{hours}h {minutes}m'))

    # Version
    checks.append(CheckResult('Version', True, VERSION))

    # Task-Loops
    task_loops = getattr(bot, '_task_loops', {})
    for name, loop in sorted(task_loops.items()):
        running = False
        try:
            running = loop.is_running()
        except Exception:
            pass
        checks.append(CheckResult(
            f'Loop: {name}', running,
            'running' if running else 'stopped'))

    return checks


# ---------------------------------------------------------------------------
# Modus: files — JSON-Integritaet
# ---------------------------------------------------------------------------

def _run_files() -> list[CheckResult]:
    checks = []

    # Alle *.json in config/
    if not os.path.isdir(CONFIG_DIR):
        checks.append(CheckResult('config/', True, 'Verzeichnis existiert nicht (OK, leer)'))
        return checks

    json_files = sorted(f for f in os.listdir(CONFIG_DIR) if f.endswith('.json'))
    for fname in json_files:
        path = os.path.join(CONFIG_DIR, fname)
        try:
            data = atomic_read(path)
            if isinstance(data, dict):
                detail = f'{len(data)} Keys'
            elif isinstance(data, list):
                detail = f'{len(data)} Eintraege'
            else:
                detail = type(data).__name__
            checks.append(CheckResult(fname, True, detail))
        except Exception as e:
            checks.append(CheckResult(fname, False, str(e)))

    # reaction_log.jsonl
    from core.event_log import REACTION_LOG_FILE
    jsonl_path = REACTION_LOG_FILE
    if os.path.exists(jsonl_path):
        try:
            with open(jsonl_path, encoding='utf-8') as f:
                lines = f.readlines()
            line_count = len(lines)
            # Letzte nicht-leere Zeile pruefen
            last_valid = False
            for line in reversed(lines):
                line = line.strip()
                if line:
                    json.loads(line)
                    last_valid = True
                    break
            checks.append(CheckResult(
                'reaction_log.jsonl', last_valid,
                f'{line_count} Zeilen'))
        except json.JSONDecodeError:
            checks.append(CheckResult(
                'reaction_log.jsonl', False,
                f'{line_count} Zeilen, letzte Zeile ungueltig'))
        except Exception as e:
            checks.append(CheckResult('reaction_log.jsonl', False, str(e)))
    else:
        checks.append(CheckResult('reaction_log.jsonl', True, 'nicht vorhanden (OK)'))

    return checks


# ---------------------------------------------------------------------------
# Modus: pgn — PGN-Dateien pruefen
# ---------------------------------------------------------------------------

def _run_pgn() -> list[CheckResult]:
    checks = []

    books_config = _load_books_config()
    config_keys = set(books_config.keys())

    if not os.path.isdir(BOOKS_DIR):
        checks.append(CheckResult('books/', False, 'Verzeichnis nicht gefunden'))
        return checks

    pgn_files = sorted(f for f in os.listdir(BOOKS_DIR) if f.endswith('.pgn'))
    pgn_set = set(pgn_files)

    # Abgleich books.json vs Dateien
    missing_files = config_keys - pgn_set
    extra_files = pgn_set - config_keys
    if missing_files:
        checks.append(CheckResult(
            'books.json Abgleich', False,
            f'In books.json aber keine Datei: {", ".join(sorted(missing_files))}'))
    if extra_files:
        checks.append(CheckResult(
            'books.json Abgleich', False,
            f'Datei ohne books.json-Eintrag: {", ".join(sorted(extra_files))}'))
    if not missing_files and not extra_files:
        checks.append(CheckResult(
            'books.json Abgleich', True,
            f'{len(pgn_files)} Dateien = {len(config_keys)} Eintraege'))

    # Pro Buch: erste Partie parsen, Linien zaehlen
    for fname in pgn_files:
        path = os.path.join(BOOKS_DIR, fname)
        try:
            with open(path, encoding='utf-8') as f:
                text = f.read()
            line_count = len(re.findall(r'^\[Event ', text, re.MULTILINE))
            # Erste Partie parsen
            stream = io.StringIO(_flatten_null_move_variations(text))
            game = chess.pgn.read_game(stream)
            if game is None:
                checks.append(CheckResult(fname, False, 'Keine Partie gefunden'))
            else:
                label = fname.replace('_firstkey.pgn', '')
                checks.append(CheckResult(label, True, f'{line_count} Linien'))
        except Exception as e:
            checks.append(CheckResult(fname, False, str(e)[:200]))

    return checks


# ---------------------------------------------------------------------------
# Modus: lichess — API-Status
# ---------------------------------------------------------------------------

def _run_lichess() -> list[CheckResult]:
    checks = []

    from puzzle.lichess import LICHESS_TOKEN

    # Token vorhanden?
    has_token = bool(LICHESS_TOKEN)
    checks.append(CheckResult(
        'Token vorhanden', has_token,
        'Ja' if has_token else 'LICHESS_TOKEN fehlt in .env'))

    if not has_token:
        return checks

    # Token gueltig? (GET /api/account)
    import requests
    try:
        resp = requests.get(
            'https://lichess.org/api/account',
            headers={'Authorization': f'Bearer {LICHESS_TOKEN}'},
            timeout=5)
        if resp.status_code == 200:
            username = resp.json().get('username', '?')
            checks.append(CheckResult('Token gueltig', True, f'User: {username}'))
        elif resp.status_code == 401:
            checks.append(CheckResult('Token gueltig', False, 'HTTP 401 — Token ungueltig'))
        else:
            checks.append(CheckResult('Token gueltig', False, f'HTTP {resp.status_code}'))
    except Exception as e:
        checks.append(CheckResult('Token gueltig', False, str(e)[:200]))

    # Cooldown-Status
    from puzzle.lichess import _lichess_rate_limited
    if _lichess_rate_limited():
        from puzzle.state import LICHESS_COOLDOWN_FILE
        cooldown = atomic_read(LICHESS_COOLDOWN_FILE, default=dict)
        until = cooldown.get('until', '')
        checks.append(CheckResult('Cooldown', False, f'Aktiv bis {until}'))
    else:
        checks.append(CheckResult('Cooldown', True, 'Kein aktiver Cooldown'))

    return checks


# ---------------------------------------------------------------------------
# Modus: rendering — Board-Rendering testen
# ---------------------------------------------------------------------------

def _run_rendering() -> tuple[list[CheckResult], io.BytesIO | None]:
    checks = []
    img = None

    try:
        board = chess.Board()
        img = _render_board(board)
        checks.append(CheckResult('Startposition rendern', True, 'Erfolgreich'))
    except Exception as e:
        checks.append(CheckResult('Startposition rendern', False, str(e)[:200]))

    return checks, img


# ---------------------------------------------------------------------------
# Modus: assets — Datei-Vollstaendigkeit
# ---------------------------------------------------------------------------

_EXPECTED_PIECES = [
    'wK', 'wQ', 'wR', 'wB', 'wN', 'wP',
    'bK', 'bQ', 'bR', 'bB', 'bN', 'bP',
]

_ASSETS_DIR = os.path.join(_ROOT, 'assets')


def _run_assets() -> list[CheckResult]:
    checks = []

    # SVG-Pieces
    pieces_dir = os.path.join(_ASSETS_DIR, 'pieces')
    for piece in _EXPECTED_PIECES:
        path = os.path.join(pieces_dir, f'{piece}.svg')
        exists = os.path.isfile(path)
        detail = 'vorhanden' if exists else 'FEHLT'
        checks.append(CheckResult(f'{piece}.svg', exists, detail))

    # sprueche.json
    sprueche_path = os.path.join(_ASSETS_DIR, 'sprueche.json')
    if os.path.isfile(sprueche_path):
        try:
            with open(sprueche_path, encoding='utf-8') as f:
                data = json.load(f)
            checks.append(CheckResult(
                'sprueche.json', True, f'{len(data)} Eintraege'))
        except Exception as e:
            checks.append(CheckResult('sprueche.json', False, str(e)[:200]))
    else:
        checks.append(CheckResult('sprueche.json', False, 'FEHLT'))

    # Bot-Icons
    for icon in ('icon_schach_bot.png', 'icon_schach_bot_dev.png'):
        path = os.path.join(_ASSETS_DIR, icon)
        exists = os.path.isfile(path)
        checks.append(CheckResult(icon, exists, 'vorhanden' if exists else 'FEHLT'))

    return checks


# ---------------------------------------------------------------------------
# Snapshot-Helpers (unveraendert)
# ---------------------------------------------------------------------------

def _load_snapshots():
    try:
        with open(SNAPSHOTS_FILE, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f'Snapshot-Datei nicht gefunden: {SNAPSHOTS_FILE}')
    except json.JSONDecodeError as e:
        raise ValueError(f'Snapshot-Datei fehlerhaft: {e}')


_MAX_PARSE_ERRORS = 50


def _find_game(filename, round_id):
    """PGN-Datei lesen und Partie mit passendem Round-Header finden."""
    path = os.path.join(BOOKS_DIR, filename)
    with open(path, encoding='utf-8') as f:
        pgn_text = _flatten_null_move_variations(f.read())
    stream = io.StringIO(pgn_text)
    errors = 0
    while True:
        try:
            game = chess.pgn.read_game(stream)
        except Exception:
            errors += 1
            if errors >= _MAX_PARSE_ERRORS:
                raise ValueError(
                    f'Zu viele Parse-Fehler ({errors}) in {filename}, '
                    f'Round {round_id!r} nicht gefunden')
            continue
        if game is None:
            raise ValueError(f'Round {round_id!r} nicht gefunden in {filename}')
        if game.headers.get('Round', '') == round_id:
            return game


def _book_label(filename):
    return filename.replace('_firstkey.pgn', '')


class _PuzzleSelect(discord.ui.Select):
    """Dropdown zum Rendern eines getesteten Puzzles."""

    def __init__(self, puzzle_ids: list[tuple[str, str]]):
        options = [
            discord.SelectOption(label=label[:100], value=pid)
            for label, pid in puzzle_ids
        ]
        super().__init__(placeholder='Puzzle anzeigen...', options=options)

    async def callback(self, interaction: discord.Interaction):
        if not self.values:
            return
        puzzle_id = self.values[0]
        await interaction.response.defer(ephemeral=True)

        result = find_line_by_id(puzzle_id)
        if not result:
            await interaction.followup.send(
                f'Puzzle `{puzzle_id}` nicht gefunden.', ephemeral=True)
            return

        line_id, original_game = result
        game = _trim_to_training_position(original_game)
        context = original_game if game is not original_game else None

        board = game.board()
        turn = board.turn
        try:
            img = await asyncio.to_thread(_render_board, board)
        except Exception:
            img = None

        fname = line_id.split(':')[0]
        meta = _load_books_config().get(fname, {})
        embed = build_puzzle_embed(
            game, turn=turn,
            difficulty=meta.get('difficulty', ''),
            rating=meta.get('rating', 0),
            line_id=line_id,
        )

        # Loesung + Partie als Felder anhaengen (max 1024 Zeichen pro Feld)
        def _field_val(text):
            val = f'||`{text}`||'
            if len(val) > 1024:
                val = f'||`{text[:1014]}`\u2026||'
            return val

        exporter = chess.pgn.StringExporter(
            headers=False, variations=True, comments=True)
        pgn_moves = _strip_pgn_annotations(game.accept(exporter))
        if pgn_moves:
            embed.add_field(
                name='Loesung', value=_field_val(pgn_moves), inline=False)
        if context:
            prelude = _prelude_pgn(context, game)
            if prelude:
                embed.add_field(
                    name='Ganze Partie', value=_field_val(prelude), inline=False)

        # Lichess-Upload
        loop = asyncio.get_running_loop()
        puzzle_url = await loop.run_in_executor(
            _lichess_executor, lambda: upload_to_lichess(game, context_game=context))

        if puzzle_url:
            embed.add_field(
                name='Lichess', value=f'[Studie \u00f6ffnen]({puzzle_url})', inline=False)

        if img:
            file = discord.File(img, filename='board.png')
            embed.set_image(url='attachment://board.png')
            await interaction.followup.send(
                file=file, embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)


def _resolve_book_filename(book_idx: int) -> str | None:
    """1-basierte Buchnummer -> Dateiname oder None."""
    if book_idx < 1:
        return None
    books = sorted(f for f in os.listdir(BOOKS_DIR) if f.endswith('.pgn'))
    if 1 <= book_idx <= len(books):
        return books[book_idx - 1]
    return None


# ---------------------------------------------------------------------------
# Modus: snapshots — Trim-Snapshot-Tests (bisheriger Default)
# ---------------------------------------------------------------------------

async def _run_snapshots(interaction, kurs, show_puzzle, show_lichess):
    """Fuehrt die Snapshot-Tests aus und sendet Ergebnisse."""
    snapshots = _load_snapshots()

    # Optional nach Buch filtern
    if kurs > 0:
        book_fn = _resolve_book_filename(kurs)
        if not book_fn:
            await interaction.followup.send(
                f'Buch {kurs} nicht gefunden. `/kurs` zeigt die Liste.',
                ephemeral=True)
            return
        snapshots = [s for s in snapshots if s['filename'] == book_fn]
        if not snapshots:
            await interaction.followup.send(
                f'Keine Snapshots fuer Buch {kurs} (`{_book_label(book_fn)}`).',
                ephemeral=True)
            return

    ok_count = 0
    fields = []
    puzzle_ids = []  # (label, puzzle_id) fuer Dropdown
    detail_results: list[dict] = []

    book_counter = {}
    for snap in snapshots:
        fn = snap['filename']
        book_counter[fn] = book_counter.get(fn, 0) + 1

    book_seen = {}
    for snap in snapshots:
        filename = snap['filename']
        round_id = snap['round']
        exp_trimmed = snap['trimmed']
        exp_fen = snap['fen']
        exp_side = snap['side']
        exp_first = snap['first_move_uci']

        base = _book_label(filename)
        book_seen[filename] = book_seen.get(filename, 0) + 1
        label = f'{base} #{book_seen[filename]}' if book_counter[filename] > 1 else base
        errors = []
        trimmed_game = None
        context_game = None
        solution_text = ''

        try:
            game = _find_game(filename, round_id)
            result = _trim_to_training_position(game)
            was_trimmed = result is not game

            if was_trimmed != exp_trimmed:
                errors.append(f'trimmed: {was_trimmed}, erwartet {exp_trimmed}')

            result_fen = result.headers.get('FEN', result.board().fen())
            if result_fen != exp_fen:
                errors.append(f'FEN abweichend')

            side = 'b' if ' b ' in result_fen else 'w'
            if side != exp_side:
                errors.append(f'side: {side}, erwartet {exp_side}')

            if result.variations:
                first_move = result.variations[0].move.uci()
            else:
                first_move = '-'
            if first_move != exp_first:
                errors.append(f'move: {first_move}, erwartet {exp_first}')

            context_game = game if was_trimmed else None

            exporter = chess.pgn.StringExporter(
                headers=False, variations=True, comments=True)
            solution_text = _strip_pgn_annotations(result.accept(exporter))
            exp_solution = snap.get('solution', '')
            if exp_solution and solution_text != exp_solution:
                errors.append(f'solution abweichend')

            if exp_trimmed:
                prelude = _prelude_pgn(context_game, result) if context_game else ''
                exp_prelude = snap.get('prelude', '')
                if exp_prelude and prelude != exp_prelude:
                    errors.append(f'prelude abweichend')

            trimmed_game = result

        except Exception as exc:
            errors.append(str(exc))

        puzzle_id = f'{filename}:{round_id}'
        puzzle_ids.append((label, puzzle_id))

        if errors:
            fields.append((
                f'\u274c {label}',
                f'`{puzzle_id}`\n' + '\n'.join(errors),
            ))
        else:
            ok_count += 1
            side_label = 'w' if exp_side == 'w' else 'b'
            move_info = exp_first if exp_first != '-' else 'keine Variante'
            fields.append((
                f'\u2705 {label}',
                f'`{puzzle_id}`\n{"trimmed" if exp_trimmed else "untrimmed"} \u00b7 {side_label} am Zug \u00b7 {move_info}',
            ))

        if (show_puzzle or show_lichess) and trimmed_game is not None:
            detail_results.append({
                'label': label,
                'puzzle_id': puzzle_id,
                'game': trimmed_game,
                'context': context_game,
                'solution': solution_text,
                'side': exp_side,
            })

    total = len(snapshots)
    all_ok = ok_count == total
    colour = EMBED_COLOR if all_ok else 0xe74c3c

    MAX_FIELDS = 25
    embeds = []
    for i in range(0, len(fields), MAX_FIELDS):
        chunk = fields[i:i + MAX_FIELDS]
        embed = discord.Embed(
            title='Trim-Snapshot-Tests' if i == 0 else None,
            colour=colour,
        )
        for name, value in chunk:
            embed.add_field(name=name, value=value, inline=False)
        embeds.append(embed)
    embeds[-1].set_footer(text=f'{ok_count}/{total} OK')

    view = discord.ui.View(timeout=300)
    view.add_item(_PuzzleSelect(puzzle_ids[:25]))

    await interaction.followup.send(embeds=embeds, view=view, ephemeral=True)

    # Detail-Nachrichten (puzzle / lichess)
    for det in detail_results:
        g = det['game']
        ctx = det['context']
        side_str = 'Weiss' if det['side'] == 'w' else 'Schwarz'
        header = f"**{det['label']}** \u00b7 `{det['puzzle_id']}` \u00b7 {side_str} am Zug"

        parts = [header]

        if show_puzzle and det['solution']:
            sol = det['solution']
            if len(sol) > 1900:
                sol = sol[:1900] + '\u2026'
            parts.append(f'||`{sol}`||')

        lichess_url = None
        if show_lichess:
            loop = asyncio.get_running_loop()
            lichess_url = await loop.run_in_executor(
                _lichess_executor, lambda _g=g, _c=ctx: upload_to_lichess(_g, context_game=_c))
            if lichess_url:
                parts.append(lichess_url)

        text = '\n'.join(parts)

        if show_puzzle:
            try:
                img = await asyncio.to_thread(_render_board, g.board())
                file = discord.File(img, filename='board.png')
                await interaction.followup.send(
                    text, file=file, ephemeral=True)
            except Exception:
                await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.followup.send(text, ephemeral=True)


# ---------------------------------------------------------------------------
# Test-Reminder per DM (Wochenpost + Turnier)
# ---------------------------------------------------------------------------

async def _trigger_test_reminders(interaction, bot):
    """Sendet Test-Reminder per DM falls der User subscribed ist."""
    uid = str(interaction.user.id)
    uid_int = interaction.user.id
    sent = []

    # --- Wochenpost-Erinnerung ---
    try:
        import commands.wochenpost as wp
        sub_data = atomic_read(wp.WOCHENPOST_SUB_FILE, default=dict)
        if uid in sub_data.get('subscribers', {}):
            entry = wp._get_latest_posted()
            if entry and 'msg_id' in entry:
                titel = entry.get('titel', '')
                thread_id = entry.get('thread_id')

                thread_url = ''
                if thread_id and wp._wochenpost_channel_id:
                    channel = bot.get_channel(wp._wochenpost_channel_id)
                    if channel:
                        guild_id = getattr(getattr(channel, 'guild', None), 'id', None)
                        if guild_id:
                            thread_url = f'https://discord.com/channels/{guild_id}/{thread_id}'

                msg = await wp._build_reminder_text(uid_int, titel, thread_url)
                dm = await interaction.user.create_dm()
                await dm.send(msg)
                sent.append('wochenpost')
    except Exception as e:
        log.debug('Test-Reminder wochenpost: %s', e)

    # --- Turnier-Erinnerung ---
    try:
        import commands.schachrallye as sr
        turnier_data = atomic_read(sr.TURNIER_FILE, default=dict)
        if isinstance(turnier_data, dict):
            subs = turnier_data.get('subscribers', {})
            user_tags = [tag for tag, uids in subs.items() if uid_int in uids]

            if user_tags:
                events = turnier_data.get('events', [])
                today = datetime.now(timezone.utc).date()
                upcoming = []
                for ev in events:
                    if not set(ev.get('tags', [])).intersection(user_tags):
                        continue
                    try:
                        d = datetime.strptime(ev.get('datum', ''), '%Y-%m-%d').date()
                    except ValueError:
                        continue
                    if d > today:
                        upcoming.append(ev)

                if upcoming:
                    upcoming.sort(key=lambda e: e.get('datum', ''))
                    lines = []
                    for ev in upcoming[:5]:
                        name = ev.get('name', f'Termin #{ev.get("id", "?")}')
                        try:
                            d = datetime.strptime(ev['datum'], '%Y-%m-%d').date()
                            ts = int(datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc).timestamp())
                            lines.append(f'**{name}** \u2014 <t:{ts}:D>')
                        except Exception:
                            lines.append(f'**{name}** \u2014 {ev.get("datum", "")}')

                    tags_str = ', '.join(user_tags)
                    msg = f'\U0001f3c6 **Turnier-Erinnerung** (Tags: {tags_str})\n\n' + '\n'.join(lines)

                    dm = await interaction.user.create_dm()
                    await dm.send(msg)
                    sent.append('turnier')
    except Exception as e:
        log.debug('Test-Reminder turnier: %s', e)

    if sent:
        await interaction.followup.send(
            f'Test-Reminder gesendet: {", ".join(sent)}', ephemeral=True)


# ---------------------------------------------------------------------------
# Dispatch + Command
# ---------------------------------------------------------------------------

_MODES = {
    'status': 'Bot-Vitals (Latenz, Guilds, Uptime, Loops)',
    'files': 'JSON-Datei-Integritaet pruefen',
    'pgn': 'PGN-Dateien parsen und pruefen',
    'lichess': 'Lichess-API-Verbindung testen',
    'rendering': 'Board-Rendering testen',
    'assets': 'Asset-Vollstaendigkeit pruefen',
    'snapshots': 'Trim-Snapshot-Regressionstests',
}


def setup(bot):
    choices = [
        discord.app_commands.Choice(name=f'{key} — {desc}', value=key)
        for key, desc in _MODES.items()
    ]

    @bot.tree.command(name='test', description='Diagnose-Tests ausfuehren (Admin)')
    @discord.app_commands.default_permissions(administrator=True)
    @discord.app_commands.describe(
        modus='Test-Modus (Standard: snapshots)',
        kurs='Buchnummer aus /kurs (nur fuer snapshots)',
        puzzle='1 = Board-Bild + Loesung pro Snapshot (nur fuer snapshots)',
        lichess='1 = Lichess-Studienlink pro Snapshot (nur fuer snapshots)',
    )
    @discord.app_commands.choices(modus=choices)
    async def test_cmd(interaction: discord.Interaction,
                       modus: str = 'snapshots',
                       kurs: int = 0, puzzle: int = 0, lichess: int = 0):
        if not is_privileged(interaction):
            await interaction.response.send_message('\u26a0\ufe0f Nur fuer Admins.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        if modus == 'snapshots':
            await _run_snapshots(interaction, kurs, puzzle == 1, lichess == 1)
        elif modus == 'status':
            checks = _run_status(bot)
            embed = _build_result_embed('Bot-Status', checks)
            await interaction.followup.send(embed=embed, ephemeral=True)
        elif modus == 'files':
            checks = await asyncio.to_thread(_run_files)
            embed = _build_result_embed('JSON-Integritaet', checks)
            await interaction.followup.send(embed=embed, ephemeral=True)
        elif modus == 'pgn':
            checks = await asyncio.to_thread(_run_pgn)
            embed = _build_result_embed('PGN-Dateien', checks)
            await interaction.followup.send(embed=embed, ephemeral=True)
        elif modus == 'lichess':
            checks = await asyncio.to_thread(_run_lichess)
            embed = _build_result_embed('Lichess-API', checks)
            await interaction.followup.send(embed=embed, ephemeral=True)
        elif modus == 'rendering':
            checks, img = await asyncio.to_thread(_run_rendering)
            embed = _build_result_embed('Board-Rendering', checks)
            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                await interaction.followup.send(
                    file=file, embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
        elif modus == 'assets':
            checks = _run_assets()
            embed = _build_result_embed('Assets', checks)
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(
                f'Unbekannter Modus: `{modus}`', ephemeral=True)
            return

        # Test-Reminder per DM falls subscribed
        await _trigger_test_reminders(interaction, bot)
