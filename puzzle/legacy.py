"""Puzzle-Funktionen: Board-Rendering, Lichess-Upload, PGN-Laden, Slash-Commands."""

import asyncio
from core import stats
import logging
import os
import random
import re
import time as _time_mod
from collections import defaultdict
from datetime import date as _date

import chess
import chess.pgn
import discord

log = logging.getLogger('schach-bot')

from core.version import EMBED_COLOR
from puzzle.buttons import fresh_view as _fresh_button_view

_DISCORD_THREAD_NAME_MAX = 100

# --- Zustand/Persistenz (ausgelagert nach puzzle.state) ---
from puzzle.state import (  # noqa: F401
    IGNORE_FILE, CHAPTER_IGNORE_FILE, BOOKS_DIR, PUZZLE_STUDY_ID,
    PUZZLE_STATE_FILE, USER_STUDIES_FILE, LICHESS_COOLDOWN_FILE,
    _PUZZLE_MSG_CAP, _puzzle_msg_ids,
    _register_puzzle_msg, is_puzzle_message, get_puzzle_line_id, get_puzzle_mode,
    _ignore_cache, _load_ignore_list, _invalidate_ignore_cache,
    ignore_puzzle, unignore_puzzle,
    _chapter_ignore_cache, _load_chapter_ignore_list, _invalidate_chapter_ignore_cache,
    _is_chapter_ignored, ignore_chapter, unignore_chapter, get_chapter_from_line_id,
    _endless_sessions, _ENDLESS_TIMEOUT_SECS,
    _evict_stale_endless, start_endless, stop_endless, is_endless, get_endless_session,
    load_puzzle_state, save_puzzle_state,
    _load_user_studies, _save_user_studies,
    _get_user_study_id, _get_user_puzzle_count, _set_user_study_id,
    _books_config_cache, _load_books_config, _invalidate_books_config_cache,
    _get_user_training, _set_user_training, _clear_user_training,
)
from core.paths import CONFIG_DIR


async def _upload_puzzles_async(
    pairs: list[tuple[chess.pgn.Game, chess.pgn.Game | None]],
    reuse_study_id: str | None = None,
) -> list[str]:
    """Upload-Pairs asynchron in einem Thread-Executor hochladen."""
    loop = asyncio.get_running_loop()
    if len(pairs) == 1:
        u = await loop.run_in_executor(
            None, lambda: upload_to_lichess(
                pairs[0][0], context_game=pairs[0][1],
                reuse_study_id=reuse_study_id))
        return [u] if u else []
    else:
        return await loop.run_in_executor(
            None, lambda: upload_many_to_lichess(
                pairs, reuse_study_id=reuse_study_id))


# --- PGN-Verarbeitung (ausgelagert nach puzzle.processing) ---
from puzzle.processing import (  # noqa: F401
    _solution_pgn, _clean_book_name, _prelude_pgn, _has_training_comment,
    _trim_to_training_position, _split_for_blind, _format_blind_moves,
    _flatten_null_move_variations, _strip_pgn_annotations, _clean_pgn_for_lichess,
)


async def _send_puzzle_followups(target, game: chess.pgn.Game,
                                 context: chess.pgn.Game | None,
                                 puzzle_url: str | None,
                                 line_id: str):
    """Lösung, Prelude und Lichess-Link als optionale Follow-ups senden."""
    pgn_moves = _solution_pgn(game)
    if pgn_moves:
        await _send_optional(target, f'Lösung: ||`{pgn_moves}`||', label=f'Lösung {line_id}')
    if context:
        prelude = _prelude_pgn(context, game)
        if prelude:
            await _send_optional(target, f'Ganze Partie: ||`{prelude}`||', label=f'Partie {line_id}')
    if puzzle_url:
        await _send_optional(target, f'[Klickbares Rätsel]({puzzle_url})', label=f'Lichess-Link {line_id}')


async def post_next_endless(bot, user_id: int):
    """Nächstes Puzzle im Endless-Modus per DM senden."""
    session = _endless_sessions.get(user_id)
    if not session:
        return

    book_filename = session['book']
    results = pick_random_lines(1, book_filename)
    if not results:
        # Keine Puzzles mehr → Session beenden
        try:
            user = await bot.fetch_user(user_id)
            dm = await user.create_dm()
            await dm.send('⚠️ Keine weiteren Puzzles verfügbar. Endless-Modus beendet.')
        except Exception as e:
            log.warning('Endless-Ende-DM fehlgeschlagen (user=%s): %s', user_id, e)
        _endless_sessions.pop(user_id, None)
        return

    line_id, original_game = results[0]
    game = _trim_to_training_position(original_game)
    context = original_game if game is not original_game else None

    books_config = _load_books_config()
    fname = line_id.split(':')[0]
    book_meta = books_config.get(fname, {})
    diff = book_meta.get('difficulty', '')
    rating = book_meta.get('rating', 0)

    # Upload
    reuse_study_id = _get_user_study_id(user_id)
    urls = await _upload_puzzles_async([(game, context)], reuse_study_id=reuse_study_id)
    puzzle_url = urls[0] if urls else None

    # Studie-ID speichern
    sid = _extract_study_id(puzzle_url)
    if sid:
        base_count, base_total = _get_user_puzzle_count(user_id)
        _set_user_study_id(user_id, sid, base_count + 1, base_total + 1)

    session['count'] += 1
    session['last_active'] = _time_mod.time()

    # DM senden
    try:
        user = await bot.fetch_user(user_id)
        dm = await user.create_dm()
    except Exception as e:
        log.warning('Endless-DM fehlgeschlagen (user=%s): %s – Session beendet', user_id, e)
        stop_endless(user_id)
        return

    try:
        board = game.board()
        turn = board.turn
        img = await asyncio.to_thread(_render_board, board)
    except Exception:
        turn, img = None, None

    embed = build_puzzle_embed(game, turn=turn, difficulty=diff, rating=rating, line_id=line_id)
    embed.set_footer(text=f'♾️ Endless-Modus · Puzzle #{session["count"]} · ID: {line_id}')

    if img:
        file = discord.File(img, filename='board.png')
        embed.set_image(url='attachment://board.png')
        msg = await dm.send(file=file, embed=embed)
    else:
        msg = await dm.send(embed=embed)

    _register_puzzle_msg(msg.id, line_id)
    await msg.edit(view=_fresh_button_view())

    # Lösung, Prelude, Lichess-Link
    await _send_puzzle_followups(dm, game, context, puzzle_url, line_id)

    stats.inc(user_id, 'puzzles', 1)


