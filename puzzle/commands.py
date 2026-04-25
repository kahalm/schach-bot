"""Puzzle Slash-Commands: /puzzle, /kurs, /train, /next, /endless, /ignore_kapitel."""

import asyncio
import logging
import os
import re
from collections import defaultdict

import chess
import chess.pgn
import discord

from core import stats

# Funktionen werden über puzzle.legacy referenziert (nicht direkt importiert),
# damit Test-Monkeypatches auf puzzle.legacy.X auch hier wirken.
# Die zirkuläre Abhängigkeit ist sicher, weil alle Re-Exports in legacy.py
# vor dem 'from puzzle.commands import ...' definiert sind.
import puzzle.legacy as _leg

log = logging.getLogger('schach-bot')

PUZZLE_HOUR   = int(os.getenv('PUZZLE_HOUR', '9'))
PUZZLE_MINUTE = int(os.getenv('PUZZLE_MINUTE', '0'))
CHANNEL_ID    = int(os.getenv('CHANNEL_ID', '0'))


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

            result = _leg.find_line_by_id(_lookup_id)
            if not result:
                await interaction.followup.send(f'⚠️ Puzzle `{id}` nicht gefunden.', ephemeral=True)
                return

            if not _leg._has_training_comment(result[1]):
                await interaction.followup.send(
                    f'⚠️ `{id}` hat keinen Trainingskommentar.', ephemeral=True)
                return

            if _blind_moves:
                if user:
                    await dm.send(f'**{interaction.user.display_name}** schickt dir ein Blind-Puzzle 🙈')
                line_id = result[0]
                orig = result[1]
                split = _leg._split_for_blind(orig, _blind_moves)
                if split is None:
                    await interaction.followup.send(
                        f'⚠️ Puzzle `{line_id}` hat nicht genug Vorlauf-Züge für blind:{_blind_moves}.',
                        ephemeral=True)
                    return
                blind_board, blind_san, puzzle_game = split
                fname = line_id.split(':')[0]
                meta  = _leg._load_books_config().get(fname, {})
                try:
                    img = await asyncio.to_thread(_leg._render_board, blind_board)
                except Exception:
                    img = None
                embed = _leg.build_puzzle_embed(
                    puzzle_game, turn=blind_board.turn,
                    difficulty=meta.get('difficulty',''), rating=meta.get('rating', 0),
                    line_id=line_id, blind_moves=_blind_moves)
                embed.title = f'🙈 Blind-Puzzle ({_blind_moves} Züge)'
                blind_pgn = _leg._format_blind_moves(blind_board, blind_san)
                embed.add_field(name='🙈 Spiele in Gedanken',
                                value=f'`{blind_pgn}`\n_Visualisiere die Stellung danach und löse das Puzzle._',
                                inline=False)
                if img:
                    file = discord.File(img, filename='board.png')
                    embed.set_image(url='attachment://board.png')
                    msg = await _leg._resilient_send(dm, file=file, embed=embed)
                else:
                    msg = await _leg._resilient_send(dm, embed=embed)
                _leg._register_puzzle_msg(msg.id, line_id, mode='blind')
                try:
                    from puzzle.buttons import fresh_view as _fresh_button_view
                    await msg.edit(view=_fresh_button_view())
                except Exception:
                    pass
                pgn_moves = _leg._solution_pgn(puzzle_game)
                if pgn_moves:
                    await _leg._send_optional(dm, f'Lösung des Puzzles: ||`{pgn_moves}`||', label=f'Blind-Lösung {line_id}')
                dest = f'an {target_user.mention}' if user else 'dir'
                await interaction.followup.send(f'🙈 Blind-Puzzle `{line_id}:blind:{_blind_moves}` {dest} per DM gesendet.', ephemeral=True)
                return

            line_id, original_game = result
            game = _leg._trim_to_training_position(original_game)
            context = original_game if game is not original_game else None

            books_config = _leg._load_books_config()
            fname = line_id.split(':')[0]
            book_meta = books_config.get(fname, {})
            diff = book_meta.get('difficulty', '')
            rating = book_meta.get('rating', 0)

            # Upload
            reuse_study_id = _leg._get_user_study_id(target_uid)
            urls = await _leg._upload_puzzles_async([(game, context)], reuse_study_id=reuse_study_id)
            puzzle_url = urls[0] if urls else None

            try:
                board = game.board()
                turn = board.turn
                img = await asyncio.to_thread(_leg._render_board, board)
            except Exception:
                turn, img = None, None

            if user:
                await dm.send(f'**{interaction.user.display_name}** schickt dir ein Rätsel 🧩')

            embed = _leg.build_puzzle_embed(game, turn=turn, difficulty=diff, rating=rating, line_id=line_id)
            if img:
                file = discord.File(img, filename='board.png')
                embed.set_image(url='attachment://board.png')
                msg = await dm.send(file=file, embed=embed)
            else:
                msg = await dm.send(embed=embed)
            _leg._register_puzzle_msg(msg.id, line_id)
            from puzzle.buttons import fresh_view as _fresh_button_view
            await msg.edit(view=_fresh_button_view())

            await _leg._send_puzzle_followups(dm, game, context, puzzle_url, line_id)

            dest = f'an {target_user.mention}' if user else 'dir'
            await interaction.followup.send(
                f'✅ Puzzle `{line_id}` {dest} per DM gesendet.', ephemeral=True)
            return

        if user:
            await dm.send(f'**{interaction.user.display_name}** schickt dir ein Rätsel 🧩')
        sent = await _leg.post_puzzle(dm, count=anzahl, book_idx=buch, user_id=target_uid)
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
        all_lines = _leg.load_all_lines()
        posted    = set(_leg.load_puzzle_state().get('posted', []))
        books_config = _leg._load_books_config()

        # --- Detailansicht für ein einzelnes Buch ---
        if buch > 0:
            sorted_books = sorted(set(lid.split(':')[0] for lid, _ in all_lines))
            if buch > len(sorted_books):
                await interaction.followup.send(
                    f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die Liste.',
                    ephemeral=True)
                return
            book_fn = sorted_books[buch - 1]
            book_name = _leg._clean_book_name(book_fn)
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
            chapter_ignored = _leg._load_chapter_ignore_list()
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
            name  = _leg._clean_book_name(book)
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
        training = _leg._get_user_training(user_id)
        if not training:
            await interaction.followup.send(
                '📭 Kein Training aktiv. Wähle ein Buch mit `/train <nummer>` '
                '(Nummern aus `/kurs`).', ephemeral=True)
            return
        book_filename = training['book']
        pos = training['position']
        all_lines = _leg.load_all_lines()
        total = sum(1 for lid, _ in all_lines if lid.startswith(book_filename + ':'))
        name = _leg._clean_book_name(book_filename)
        books = _leg._list_pgn_files()
        kurs_nr = books.index(book_filename) + 1 if book_filename in books else 0
        books_config = _leg._load_books_config()
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
        _leg._clear_user_training(user_id)
        await interaction.followup.send('🔓 Training beendet.', ephemeral=True)
        return

    # Buch validieren
    books = _leg._list_pgn_files()
    if not books:
        await interaction.followup.send('⚠️ Kein books-Ordner.', ephemeral=True)
        return
    if buch < 1 or buch > len(books):
        await interaction.followup.send(
            f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die Liste.', ephemeral=True)
        return

    book_filename = books[buch - 1]
    # Aktuelle Position beibehalten falls selbes Buch
    training = _leg._get_user_training(user_id)
    if training and training.get('book') == book_filename:
        pos = training['position']
    else:
        pos = 0

    _leg._set_user_training(user_id, book_filename, pos)

    # Info anzeigen
    all_lines = _leg.load_all_lines()
    total = sum(1 for lid, _ in all_lines if lid.startswith(book_filename + ':'))
    name = _leg._clean_book_name(book_filename)
    books_config = _leg._load_books_config()
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

    training = _leg._get_user_training(user_id)
    if not training:
        await interaction.followup.send(
            '⚠️ Kein Trainingsbuch gewählt. Nutze `/train <buch>` zuerst.',
            ephemeral=True)
        return

    book_filename = training['book']
    position = training.get('position', 0)

    results = _leg.pick_sequential_lines(book_filename, position, anzahl)
    if not results:
        name = _leg._clean_book_name(book_filename)
        # Position auf 0 zurücksetzen
        _leg._set_user_training(user_id, book_filename, 0)
        await interaction.followup.send(
            f'✅ Alle Linien in **{name}** durchgearbeitet! '
            f'Nutze `/train` erneut zum Zurücksetzen oder wähle ein neues Buch.',
            ephemeral=True)
        return

    # Position updaten
    new_position = position + len(results)
    _leg._set_user_training(user_id, book_filename, new_position)

    # Puzzles aufbereiten (wie in post_puzzle)
    books_config = _leg._load_books_config()
    meta = books_config.get(book_filename, {})
    diff = meta.get('difficulty', '')
    rating = meta.get('rating', 0)

    puzzles = []
    for line_id, original_game in results:
        game = _leg._trim_to_training_position(original_game)
        context = original_game if game is not original_game else None
        puzzles.append((game, context, diff, rating, line_id))

    # Upload (Studien-Reuse wie bei /puzzle)
    reuse_study_id = _leg._get_user_study_id(user_id)
    base_count, base_total = _leg._get_user_puzzle_count(user_id)

    upload_pairs = [(g, c) for g, c, _, _, _ in puzzles]
    urls = await _leg._upload_puzzles_async(upload_pairs, reuse_study_id=reuse_study_id)

    # Studie-ID + Zähler speichern
    first_url = urls[0] if urls else None
    sid = _leg._extract_study_id(first_url) if first_url else None
    if sid:
        _leg._set_user_study_id(user_id, sid,
                           base_count + len(puzzles),
                           base_total + len(puzzles))

    # DM senden
    dm = await interaction.user.create_dm()
    all_book_lines = _leg.load_all_lines()
    total_in_book = sum(1 for lid, _ in all_book_lines
                        if lid.startswith(book_filename + ':'))

    from puzzle.buttons import fresh_view as _fresh_button_view

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
            pgn_moves = _leg._solution_pgn(game)
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
                img = await asyncio.to_thread(_leg._render_board, board)
            except Exception:
                turn, img = None, None

            embed = _leg.build_puzzle_embed(game, turn=turn,
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
            _leg._register_puzzle_msg(msg.id, lid)
            await msg.edit(view=_fresh_button_view())

            # PGN-Lösung, Prelude, Lichess-Link
            await _leg._send_puzzle_followups(dm, game, context, puzzle_url, lid)

    if puzzle_count:
        stats.inc(user_id, 'puzzles', puzzle_count)
    name = _leg._clean_book_name(book_filename)
    await interaction.followup.send(
        f'✅ {len(results)} Linie(n) aus **{name}** per DM gesendet '
        f'({new_position}/{total_in_book}).',
        ephemeral=True)


async def _cmd_endless(bot, interaction: discord.Interaction, buch: int = 0):
    user_id = interaction.user.id
    log.info('/endless von %s: buch=%d', interaction.user, buch)

    # Toggle: wenn bereits aktiv → stoppen
    if _leg.is_endless(user_id):
        count = _leg.stop_endless(user_id)
        await interaction.response.send_message(
            f'⏹️ Endless-Modus beendet! **{count}** Puzzle(s) gelöst.',
            ephemeral=True)
        return

    # Buch validieren
    book_filename = None
    if buch > 0:
        books = _leg._list_pgn_files()
        if books:
            if 1 <= buch <= len(books):
                book_filename = books[buch - 1]
            else:
                await interaction.response.send_message(
                    f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die verfügbaren Bücher.',
                    ephemeral=True)
                return

    _leg.start_endless(user_id, book_filename)
    await interaction.response.defer(ephemeral=True)

    try:
        await _leg.post_next_endless(bot, user_id)
        book_info = ''
        if book_filename:
            name = _leg._clean_book_name(book_filename)
            book_info = f' (Buch: **{name}**)'
        await interaction.followup.send(
            f'♾️ Endless-Modus gestartet{book_info}! '
            f'Erstes Puzzle per DM gesendet.\n'
            f'Nach jeder ✅/❌ kommt sofort das nächste. '
            f'Nochmal `/endless` zum Stoppen.',
            ephemeral=True)
    except Exception as e:
        _leg.stop_endless(user_id)
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
        ignored = sorted(_leg._load_chapter_ignore_list())
        if not ignored:
            await interaction.followup.send(
                'Keine Kapitel ignoriert.', ephemeral=True)
            return
        lines = ['**Ignorierte Kapitel:**']
        for entry in ignored:
            fname, _, prefix = entry.partition(':')
            name = _leg._clean_book_name(fname)
            lines.append(f'• `{name}` — Kapitel {prefix}')
        await interaction.followup.send('\n'.join(lines), ephemeral=True)
        return

    if buch == 0 or kapitel == 0:
        await interaction.followup.send(
            '⚠️ Bitte sowohl `buch` als auch `kapitel` angeben.', ephemeral=True)
        return

    # Buch auflösen
    books = _leg._list_pgn_files()
    if not books:
        await interaction.followup.send(
            f'⚠️ Books-Verzeichnis fehlt: `{_leg.BOOKS_DIR}`', ephemeral=True)
        return
    if not 1 <= buch <= len(books):
        await interaction.followup.send(
            f'⚠️ Buch {buch} nicht gefunden. `/kurs` zeigt die verfügbaren Bücher.',
            ephemeral=True)
        return
    book_filename = books[buch - 1]
    book_name = _leg._clean_book_name(book_filename)

    # Chapter-Präfix im tatsächlichen Format finden
    prefix = _leg._find_chapter_prefix(book_filename, kapitel)
    if prefix is None:
        chapters = _leg._list_chapters(book_filename)
        sample = ', '.join(sorted(chapters)[:10])
        more = f' (von {len(chapters)})' if len(chapters) > 10 else ''
        await interaction.followup.send(
            f'⚠️ Kapitel {kapitel} in **{book_name}** nicht gefunden.\n'
            f'Verfügbare Kapitel{more}: `{sample}`',
            ephemeral=True)
        return

    action_value = aktion.value if aktion else 'ignore'
    chapter_count = _leg._list_chapters(book_filename).get(prefix, 0)

    if action_value == 'unignore':
        _leg.unignore_chapter(book_filename, prefix)
        log.info('Kapitel reaktiviert: %s:%s', book_filename, prefix)
        await interaction.followup.send(
            f'♻️ Kapitel **{prefix}** in **{book_name}** wieder aktiviert '
            f'({chapter_count} Linien).',
            ephemeral=True)
    else:
        _leg.ignore_chapter(book_filename, prefix)
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
