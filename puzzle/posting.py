"""Discord-Posting: Puzzles rendern, uploaden und in Channels/DMs senden."""

import asyncio
import concurrent.futures
import logging
import random
import time as _time_mod
from datetime import date as _date

import chess
import chess.pgn
import discord

from core import stats
from puzzle.buttons import fresh_view as _fresh_button_view
from puzzle.embed import build_puzzle_embed
import puzzle.rookhub as rookhub
from puzzle.processing import (
    _solution_pgn, _prelude_pgn, _trim_to_training_position,
    _split_for_blind, _format_blind_moves,
)
from puzzle.rendering import _render_board, safe_render_board
from puzzle.selection import _list_pgn_files, pick_random_lines, pick_random_blind_lines
from puzzle.state import (
    _register_puzzle_msg, _endless_sessions, stop_endless,
    _load_books_config, _get_user_puzzle_count,
    save_puzzle_context,
)

log = logging.getLogger('schach-bot')

_DISCORD_THREAD_NAME_MAX = 100


def _build_puzzle_context(game, turn, diff, line_id, include_solution=True):
    """Baut ein dict mit Puzzle-Metadaten fuer den KI-Chat-Kontext."""
    h = dict(game.headers)
    ctx = {
        'book': h.get('Event', ''),
        'chapter': h.get('Black', ''),
        'line': h.get('White', ''),
        'fen': game.board().fen(),
        'turn': 'Weiss' if turn == chess.WHITE else 'Schwarz',
        'difficulty': diff,
        'line_id': line_id,
    }
    if include_solution:
        ctx['solution'] = _solution_pgn(game)
    return ctx


# Thread-Executor – wird nur noch von der /test-Diagnose für Lichess-Checks genutzt.
# Das produktive Puzzle-Posting läuft über RookHub (siehe post_rookhub_puzzle).
_lichess_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2,
                                                          thread_name_prefix='lichess')


async def _send_puzzle_followups(target, game: chess.pgn.Game,
                                 context: chess.pgn.Game | None,
                                 line_id: str,
                                 show_board: bool = True):
    """Lösung, Prelude und RookHub-Link als optionale Follow-ups senden.

    show_board=False unterdrückt Lösung und Prelude (nur RookHub-Link bleibt).
    """
    if show_board:
        pgn_moves = _solution_pgn(game)
        if pgn_moves:
            await _send_optional(target, f'Lösung: ||`{pgn_moves}`||', label=f'Lösung {line_id}')
        if context:
            prelude = _prelude_pgn(context, game)
            if prelude:
                await _send_optional(target, f'Ganze Partie: ||`{prelude}`||', label=f'Partie {line_id}')
    # RookHub-Link via line_id-Lookup (synchroner HTTP-Call → in Thread auslagern)
    url = await asyncio.to_thread(rookhub.web_url_for_line, line_id)
    if url:
        await _send_optional(target, f'[Klickbares Rätsel]({url})', label=f'RookHub-Link {line_id}')


async def post_next_endless(bot, user_id: int):
    """Nächstes Puzzle im Endless-Modus per DM senden."""
    session = _endless_sessions.get(user_id)
    if not session:
        return
    # Guard gegen Doppel-Sends bei schnellen Klicks (Race via create_task)
    if session.get('_sending'):
        return
    session['_sending'] = True
    try:
        book_filename = session['book']
        results = await asyncio.to_thread(pick_random_lines, 1, book_filename)
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

        turn, img = await safe_render_board(game)

        embed = build_puzzle_embed(game, turn=turn, difficulty=diff, rating=rating, line_id=line_id)
        embed.set_footer(text=f'♾️ Endless-Modus · Puzzle #{session["count"]} · ID: {line_id}')

        if img:
            file = discord.File(img, filename='board.png')
            embed.set_image(url='attachment://board.png')
            msg = await dm.send(file=file, embed=embed)
        else:
            msg = await dm.send(embed=embed)

        _register_puzzle_msg(msg.id, line_id)
        save_puzzle_context(user_id, _build_puzzle_context(game, turn, diff, line_id))
        await msg.edit(view=_fresh_button_view())

        # Lösung, Prelude, RookHub-Link
        await _send_puzzle_followups(dm, game, context, line_id)

        stats.inc(user_id, 'puzzles', 1)
    finally:
        session.pop('_sending', None)


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