PUZZLE_HOUR       = int(os.getenv('PUZZLE_HOUR', '9'))
PUZZLE_MINUTE     = int(os.getenv('PUZZLE_MINUTE', '0'))
CHANNEL_ID        = int(os.getenv('CHANNEL_ID', '0'))

# --- Board-Rendering (ausgelagert nach puzzle.rendering) ---
from puzzle.rendering import _svg_to_pil, _get_piece, _label_font, _render_board  # noqa: F401

# --- Auswahl/Caching (ausgelagert nach puzzle.selection) ---
from puzzle.selection import (  # noqa: F401
    _find_chapter_prefix, _list_chapters, _list_pgn_files,
    _FATAL_STATUS, PUZZLE_CACHE_FILE, _lines_cache, _lines_cache_fp,
    _books_fingerprint, clear_lines_cache, load_all_lines, _parse_all_lines,
    pick_sequential_lines, get_random_books,
    pick_random_lines, pick_random_line, find_line_by_id,
    get_blind_books, pick_random_blind_lines,
)


# --- Lichess-API (ausgelagert nach puzzle.lichess) ---
from puzzle.lichess import (  # noqa: F401
    _LICHESS_STUDY_NAME_MAX, _LICHESS_CHAPTER_NAME_MAX,
    LICHESS_API_TIMEOUT, LICHESS_TOKEN,
    _extract_study_id, _export_pgn_for_lichess,
    _LICHESS_COOLDOWN_SECS, LichessRateLimitError,
    _lichess_cooldown_until, _lichess_rate_limited, _lichess_set_cooldown,
    _lichess_request, upload_to_lichess, upload_many_to_lichess,
)

# --- Embed-Bau (ausgelagert nach puzzle.embed) ---
from puzzle.embed import build_puzzle_embed  # noqa: F401


async def _resilient_send(target, *args, retries: int = 3, **kwargs):
    """Wie target.send(), aber mit Retry bei transienten Discord-5xx-Fehlern.

    Backoff: 1s, 2s, 4s. Wirft beim letzten Fehlversuch weiter.
    """
    delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            return await target.send(*args, **kwargs)
        except discord.errors.DiscordServerError as e:
            if attempt == retries:
                raise
            log.warning('Discord-5xx (Versuch %d/%d): %s – retry in %.1fs',
                        attempt, retries, e, delay)
            await asyncio.sleep(delay)
            delay = delay * 2 + random.uniform(0, 1)


async def _send_optional(target, *args, label: str = '', **kwargs):
    """Send, der bei Discord-5xx (auch nach Retries) nur loggt, nicht wirft."""
    try:
        return await _resilient_send(target, *args, **kwargs)
    except discord.errors.DiscordServerError as e:
        log.warning('Optionaler Send (%s) fehlgeschlagen nach Retries: %s', label, e)
    except Exception as e:
        log.warning('Optionaler Send (%s) fehlgeschlagen: %s', label, e)
    return None


async def post_puzzle(channel, count: int = 1, book_idx: int = 0, user_id: int | None = None) -> int:
    """Puzzles auswählen, auf Lichess hochladen und posten.

    count    – Anzahl Puzzles (1–20).
    book_idx – 1-basierte Buchnummer aus /kurs (0 = alle Bücher).
    user_id  – Discord-User-ID; wenn gesetzt, wird die Tages-Studie wiederverwendet.

    Gibt die Anzahl tatsächlich geposteter Puzzles zurück.
    """
    count = max(1, min(count, 20))

    # Buch bestimmen
    book_filename = None
    if book_idx > 0:
        books = _list_pgn_files()
        if books:
            if 1 <= book_idx <= len(books):
                book_filename = books[book_idx - 1]
            else:
                await channel.send(
                    f'⚠️ Buch {book_idx} nicht gefunden. `/kurs` zeigt die verfügbaren Bücher.'
                )
                return 0

    results = pick_random_lines(count, book_filename)
    if not results:
        await channel.send('⚠️ Keine Puzzle-Linien gefunden. Bitte .pgn-Dateien in den `books/`-Ordner legen.')
        return 0

    books_config = _load_books_config()

    # Trimmen
    puzzles: list[tuple[chess.pgn.Game, chess.pgn.Game | None, str, int, str]] = []
    for line_id, original_game in results:
        game    = _trim_to_training_position(original_game)
        context = original_game if game is not original_game else None
        fname   = line_id.split(':')[0]
        book_meta = books_config.get(fname, {})
        diff      = book_meta.get('difficulty', '')
        rating    = book_meta.get('rating', 0)
        puzzles.append((game, context, diff, rating, line_id))

    reuse_study_id = _get_user_study_id(user_id) if user_id else None
    base_count, base_total = _get_user_puzzle_count(user_id) if user_id else (0, 0)

    # Upload in Thread damit der Event Loop nicht blockiert
    upload_pairs = [(g, c) for g, c, _, _, _ in puzzles]
    urls = await _upload_puzzles_async(upload_pairs, reuse_study_id=reuse_study_id)

    # Studie-ID für diesen User+Tag speichern
    first_url = urls[0] if urls else None
    sid = _extract_study_id(first_url) if first_url and user_id else None
    if sid:
        _set_user_study_id(user_id, sid, base_count + len(puzzles), base_total + len(puzzles))

    # Thread-Name vom ersten Puzzle
    h = dict(puzzles[0][0].headers)
    event = h.get('Event', 'Puzzle')
    today = _date.today().strftime('%d.%m.%Y')
    thread_name = f'{event} – {today}'
    if len(thread_name) > 100:
        thread_name = thread_name[:_DISCORD_THREAD_NAME_MAX - 3] + '...'

    # Ziel: Thread (Server) oder direkt (DM / bestehender Thread)
    is_dm = isinstance(channel, discord.DMChannel)
    if is_dm or isinstance(channel, discord.Thread):
        target = channel
    else:
        target = await channel.create_thread(
            name=thread_name,
            type=discord.ChannelType.public_thread,
            auto_archive_duration=1440,
        )

    # Alle Puzzles als einzelne Bilder posten. Jede Iteration in try/except,
    # damit ein einzelner Crash (kaputtes Board, Discord-Edge-Case) nicht die
    # restlichen Puzzles verschluckt – der User soll bei /puzzle 5 auch dann 4
    # bekommen, wenn Nr. 2 schiefgeht.
    posted_ok = 0
    log.info('post_puzzle: poste %d Puzzle(s) in %s',
             len(puzzles), 'DM' if is_dm else f'thread {target.id}')
    for i, (game, context, diff, rating, lid) in enumerate(puzzles):
        try:
            puzzle_url = urls[i] if i < len(urls) else None
            puzzle_num   = (base_count + i + 1) if user_id else 0
            puzzle_total = (base_total + i + 1) if user_id else 0
            try:
                board = game.board()
                turn  = board.turn
                img   = await asyncio.to_thread(_render_board, board)
            except Exception as e:
                log.warning('Board-Render fehlgeschlagen (%s): %s', lid, e)
                turn = None
                img  = None

            embed = build_puzzle_embed(game, turn=turn, puzzle_num=puzzle_num, puzzle_total=puzzle_total, difficulty=diff, rating=rating, line_id=lid)
            # Haupt-Send: Brett + Embed. Nur das ist der Erfolgs-Anker;
            # alles danach (Lösung, Lichess-Link) ist optional und darf
            # bei Discord-5xx das Puzzle nicht als gescheitert markieren.
            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                msg = await _resilient_send(target, file=file, embed=embed)
            else:
                msg = await _resilient_send(target, embed=embed)
            posted_ok += 1
            _register_puzzle_msg(msg.id, lid)
        except Exception as e:
            log.exception('Puzzle %d/%d (%s) fehlgeschlagen: %s',
                          i + 1, len(puzzles), lid, e)
            continue

        # Ab hier ist das Puzzle „gepostet". Folgende Sends sind Beiwerk –
        # wenn Discord 5xx wirft, loggen wir, zählen aber nicht runter.
        try:
            await msg.edit(view=_fresh_button_view())
        except Exception as e:
            log.warning('Button-View-Edit fehlgeschlagen (%s): %s', lid, e)

        await _send_puzzle_followups(target, game, context, puzzle_url, lid)

    log.info('post_puzzle: %d/%d Puzzle(s) gepostet', posted_ok, len(puzzles))
    if user_id and posted_ok:
        stats.inc(user_id, 'puzzles', posted_ok)
    return posted_ok


async def post_blind_puzzle(channel,
                            moves: int,
                            count: int = 1,
                            book_idx: int = 0,
                            user_id: int | None = None):
    """Postet Blind-Puzzles: Stellung X Halbzüge VOR der Trainingsposition.

    moves    – Anzahl Halbzüge, die der User im Kopf spielen muss (≥1).
    count    – Anzahl Puzzles (1–20).
    book_idx – 1-basierte Buchnummer (0 = alle blind-fähigen Bücher).
    """
    moves = max(1, moves)
    count = max(1, min(count, 20))

    book_filename = None
    if book_idx > 0:
        books = _list_pgn_files()
        if books:
            if 1 <= book_idx <= len(books):
                book_filename = books[book_idx - 1]
            else:
                await channel.send(
                    f'⚠️ Buch {book_idx} nicht gefunden. `/kurs` zeigt verfügbare Bücher.'
                )
                return

    config = _load_books_config()
    if book_filename and not config.get(book_filename, {}).get('blind'):
        await channel.send(
            f'⚠️ Buch `{book_filename}` ist nicht für den Blind-Modus freigegeben.\n'
            'Setze in `books/books.json` `"blind": true` für dieses Buch.'
        )
        return

    results = pick_random_blind_lines(count, book_filename, moves)
    if not results:
        if not any(m.get('blind') for m in config.values()):
            await channel.send(
                '⚠️ Kein Buch hat `blind: true` in `books/books.json`. '
                'Bitte mindestens ein Buch dafür freigeben.'
            )
        else:
            await channel.send(
                f'⚠️ Kein Puzzle mit ≥{moves} Vorlauf-Zügen gefunden. '
                'Versuche eine kleinere `moves:`-Zahl oder ein anderes Buch.'
            )
        return

    h = dict(results[0][1].headers)
    event = h.get('Event', 'Blind-Puzzle')
    today = _date.today().strftime('%d.%m.%Y')
    thread_name = f'🙈 {event} (blind {moves}) – {today}'
    if len(thread_name) > 100:
        thread_name = thread_name[:_DISCORD_THREAD_NAME_MAX - 3] + '...'

    is_dm = isinstance(channel, discord.DMChannel)
    if is_dm:
        target = channel
    else:
        target = await channel.create_thread(
            name=thread_name,
            type=discord.ChannelType.public_thread,
            auto_archive_duration=1440,
        )

    posted = 0
    for line_id, original_game in results:
        split = _split_for_blind(original_game, moves)
        if split is None:
            continue
        blind_board, blind_san, puzzle_game = split

        fname = line_id.split(':')[0]
        meta = config.get(fname, {})
        diff = meta.get('difficulty', '')
        rating = meta.get('rating', 0)

        try:
            img = await asyncio.to_thread(_render_board, blind_board)
        except Exception as e:
            log.warning('Blind-Board-Render fehlgeschlagen: %s', e)
            img = None

        embed = build_puzzle_embed(
            puzzle_game,
            turn=blind_board.turn,
            difficulty=diff,
            rating=rating,
            line_id=line_id,
            blind_moves=moves,
        )
        embed.title = f'🙈 Blind-Puzzle ({moves} Züge)'
        blind_pgn = _format_blind_moves(blind_board, blind_san)
        embed.add_field(
            name='🙈 Spiele in Gedanken',
            value=f'`{blind_pgn}`\n_Visualisiere die Stellung danach und löse das Puzzle._',
            inline=False,
        )

        try:
            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                msg = await _resilient_send(target, file=file, embed=embed)
            else:
                msg = await _resilient_send(target, embed=embed)
            posted += 1
            _register_puzzle_msg(msg.id, line_id, mode='blind')
        except Exception as e:
            log.exception('Blind-Puzzle (%s) fehlgeschlagen: %s', line_id, e)
            continue

        try:
            await msg.edit(view=_fresh_button_view())
        except Exception as e:
            log.warning('Blind-Button-View-Edit fehlgeschlagen (%s): %s', line_id, e)

        pgn_moves = _solution_pgn(puzzle_game)
        if pgn_moves:
            await _send_optional(target, f'Lösung des Puzzles: ||`{pgn_moves}`||',
                                 label=f'Blind-Lösung {line_id}')

    if user_id and posted:
        stats.inc(user_id, 'blind_puzzles', posted)