async def post_puzzle(channel, count: int = 1, book_idx: int = 0,
                      user_id: int | None = None, show_board: bool = True) -> int:
    """Puzzles auswählen, rendern und posten.

    count      – Anzahl Puzzles (1–20).
    book_idx   – 1-basierte Buchnummer aus /kurs (0 = alle Bücher).
    user_id    – Discord-User-ID; wenn gesetzt, wird die Tages-Studie wiederverwendet.
    show_board – False: kein Brettbild, keine Lösung – nur Embed + RookHub-Link.

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

    results = await asyncio.to_thread(pick_random_lines, count, book_filename)
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

    base_count, base_total = _get_user_puzzle_count(user_id) if user_id else (0, 0)

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
            puzzle_num   = (base_count + i + 1) if user_id else 0
            puzzle_total = (base_total + i + 1) if user_id else 0

            if show_board:
                turn, img = await safe_render_board(game)
            else:
                # Nur turn ermitteln fuer Embed, kein Bild rendern
                board = game.board()
                for move in game.mainline_moves():
                    board.push(move)
                turn = board.turn
                img = None

            embed = build_puzzle_embed(game, turn=turn, puzzle_num=puzzle_num, puzzle_total=puzzle_total, difficulty=diff, rating=rating, line_id=lid)
            # Haupt-Send: Brett + Embed. Nur das ist der Erfolgs-Anker;
            # alles danach (Lösung, RookHub-Link) ist optional und darf
            # bei Discord-5xx das Puzzle nicht als gescheitert markieren.
            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                msg = await _resilient_send(target, file=file, embed=embed)
            else:
                msg = await _resilient_send(target, embed=embed)
            posted_ok += 1
            _register_puzzle_msg(msg.id, lid)
            save_puzzle_context(user_id, _build_puzzle_context(game, turn, diff, lid))
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

        await _send_puzzle_followups(target, game, context, lid, show_board=show_board)

    log.info('post_puzzle: %d/%d Puzzle(s) gepostet', posted_ok, len(puzzles))
    if user_id and posted_ok:
        stats.inc(user_id, 'puzzles', posted_ok)
    return posted_ok


async def post_rookhub_puzzle(channel, pool: str = 'daily',
                              user_id: int | None = None, exclude=None) -> bool:
    """Holt ein Puzzle aus dem RookHub-Pool (``daily`` | ``random`` | ``blind``),
    rendert Brett + Embed und postet zusätzlich den RookHub-Link. Die Auswahl
    übernimmt RookHub. Gibt True bei Erfolg zurück.
    """
    dto = await asyncio.to_thread(rookhub.get_puzzle, pool, exclude)
    if not dto:
        await _send_optional(channel, f'⚠️ Kein {pool}-Puzzle in RookHub verfügbar.',
                             label=f'rookhub-{pool}')
        return False

    try:
        game, _solution = rookhub.game_from_puzzle(dto)
    except Exception as e:
        log.exception('RookHub-Puzzle %s konnte nicht aufbereitet werden: %s',
                      dto.get('lineId'), e)
        return False

    line_id = dto.get('lineId', '')
    diff = dto.get('difficulty') or ''
    rating = dto.get('bookRating') or 0
    web_url = rookhub.puzzle_web_url(dto.get('id'))

    # Ziel: Thread (Server) oder direkt (DM / bestehender Thread)
    is_dm = isinstance(channel, discord.DMChannel)
    if is_dm or isinstance(channel, discord.Thread):
        target = channel
    else:
        label = {'daily': 'Tagespuzzle', 'random': 'Zufallspuzzle',
                 'blind': 'Blindpuzzle'}.get(pool, 'Puzzle')
        today = _date.today().strftime('%d.%m.%Y')
        thread_name = f'{label} – {today}'[:_DISCORD_THREAD_NAME_MAX]
        try:
            target = await channel.create_thread(
                name=thread_name, type=discord.ChannelType.public_thread,
                auto_archive_duration=1440)
        except Exception:
            target = channel

    try:
        turn, img = await safe_render_board(game)
        embed = build_puzzle_embed(game, turn=turn, difficulty=diff, rating=rating,
                                   line_id=line_id)
        if img:
            file = discord.File(img, filename='board.png')
            embed.set_image(url='attachment://board.png')
            msg = await _resilient_send(target, file=file, embed=embed)
        else:
            msg = await _resilient_send(target, embed=embed)
    except Exception as e:
        log.exception('RookHub-Puzzle-Post fehlgeschlagen (%s): %s', line_id, e)
        return False

    _register_puzzle_msg(msg.id, line_id)
    save_puzzle_context(user_id, _build_puzzle_context(game, turn, diff, line_id))

    # Lösung (Spoiler) + RookHub-Link als optionale Follow-ups
    pgn_moves = _solution_pgn(game)
    if pgn_moves:
        await _send_optional(target, f'Lösung: ||`{pgn_moves}`||', label=f'Lösung {line_id}')
    if web_url:
        await _send_optional(target, f'[Klickbares Rätsel auf RookHub]({web_url})',
                             label=f'RookHub-Link {line_id}')

    if user_id:
        stats.inc(user_id, 'puzzles', 1)
    return True


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

    results = await asyncio.to_thread(pick_random_blind_lines, count, book_filename, moves)
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
    if is_dm or isinstance(channel, discord.Thread):
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
            save_puzzle_context(user_id,
                                _build_puzzle_context(puzzle_game, blind_board.turn,
                                                      diff, line_id, include_solution=False))
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