# ---------------------------------------------------------------------------
# Slash-Commands registrieren
# ---------------------------------------------------------------------------

async def _cmd_puzzle(interaction: discord.Interaction, anzahl: int = 1, buch: int = 0,
                      id: str = '', user: discord.Member | None = None):
    target_user = user or interaction.user
    log.info('/puzzle von %s: anzahl=%d buch=%d id=%s user=%s',
             interaction.user, anzahl, buch, id, target_user)
    await interaction.response.defer(ephemeral=True)
    try:
        dm = await target_user.create_dm()
        target_uid = target_user.id

        if id:
            # Blind-Referenz: "lid:blind:N" → post_blind_puzzle
            _blind_moves = 0
            _lookup_id = id
            _blind_match = re.search(r':blind:(\d+)$', id, re.IGNORECASE)
            if _blind_match:
                _blind_moves = int(_blind_match.group(1))
                if _blind_moves > 50:
                    await interaction.followup.send(
                        '⚠️ Maximal 50 Blind-Züge erlaubt.', ephemeral=True)
                    return
                _lookup_id = id[:_blind_match.start()]

            result = find_line_by_id(_lookup_id)
            if not result:
                await interaction.followup.send(f'⚠️ Puzzle `{id}` nicht gefunden.', ephemeral=True)
                return

            if not _has_training_comment(result[1]):
                await interaction.followup.send(
                    f'⚠️ `{id}` hat keinen Trainingskommentar.', ephemeral=True)
                return

            if _blind_moves:
                if user:
                    await dm.send(f'**{interaction.user.display_name}** schickt dir ein Blind-Puzzle 🙈')
                line_id = result[0]
                orig = result[1]
                split = _split_for_blind(orig, _blind_moves)
                if split is None:
                    await interaction.followup.send(
                        f'⚠️ Puzzle `{line_id}` hat nicht genug Vorlauf-Züge für blind:{_blind_moves}.',
                        ephemeral=True)
                    return
                blind_board, blind_san, puzzle_game = split
                fname = line_id.split(':')[0]
                meta  = _load_books_config().get(fname, {})
                try:
                    img = await asyncio.to_thread(_render_board, blind_board)
                except Exception:
                    img = None
                embed = build_puzzle_embed(
                    puzzle_game, turn=blind_board.turn,
                    difficulty=meta.get('difficulty',''), rating=meta.get('rating', 0),
                    line_id=line_id, blind_moves=_blind_moves)
                embed.title = f'🙈 Blind-Puzzle ({_blind_moves} Züge)'
                blind_pgn = _format_blind_moves(blind_board, blind_san)
                embed.add_field(name='🙈 Spiele in Gedanken',
                                value=f'`{blind_pgn}`\n_Visualisiere die Stellung danach und löse das Puzzle._',
                                inline=False)
                if img:
                    file = discord.File(img, filename='board.png')
                    embed.set_image(url='attachment://board.png')
                    msg = await _resilient_send(dm, file=file, embed=embed)
                else:
                    msg = await _resilient_send(dm, embed=embed)
                _register_puzzle_msg(msg.id, line_id, mode='blind')
                try:
                    await msg.edit(view=_fresh_button_view())
                except Exception:
                    pass
                pgn_moves = _solution_pgn(puzzle_game)
                if pgn_moves:
                    await _send_optional(dm, f'Lösung des Puzzles: ||`{pgn_moves}`||', label=f'Blind-Lösung {line_id}')
                dest = f'an {target_user.mention}' if user else 'dir'
                await interaction.followup.send(f'🙈 Blind-Puzzle `{line_id}:blind:{_blind_moves}` {dest} per DM gesendet.', ephemeral=True)
                return

            line_id, original_game = result
            game = _trim_to_training_position(original_game)
            context = original_game if game is not original_game else None

            books_config = _load_books_config()
            fname = line_id.split(':')[0]
            book_meta = books_config.get(fname, {})
            diff = book_meta.get('difficulty', '')
            rating = book_meta.get('rating', 0)

            # Upload
            reuse_study_id = _get_user_study_id(target_uid)
            urls = await _upload_puzzles_async([(game, context)], reuse_study_id=reuse_study_id)
            puzzle_url = urls[0] if urls else None

            try:
                board = game.board()
                turn = board.turn
                img = await asyncio.to_thread(_render_board, board)
            except Exception:
                turn, img = None, None

            if user:
                await dm.send(f'**{interaction.user.display_name}** schickt dir ein Rätsel 🧩')

            embed = build_puzzle_embed(game, turn=turn, difficulty=diff, rating=rating, line_id=line_id)
            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                msg = await dm.send(file=file, embed=embed)
            else:
                msg = await dm.send(embed=embed)
            _register_puzzle_msg(msg.id, line_id)
            await msg.edit(view=_fresh_button_view())

            await _send_puzzle_followups(dm, game, context, puzzle_url, line_id)

            dest = f'an {target_user.mention}' if user else 'dir'
            await interaction.followup.send(
                f'✅ Puzzle `{line_id}` {dest} per DM gesendet.', ephemeral=True)
            return

        if user:
            await dm.send(f'**{interaction.user.display_name}** schickt dir ein Rätsel 🧩')
        sent = await post_puzzle(dm, count=anzahl, book_idx=buch, user_id=target_uid)
        dest = f'an {target_user.mention}' if user else 'dir'
        if sent == anzahl:
            msg = f'✅ {sent} Puzzle(s) wurde(n) {dest} per DM gesendet.'
        elif sent > 0:
            msg = f'⚠️ Nur {sent}/{anzahl} Puzzle(s) konnten {dest} gesendet werden – Details im Bot-Log.'
        else:
            msg = '❌ Es konnte kein Puzzle gesendet werden – Details im Bot-Log.'
        await interaction.followup.send(msg, ephemeral=True)
    except Exception as e:
        log.exception('/puzzle fehlgeschlagen: %s', e)
        await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)


async def _cmd_buecher(interaction: discord.Interaction, buch: int = 0):
    await interaction.response.defer(ephemeral=True)
    try:
        all_lines = load_all_lines()
        posted    = set(load_puzzle_state().get('posted', []))
        books_config = _load_books_config()

        # --- Detailansicht für ein einzelnes Buch ---
        if buch > 0:
            sorted_books = sorted(set(lid.split(':')[0] for lid, _ in all_lines))
            if buch > len(sorted_books):
                await interaction.followup.send(
                    f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die Liste.',
                    ephemeral=True)
                return
            book_fn = sorted_books[buch - 1]
            book_name = _clean_book_name(book_fn)
            meta  = books_config.get(book_fn, {})
            diff  = meta.get('difficulty', '')
            rat   = meta.get('rating', 0)
            stars = '★' * rat + '☆' * (10 - rat) if rat else ''

            # Persönlich abgehakte Puzzles (✅ oder ❌, netto >0)
            from core import event_log as _elog
            uid = interaction.user.id
            _net: dict[str, int] = {}
            for entry in _elog.read_all():
                if entry.get('user') != uid:
                    continue
                if entry.get('emoji') not in ('✅', '❌'):
                    continue
                lid_e = entry.get('line_id') or ''
                _net[lid_e] = _net.get(lid_e, 0) + entry.get('delta', 0)
            user_done: set[str] = {lid_e for lid_e, n in _net.items() if n > 0}

            # Kapitel aufbauen: round-Prefix → (name, total, done)
            chapter_ignored = _load_chapter_ignore_list()
            chapters: dict[str, dict] = {}
            for lid, game in all_lines:
                if lid.split(':')[0] != book_fn:
                    continue
                round_hdr = lid.split(':')[1] if ':' in lid else ''
                prefix = round_hdr.split('.')[0] if '.' in round_hdr else round_hdr
                if prefix not in chapters:
                    h = dict(game.headers)
                    chap_name = h.get('Black', '') or h.get('Event', '')
                    ignored_key = f'{book_fn}:{prefix}'
                    chapters[prefix] = {
                        'name': chap_name,
                        'total': 0,
                        'posted': 0,
                        'ignored': ignored_key in chapter_ignored,
                    }
                chapters[prefix]['total'] += 1
                if lid in user_done:
                    chapters[prefix]['posted'] += 1

            total_book  = sum(c['total']  for c in chapters.values())
            posted_book = sum(c['posted'] for c in chapters.values())

            flags = []
            if meta.get('random', True):  flags.append('🎲 Im Zufalls-/Daily-Pool')
            if meta.get('blind'):          flags.append('🙈 Blind-Modus')

            desc_parts = [f'**{posted_book}/{total_book}** von dir bewertet (✅/❌)']
            if diff:
                desc_parts.append(f'{diff}  {stars}' if stars else diff)
            desc_parts.extend(flags)

            embed = discord.Embed(
                title=f'📖 {book_name}',
                description='\n'.join(desc_parts),
                color=0x7fa650,
            )

            sorted_chapters = sorted(chapters.items())
            # Bis zu 25 Felder (Discord-Limit)
            for prefix, info in sorted_chapters[:25]:
                chap_num = int(prefix) if prefix.isdigit() else prefix
                done  = info['posted']
                total = info['total']
                is_ign = info['ignored']
                bar   = '█' * round(done / total * 8) + '░' * (8 - round(done / total * 8)) if total else '░' * 8
                label = f'Kap. {chap_num}: {info["name"]}' if info['name'] else f'Kapitel {chap_num}'
                if len(label) > 250:
                    label = label[:247] + '...'
                name_field = f'~~{label}~~ 🚫' if is_ign else label
                embed.add_field(
                    name=name_field,
                    value=f'`{bar}` {done}/{total}' + (' *(ignoriert)*' if is_ign else ''),
                    inline=False,
                )
            if len(sorted_chapters) > 25:
                embed.set_footer(text=f'… {len(sorted_chapters) - 25} weitere Kapitel nicht angezeigt')
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # --- Übersichtsliste aller Bücher ---
        total_per_book:  dict[str, int] = defaultdict(int)
        posted_per_book: dict[str, int] = defaultdict(int)
        for lid, _ in all_lines:
            book = lid.split(':')[0]
            total_per_book[book] += 1
            if lid in posted:
                posted_per_book[book] += 1

        if not total_per_book:
            await interaction.followup.send(
                '⚠️ Keine Bücher gefunden. Bitte .pgn-Dateien in den `books/`-Ordner legen.',
                ephemeral=True,
            )
            return

        embed = discord.Embed(title='📚 Puzzle-Bücher', color=0x7fa650)
        for i, book in enumerate(sorted(total_per_book), 1):
            name  = _clean_book_name(book)
            total = total_per_book[book]
            done  = posted_per_book[book]
            meta  = books_config.get(book, {})
            diff  = meta.get('difficulty', '')
            rat   = meta.get('rating', 0)
            stars = '★' * rat + '☆' * (10 - rat) if rat else ''
            info  = f'{done}/{total} gepostet'
            if diff:
                info += f'\n{diff}  {stars}' if stars else f'\n{diff}'
            if meta.get('random', True):
                info += '\n🎲 Im Zufalls-/Daily-Pool'
            if meta.get('blind'):
                info += '\n🙈 Blind-Modus verfügbar'
            embed.add_field(name=f'{i}: {name}', value=info, inline=False)

        total_all = sum(total_per_book.values())
        done_all  = sum(posted_per_book.values())
        embed.set_footer(text=f'Gesamt: {done_all}/{total_all} Linien gepostet')
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)


async def _cmd_train(interaction: discord.Interaction, buch: int = None):
    await interaction.response.defer(ephemeral=True)
    user_id = interaction.user.id

    if buch is None:
        # Status anzeigen
        training = _get_user_training(user_id)
        if not training:
            await interaction.followup.send(
                '📭 Kein Training aktiv. Wähle ein Buch mit `/train <nummer>` '
                '(Nummern aus `/kurs`).', ephemeral=True)
            return
        book_filename = training['book']
        pos = training['position']
        all_lines = load_all_lines()
        total = sum(1 for lid, _ in all_lines if lid.startswith(book_filename + ':'))
        name = _clean_book_name(book_filename)
        books = _list_pgn_files()
        kurs_nr = books.index(book_filename) + 1 if book_filename in books else 0
        books_config = _load_books_config()
        meta = books_config.get(book_filename, {})
        diff = meta.get('difficulty', '')
        rat = meta.get('rating', 0)
        stars = ('★' * rat + '☆' * (10 - rat)) if rat else ''
        pct = f' ({pos * 100 // total}%)' if total else ''

        embed = discord.Embed(title=f'📖 Training: {name} ({kurs_nr})', color=0x7fa650)
        embed.add_field(name='Fortschritt', value=f'{pos}/{total} Linien{pct}', inline=True)
        if diff:
            embed.add_field(name='Schwierigkeit',
                            value=f'{diff}  {stars}' if stars else diff, inline=True)
        embed.add_field(name='Nächster Schritt',
                        value='`/next` `/next 5` `/next 10`', inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    if buch == 0:
        _clear_user_training(user_id)
        await interaction.followup.send('🔓 Training beendet.', ephemeral=True)
        return

    # Buch validieren
    books = _list_pgn_files()
    if not books:
        await interaction.followup.send('⚠️ Kein books-Ordner.', ephemeral=True)
        return
    if buch < 1 or buch > len(books):
        await interaction.followup.send(
            f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die Liste.', ephemeral=True)
        return

    book_filename = books[buch - 1]
    # Aktuelle Position beibehalten falls selbes Buch
    training = _get_user_training(user_id)
    if training and training.get('book') == book_filename:
        pos = training['position']
    else:
        pos = 0

    _set_user_training(user_id, book_filename, pos)

    # Info anzeigen
    all_lines = load_all_lines()
    total = sum(1 for lid, _ in all_lines if lid.startswith(book_filename + ':'))
    name = _clean_book_name(book_filename)
    books_config = _load_books_config()
    meta = books_config.get(book_filename, {})
    diff = meta.get('difficulty', '')
    rat = meta.get('rating', 0)
    stars = ('★' * rat + '☆' * (10 - rat)) if rat else ''

    embed = discord.Embed(title=f'📖 Training: {name} ({buch})', color=0x7fa650)
    embed.add_field(name='Fortschritt', value=f'{pos}/{total} Linien', inline=True)
    if diff:
        embed.add_field(name='Schwierigkeit',
                        value=f'{diff}  {stars}' if stars else diff, inline=True)
    embed.add_field(name='Nächster Schritt',
                    value='`/next` `/next 5` `/next 10`', inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


async def _cmd_next(interaction: discord.Interaction, anzahl: int = 1):
    await interaction.response.defer(ephemeral=True)
    user_id = interaction.user.id
    anzahl = max(1, min(anzahl, 20))

    training = _get_user_training(user_id)
    if not training:
        await interaction.followup.send(
            '⚠️ Kein Trainingsbuch gewählt. Nutze `/train <buch>` zuerst.',
            ephemeral=True)
        return

    book_filename = training['book']
    position = training.get('position', 0)

    results = pick_sequential_lines(book_filename, position, anzahl)
    if not results:
        name = _clean_book_name(book_filename)
        # Position auf 0 zurücksetzen
        _set_user_training(user_id, book_filename, 0)
        await interaction.followup.send(
            f'✅ Alle Linien in **{name}** durchgearbeitet! '
            f'Nutze `/train` erneut zum Zurücksetzen oder wähle ein neues Buch.',
            ephemeral=True)
        return

    # Position updaten
    new_position = position + len(results)
    _set_user_training(user_id, book_filename, new_position)

    # Puzzles aufbereiten (wie in post_puzzle)
    books_config = _load_books_config()
    meta = books_config.get(book_filename, {})
    diff = meta.get('difficulty', '')
    rating = meta.get('rating', 0)

    puzzles = []
    for line_id, original_game in results:
        game = _trim_to_training_position(original_game)
        context = original_game if game is not original_game else None
        puzzles.append((game, context, diff, rating, line_id))

    # Upload (Studien-Reuse wie bei /puzzle)
    reuse_study_id = _get_user_study_id(user_id)
    base_count, base_total = _get_user_puzzle_count(user_id)

    upload_pairs = [(g, c) for g, c, _, _, _ in puzzles]
    urls = await _upload_puzzles_async(upload_pairs, reuse_study_id=reuse_study_id)

    # Studie-ID + Zähler speichern
    first_url = urls[0] if urls else None
    sid = _extract_study_id(first_url) if first_url else None
    if sid:
        _set_user_study_id(user_id, sid,
                           base_count + len(puzzles),
                           base_total + len(puzzles))

    # DM senden
    dm = await interaction.user.create_dm()
    all_book_lines = load_all_lines()
    total_in_book = sum(1 for lid, _ in all_book_lines
                        if lid.startswith(book_filename + ':'))

    puzzle_count = 0
    for i, (game, context, d, r, lid) in enumerate(puzzles):
        puzzle_url = urls[i] if i < len(urls) else None
        is_chapter = context is None  # kein [%tqu] → Kapitel

        if is_chapter:
            # Kapitel: Züge offen anzeigen, keine Puzzle-Buttons
            h = dict(game.headers)
            chapter_name = h.get('White', h.get('Event', 'Kapitel'))
            embed = discord.Embed(
                title=f'📖 Kapitel: {chapter_name}',
                color=0x7fa650)
            embed.set_footer(
                text=f'📖 Training: {position + i + 1}/{total_in_book} · ID: {lid}')
            pgn_moves = _solution_pgn(game)
            if pgn_moves:
                embed.add_field(name='Züge', value=f'`{pgn_moves}`', inline=False)
            msg = await dm.send(embed=embed)
            if puzzle_url:
                await dm.send(f'[Auf Lichess ansehen]({puzzle_url})')
        else:
            puzzle_count += 1
            puzzle_num = base_count + puzzle_count
            puzzle_total = base_total + puzzle_count
            try:
                board = game.board()
                turn = board.turn
                img = await asyncio.to_thread(_render_board, board)
            except Exception:
                turn, img = None, None

            embed = build_puzzle_embed(game, turn=turn,
                                       puzzle_num=puzzle_num,
                                       puzzle_total=puzzle_total,
                                       difficulty=d, rating=r,
                                       line_id=lid)
            embed.set_footer(
                text=f'📖 Training: {position + i + 1}/{total_in_book} · ID: {lid}')

            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                msg = await dm.send(file=file, embed=embed)
            else:
                msg = await dm.send(embed=embed)
            _register_puzzle_msg(msg.id, lid)
            await msg.edit(view=_fresh_button_view())

            # PGN-Lösung, Prelude, Lichess-Link
            await _send_puzzle_followups(dm, game, context, puzzle_url, lid)

    if puzzle_count:
        stats.inc(user_id, 'puzzles', puzzle_count)
    name = _clean_book_name(book_filename)
    await interaction.followup.send(
        f'✅ {len(results)} Linie(n) aus **{name}** per DM gesendet '
        f'({new_position}/{total_in_book}).',
        ephemeral=True)


async def _cmd_endless(bot, interaction: discord.Interaction, buch: int = 0):
    user_id = interaction.user.id
    log.info('/endless von %s: buch=%d', interaction.user, buch)

    # Toggle: wenn bereits aktiv → stoppen
    if is_endless(user_id):
        count = stop_endless(user_id)
        await interaction.response.send_message(
            f'⏹️ Endless-Modus beendet! **{count}** Puzzle(s) gelöst.',
            ephemeral=True)
        return

    # Buch validieren
    book_filename = None
    if buch > 0:
        books = _list_pgn_files()
        if books:
            if 1 <= buch <= len(books):
                book_filename = books[buch - 1]
            else:
                await interaction.response.send_message(
                    f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die verfügbaren Bücher.',
                    ephemeral=True)
                return

    start_endless(user_id, book_filename)
    await interaction.response.defer(ephemeral=True)

    try:
        await post_next_endless(bot, user_id)
        book_info = ''
        if book_filename:
            name = _clean_book_name(book_filename)
            book_info = f' (Buch: **{name}**)'
        await interaction.followup.send(
            f'♾️ Endless-Modus gestartet{book_info}! '
            f'Erstes Puzzle per DM gesendet.\n'
            f'Nach jeder ✅/❌ kommt sofort das nächste. '
            f'Nochmal `/endless` zum Stoppen.',
            ephemeral=True)
    except Exception as e:
        stop_endless(user_id)
        await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)


async def _cmd_ignore_kapitel(
    interaction: discord.Interaction,
    buch: int = 0,
    kapitel: int = 0,
    aktion: discord.app_commands.Choice[str] = None,
):
    await interaction.response.defer(ephemeral=True)

    # Ohne Parameter → Liste aller ignorierten Kapitel
    if buch == 0 and kapitel == 0:
        ignored = sorted(_load_chapter_ignore_list())
        if not ignored:
            await interaction.followup.send(
                'Keine Kapitel ignoriert.', ephemeral=True)
            return
        lines = ['**Ignorierte Kapitel:**']
        for entry in ignored:
            fname, _, prefix = entry.partition(':')
            name = _clean_book_name(fname)
            lines.append(f'• `{name}` — Kapitel {prefix}')
        await interaction.followup.send('\n'.join(lines), ephemeral=True)
        return

    if buch == 0 or kapitel == 0:
        await interaction.followup.send(
            '⚠️ Bitte sowohl `buch` als auch `kapitel` angeben.', ephemeral=True)
        return

    # Buch auflösen
    books = _list_pgn_files()
    if not books:
        await interaction.followup.send(
            f'⚠️ Books-Verzeichnis fehlt: `{BOOKS_DIR}`', ephemeral=True)
        return
    if not 1 <= buch <= len(books):
        await interaction.followup.send(
            f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die verfügbaren Bücher.',
            ephemeral=True)
        return
    book_filename = books[buch - 1]
    book_name = _clean_book_name(book_filename)

    # Chapter-Präfix im tatsächlichen Format finden
    prefix = _find_chapter_prefix(book_filename, kapitel)
    if prefix is None:
        chapters = _list_chapters(book_filename)
        sample = ', '.join(sorted(chapters)[:10])
        more = f' (von {len(chapters)})' if len(chapters) > 10 else ''
        await interaction.followup.send(
            f'⚠️ Kapitel {kapitel} in **{book_name}** nicht gefunden.\n'
            f'Verfügbare Kapitel{more}: `{sample}`',
            ephemeral=True)
        return

    action_value = aktion.value if aktion else 'ignore'
    chapter_count = _list_chapters(book_filename).get(prefix, 0)

    if action_value == 'unignore':
        unignore_chapter(book_filename, prefix)
        log.info('Kapitel reaktiviert: %s:%s', book_filename, prefix)
        await interaction.followup.send(
            f'♻️ Kapitel **{prefix}** in **{book_name}** wieder aktiviert '
            f'({chapter_count} Linien).',
            ephemeral=True)
    else:
        ignore_chapter(book_filename, prefix)
        log.info('Kapitel ignoriert: %s:%s', book_filename, prefix)
        await interaction.followup.send(
            f'🚮 Kapitel **{prefix}** in **{book_name}** ignoriert '
            f'({chapter_count} Linien werden nicht mehr gepostet).',
            ephemeral=True)


def setup(bot: discord.ext.commands.Bot):
    """Registriert alle Puzzle-Commands auf dem Bot."""
    tree = bot.tree

    @tree.command(name='puzzle', description='Puzzle(s) aus den Büchern posten')
    @discord.app_commands.describe(
        anzahl='Anzahl Puzzles (1–20, Standard: 1)',
        buch='Buchnummer aus /kurs (Standard: alle Bücher)',
        id='Puzzle-ID (z.B. datei.pgn:123) – zeigt genau dieses Puzzle',
        user='Puzzle an diesen User schicken (Standard: an dich selbst)',
    )
    async def cmd_puzzle(interaction: discord.Interaction, anzahl: int = 1, buch: int = 0,
                         id: str = '', user: discord.Member | None = None):
        await _cmd_puzzle(interaction, anzahl, buch, id, user)

    @tree.command(name='kurs', description='Puzzle-Bücher anzeigen; optional Details zu einem Buch')
    @discord.app_commands.describe(
        buch='Buchnummer aus /kurs für Detailansicht mit allen Kapiteln',
    )
    async def cmd_buecher(interaction: discord.Interaction, buch: int = 0):
        await _cmd_buecher(interaction, buch)

    @tree.command(name='train', description='Buch für sequentielles Training auswählen')
    @discord.app_commands.describe(
        buch='Buchnummer aus /kurs (0 = Training beenden, leer = Status anzeigen)',
    )
    async def cmd_train(interaction: discord.Interaction, buch: int = None):
        await _cmd_train(interaction, buch)

    @tree.command(name='next', description='Nächste Linie(n) aus dem Trainingsbuch')
    @discord.app_commands.describe(
        anzahl='Anzahl Linien (Standard: 1, max 20)',
    )
    async def cmd_next(interaction: discord.Interaction, anzahl: int = 1):
        await _cmd_next(interaction, anzahl)

    @tree.command(name='endless', description='Endlos-Puzzle-Modus starten/stoppen')
    @discord.app_commands.describe(
        buch='Buchnummer aus /kurs (Standard: alle Bücher)',
    )
    async def cmd_endless(interaction: discord.Interaction, buch: int = 0):
        await _cmd_endless(bot, interaction, buch)

    @tree.command(name='ignore_kapitel',
                  description='Ein ganzes Kapitel ignorieren oder Liste anzeigen (Admin)')
    @discord.app_commands.describe(
        buch='Buchnummer aus /kurs',
        kapitel='Kapitel-Nummer (z.B. 3)',
        aktion='ignore = ignorieren · unignore = wieder aktivieren · list = ohne Parameter zeigen',
    )
    @discord.app_commands.choices(aktion=[
        discord.app_commands.Choice(name='ignore', value='ignore'),
        discord.app_commands.Choice(name='unignore', value='unignore'),
    ])
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_ignore_kapitel(
        interaction: discord.Interaction,
        buch: int = 0,
        kapitel: int = 0,
        aktion: discord.app_commands.Choice[str] = None,
    ):
        await _cmd_ignore_kapitel(interaction, buch, kapitel, aktion)
