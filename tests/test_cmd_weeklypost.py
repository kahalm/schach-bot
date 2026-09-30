"""Tests fuer den Wochenpost-Pull-Announcer (commands/weeklypost.py)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    FakeChannel, atomic_read,
)
import commands.weeklypost as wp


def _iso(dt):
    return dt.isoformat()


def test_weekly_announcer():
    """Pull-Loop: First-Run-Seed (kein Backlog-Spam), faellige Posts ankuendigen, kein Doppelposten,
    Zukunft/zu-alt ueberspringen."""
    print('[weekly announcer]')
    tmpdir = setup_temp_config()
    ch = FakeChannel(channel_id=88888)
    fake_bot = MagicMock()
    fake_bot.get_channel = lambda cid: ch if cid == 88888 else None
    old_bot, old_cid = wp._bot, wp._channel_id
    orig_get = wp.rookhub.get_weekly_posts
    wp._bot, wp._channel_id = fake_bot, 88888
    try:
        now = datetime.now(timezone.utc)
        due = {'id': 1, 'title': 'Woche 1', 'scheduledAt': _iso(now - timedelta(hours=1))}
        future = {'id': 2, 'title': 'Zukunft', 'scheduledAt': _iso(now + timedelta(days=2))}
        old = {'id': 3, 'title': 'Uralt', 'scheduledAt': _iso(now - timedelta(days=30))}

        # 1) Erster Lauf: bestehende Posts werden geseedet, NICHTS gepostet (kein Backlog-Spam).
        wp.rookhub.get_weekly_posts = lambda timeout=15: [due, future, old]
        run_async(wp.run_weekly_announcements())
        check('first run: kein Post (seed)', len(ch.threads) == 0)
        state = atomic_read(wp.WEEKLY_STATE_FILE, default=dict)
        check('first run: seeded-Flag gesetzt', state.get('seeded') is True)
        check('first run: alle IDs als posted geseedet', set(state.get('posted_ids', [])) == {1, 2, 3})

        # 2) Neuer, faelliger Post nach dem Seed → wird angekuendigt.
        new_due = {'id': 4, 'title': 'Neu faellig', 'scheduledAt': _iso(now - timedelta(minutes=5))}
        wp.rookhub.get_weekly_posts = lambda timeout=15: [due, future, old, new_due]
        run_async(wp.run_weekly_announcements())
        check('neuer faelliger Post → 1 Thread', len(ch.threads) == 1)
        check('Thread-Name enthält Datum + Titel', ch.threads[0].name.endswith('· Neu faellig') and ch.threads[0].name[:2].isdigit())

        # 3) Kein Doppelposten beim naechsten Poll.
        run_async(wp.run_weekly_announcements())
        check('kein Doppelposten', len(ch.threads) == 1)

        # 4) Neuer Zukunfts-Post wird NICHT gepostet.
        fut_new = {'id': 5, 'title': 'Zukunft neu', 'scheduledAt': _iso(now + timedelta(days=1))}
        wp.rookhub.get_weekly_posts = lambda timeout=15: [new_due, fut_new]
        run_async(wp.run_weekly_announcements())
        check('Zukunfts-Post nicht gepostet', len(ch.threads) == 1)

        # 5) Neuer, aber zu alter Post (ausserhalb Catch-up-Fenster) wird NICHT gepostet.
        too_old = {'id': 6, 'title': 'Zu alt', 'scheduledAt': _iso(now - timedelta(days=30))}
        wp.rookhub.get_weekly_posts = lambda timeout=15: [new_due, too_old]
        run_async(wp.run_weekly_announcements())
        check('zu alter Post nicht gepostet', len(ch.threads) == 1)

    finally:
        wp.rookhub.get_weekly_posts = orig_get
        wp._bot, wp._channel_id = old_bot, old_cid
        teardown_temp_config(tmpdir)
    print()


def test_weekly_announcement_prefills_progress():
    """Beim Ankündigen wird das Fortschritts-Feld sofort aus den RookHub-Results befüllt — auch wenn
    die Versuche schon VOR der Ankündigung aufgezeichnet wurden (Admin-Vorschau / Bot-Downtime), wo
    der Webhook ins Leere ging (noch kein Thread)."""
    print('[weekly announcement prefills progress]')
    tmpdir = setup_temp_config()
    ch = FakeChannel(channel_id=88888)
    orig_results = wp.rookhub.get_weekly_results
    try:
        wp.rookhub.get_weekly_results = lambda wid, timeout=15: {
            'total': 3, 'completedCount': 1,
            'players': [
                {'name': 'kahalm', 'discordId': '728', 'discordUsername': 'kahalm',
                 'solvedCount': 3, 'playedCount': 3, 'totalSeconds': 90, 'completed': True},
            ],
        }
        post = {'id': 5, 'title': 'Mate P2', 'scheduledAt': '2026-06-19T18:00:00'}
        run_async(wp._post_announcement(ch, post))

        check('Thread erstellt', len(ch.threads) == 1)
        msg = ch.threads[0].sent[0]
        embed = msg.kwargs.get('embed')
        field = next((f for f in embed.fields if f.get('name') == wp._WEEKLY_FIELD), None)
        check('Fortschritts-Feld vorhanden', field is not None)
        check('Löser im Feld', field is not None and '<@728>' in field['value'])
        # Thread/Message gemerkt → spätere Webhook-Updates greifen.
        check('Thread gemerkt', wp._thread_for(5) is not None)

        # Ohne Results-Daten (noch niemand) → kein Feld, aber Ankündigung trotzdem.
        ch2 = FakeChannel(channel_id=88888)
        wp.rookhub.get_weekly_results = lambda wid, timeout=15: {'total': 3, 'completedCount': 0, 'players': []}
        run_async(wp._post_announcement(ch2, {'id': 6, 'title': 'Leer', 'scheduledAt': '2026-06-19T18:00:00'}))
        embed2 = ch2.threads[0].sent[0].kwargs.get('embed')
        has_field = any(f.get('name') == wp._WEEKLY_FIELD for f in embed2.fields)
        check('kein Feld ohne Löser', not has_field)
    finally:
        wp.rookhub.get_weekly_results = orig_results
        teardown_temp_config(tmpdir)
    print()


def test_weekly_announcement_includes_description():
    """Die optionale RookHub-Beschreibung wird in die Embed-Beschreibung uebernommen; ohne Beschreibung
    bleibt die Standardzeile."""
    print('[weekly announcement includes description]')
    tmpdir = setup_temp_config()
    orig_results = wp.rookhub.get_weekly_results
    try:
        wp.rookhub.get_weekly_results = lambda wid, timeout=15: {'total': 2, 'completedCount': 0, 'players': []}

        ch = FakeChannel(channel_id=88888)
        post = {'id': 7, 'title': 'Mate in 2', 'description': 'Diese Woche: Damenopfer!',
                'scheduledAt': '2026-06-19T18:00:00'}
        run_async(wp._post_announcement(ch, post))
        embed = ch.threads[0].sent[0].kwargs.get('embed')
        check('Beschreibung im Embed', 'Damenopfer' in (embed.description or ''))
        check('Standardzeile bleibt daneben', 'Wochenpost' in (embed.description or ''))

        # Ohne Beschreibung → nur die Standardzeile.
        ch2 = FakeChannel(channel_id=88888)
        run_async(wp._post_announcement(ch2, {'id': 8, 'title': 'Ohne', 'scheduledAt': '2026-06-19T18:00:00'}))
        embed2 = ch2.threads[0].sent[0].kwargs.get('embed')
        check('Standardzeile ohne Beschreibung', 'Wochenpost' in (embed2.description or ''))
    finally:
        wp.rookhub.get_weekly_results = orig_results
        teardown_temp_config(tmpdir)
    print()


def test_weekly_results_format():
    """format_weekly_results: wer erledigt + gelöst/total + Gesamtzeit je User (rein)."""
    print('[weekly results format]')
    empty = wp.format_weekly_results({'players': [], 'total': 5, 'completedCount': 0})
    check('leer → Hinweis', 'niemand' in empty.lower())

    res = {
        'total': 5, 'completedCount': 1,
        'players': [
            {'name': 'Alice', 'discordId': 'd1', 'solvedCount': 4, 'playedCount': 5, 'totalSeconds': 90, 'completed': True, 'hintsUsed': 2},
            {'name': 'Bob', 'discordId': None, 'solvedCount': 2, 'playedCount': 3, 'totalSeconds': 605, 'completed': False, 'hintsUsed': 0},
        ],
    }
    out = wp.format_weekly_results(res)
    check('discord-mention', '<@d1>' in out)
    check('name-fallback ohne discord', 'Bob' in out)
    check('x/y angezeigt', '4/5' in out and '2/5' in out)
    check('gesamtzeit formatiert (m:ss)', '1:30' in out and '10:05' in out)
    check('erledigt-marker ✅', '✅' in out)
    check('completed-count im Header', '1 erledigt' in out)
    # 💡 nur bei Spielern, die mit Tipps gelöst haben (hintsUsed > 0).
    alice_line = [l for l in out.splitlines() if '<@d1>' in l][0]
    bob_line = [l for l in out.splitlines() if 'Bob' in l][0]
    check('💡 bei Alice (mit Tipps)', '💡' in alice_line)
    check('kein 💡 bei Bob (ohne Tipps)', '💡' not in bob_line)
    check('normale Namen byte-gleich', bob_line == 'Bob — 2/5 · 10:05')

    # S4-003: frei waehlbare RookHub-Namen duerfen im Embed kein Markdown/keinen Masked Link bilden.
    evil = wp.format_weekly_results({'total': 1, 'completedCount': 0, 'players': [
        {'name': '[Gratis Nitro](https://evil.example/n)', 'solvedCount': 1, 'totalSeconds': 5},
        {'name': '# Header\n> Zitat', 'solvedCount': 1, 'totalSeconds': 5},
    ]})
    check('Masked Link im Namen zerlegt', '[Gratis Nitro](' not in evil and '\\[Gratis Nitro\\]' in evil)
    check('Header/Zitat im Namen escaped, kein Zeilenumbruch',
          '\\# Header \\> Zitat' in evil and len(evil.splitlines()) == 3)
    print()


def test_weekly_results_modes():
    """Modus-Anzeige: 'einfach' (Figuren ziehbar) wird ausgewiesen, reines Training bleibt unmarkiert;
    fehlende Felder (aeltere RookHub-Version) aendern die Ausgabe nicht."""
    print('[weekly results modes]')
    res = {
        'total': 5, 'completedCount': 0,
        'players': [
            # nur Training → keine Modus-Markierung (Standardfall, haelt die Liste ruhig)
            {'name': 'Trainer', 'solvedCount': 5, 'playedCount': 5, 'totalSeconds': 60,
             'trainingCount': 5, 'easyCount': 0},
            # gemischt → Anzahl der einfachen Puzzles
            {'name': 'Mixi', 'solvedCount': 4, 'playedCount': 5, 'totalSeconds': 60,
             'trainingCount': 3, 'easyCount': 2},
            # nur einfach
            {'name': 'Easy', 'solvedCount': 3, 'playedCount': 3, 'totalSeconds': 60,
             'trainingCount': 0, 'easyCount': 3},
        ],
    }
    out = wp.format_weekly_results(res)
    trainer = [l for l in out.splitlines() if 'Trainer' in l][0]
    mixi = [l for l in out.splitlines() if 'Mixi' in l][0]
    easy = [l for l in out.splitlines() if 'Easy' in l][0]
    check('reines Training ohne Zusatz', 'einfach' not in trainer)
    check('gemischt zeigt einfache Anzahl', '2× einfach' in mixi)
    check('nur einfach zeigt Anzahl', '3× einfach' in easy)

    # Abwaertskompatibel: alte RookHub-Instanz schickt die Felder nicht → nichts Zusaetzliches.
    legacy = {
        'total': 5, 'completedCount': 1,
        'players': [
            {'name': 'Alt', 'discordId': 'd9', 'solvedCount': 5, 'playedCount': 5,
             'totalSeconds': 90, 'completed': True, 'hintsUsed': 1},
        ],
    }
    out_legacy = wp.format_weekly_results(legacy)
    check('ohne Modus-Felder kein Zusatz', 'einfach' not in out_legacy)
    check('ohne Modus-Felder Rest unveraendert', '<@d9> — 5/5 · 1:30 (💡)' in out_legacy)

    # Robust gegen Muell-Werte (None/Strings) aus der Payload.
    junk = {'total': 2, 'completedCount': 0,
            'players': [{'name': 'Junk', 'solvedCount': 1, 'totalSeconds': 10,
                         'trainingCount': None, 'easyCount': 'zwei'}]}
    check('Muell-Werte kippen das Format nicht', 'einfach' not in wp.format_weekly_results(junk))
    print()


class _FlakyThread:
    """Thread, dessen send scheitert, solange ``fail`` gesetzt ist (z. B. Discord 400/5xx)."""
    _counter = 0

    def __init__(self, name, box):
        _FlakyThread._counter += 1
        self.id = 700000 + _FlakyThread._counter
        self.name = name
        self.sent = []
        self._box = box

    async def send(self, content=None, **kwargs):
        if self._box['fail']:
            raise RuntimeError('400 Bad Request (Invalid Form Body)')
        from test_helpers import FakeMessage
        msg = FakeMessage(content=content, **kwargs)
        self.sent.append(msg)
        return msg


class _ThreadChannel(FakeChannel):
    """Channel mit Thread-Cache wie discord.TextChannel.get_thread."""

    def __init__(self, box, channel_id=88888):
        super().__init__(channel_id=channel_id)
        self._box = box
        self.deleted = set()

    async def create_thread(self, name='thread', **kwargs):
        thread = _FlakyThread(name, self._box)
        self.threads.append(thread)
        return thread

    def get_thread(self, thread_id):
        return next((t for t in self.threads if t.id == thread_id and t.id not in self.deleted), None)


def test_weekly_announcement_retry_reuses_thread():
    """N10-001: scheitert der Versand nach create_thread, legt der naechste Lauf keinen weiteren
    Thread an, sondern nutzt den vorgemerkten; nach _MAX_ATTEMPTS Fehlversuchen wird aufgegeben."""
    print('[weekly announcement retry reuses thread]')
    tmpdir = setup_temp_config()
    box = {'fail': True}
    ch = _ThreadChannel(box)

    async def _fetch_channel(cid):
        raise RuntimeError('404 Unknown Channel')

    fake_bot = MagicMock()
    fake_bot.get_channel = lambda cid: ch if cid == 88888 else None
    fake_bot.fetch_channel = _fetch_channel
    old_bot, old_cid = wp._bot, wp._channel_id
    orig_get, orig_results = wp.rookhub.get_weekly_posts, wp.rookhub.get_weekly_results
    wp._bot, wp._channel_id = fake_bot, 88888
    try:
        from test_helpers import atomic_write
        now = datetime.now(timezone.utc)
        atomic_write(wp.WEEKLY_STATE_FILE, {'posted_ids': [], 'seeded': True, 'threads': {}})  # Altbestand ohne pending
        post = {'id': 11, 'title': 'Woche 11', 'scheduledAt': _iso(now - timedelta(minutes=5))}
        wp.rookhub.get_weekly_posts = lambda timeout=15: [post]
        wp.rookhub.get_weekly_results = lambda wid, timeout=15: None

        run_async(wp.run_weekly_announcements())
        run_async(wp.run_weekly_announcements())
        check('2 gescheiterte Laeufe → nur 1 Thread', len(ch.threads) == 1)
        check('Fehlversuche gezaehlt', wp._pending(11).get('failures') == 2)
        check('Thread vorgemerkt', wp._pending(11).get('thread_id') == ch.threads[0].id)
        check('noch nicht als gepostet markiert', 11 not in wp._posted_ids())

        box['fail'] = False
        run_async(wp.run_weekly_announcements())
        check('Erfolg im vorgemerkten Thread, kein neuer', len(ch.threads) == 1 and len(ch.threads[0].sent) == 1)
        check('danach gepostet', 11 in wp._posted_ids())
        check('Zwischenstand aufgeraeumt', wp._pending(11) == {})
        check('Embed-Message fuer Updates gemerkt', (wp._thread_for(11) or {}).get('channel_id') == ch.threads[0].id)

        # Vorgemerkter Thread inzwischen geloescht (nicht im Cache, fetch 404) → neuer Thread.
        box['fail'] = True
        post2 = {'id': 12, 'title': 'Woche 12', 'scheduledAt': _iso(now - timedelta(minutes=4))}
        wp.rookhub.get_weekly_posts = lambda timeout=15: [post, post2]
        run_async(wp.run_weekly_announcements())
        ch.deleted.add(ch.threads[-1].id)
        box['fail'] = False
        run_async(wp.run_weekly_announcements())
        check('geloeschter Thread → genau ein neuer', len(ch.threads) == 3 and len(ch.threads[-1].sent) == 1)

        # Dauerfehler: nach _MAX_ATTEMPTS aufgeben (als gepostet markieren, nicht weiter versuchen).
        box['fail'] = True
        post3 = {'id': 13, 'title': 'Woche 13', 'scheduledAt': _iso(now - timedelta(minutes=3))}
        wp.rookhub.get_weekly_posts = lambda timeout=15: [post3]
        for _ in range(wp._MAX_ATTEMPTS):
            run_async(wp.run_weekly_announcements())
        check('nach _MAX_ATTEMPTS aufgegeben', 13 in wp._posted_ids() and wp._pending(13) == {})
        n_threads = len(ch.threads)
        run_async(wp.run_weekly_announcements())
        check('nach dem Aufgeben kein weiterer Versuch', len(ch.threads) == n_threads)
        check('ueber alle Fehlversuche nur 1 Thread fuer #13', sum(1 for t in ch.threads if 'Woche 13' in t.name) == 1)
    finally:
        wp.rookhub.get_weekly_posts, wp.rookhub.get_weekly_results = orig_get, orig_results
        wp._bot, wp._channel_id = old_bot, old_cid
        teardown_temp_config(tmpdir)
    print()


def test_weekly_discord_limits():
    """N10-001: Embed-Titel <= 256 (RookHub erlaubt 300), Fortschrittsfeld <= 1024 Zeichen."""
    print('[weekly discord limits]')
    tmpdir = setup_temp_config()
    orig_results = wp.rookhub.get_weekly_results
    try:
        wp.rookhub.get_weekly_results = lambda wid, timeout=15: None
        ch = FakeChannel(channel_id=88888)
        long_title = 'Kapitel ' + 'sehr langer Titel ' * 16   # ~300 Zeichen
        run_async(wp._post_announcement(ch, {'id': 21, 'title': long_title,
                                             'scheduledAt': '2026-06-19T18:00:00'}))
        embed = ch.threads[0].sent[0].kwargs.get('embed')
        check('Testtitel > 256', len(long_title) > 256)
        check('Titel > 256 gekuerzt', len(embed.title) <= 256 and embed.title.endswith('…'))
        ch2 = FakeChannel(channel_id=88888)
        run_async(wp._post_announcement(ch2, {'id': 22, 'title': 'Kurz', 'scheduledAt': '2026-06-19T18:00:00'}))
        check('kurzer Titel unveraendert', ch2.threads[0].sent[0].kwargs.get('embed').title == 'Kurz')

        players = [{'name': f'{i:02d}' + 'x' * 48, 'solvedCount': 15, 'totalSeconds': 36000,
                    'completed': True, 'hintsUsed': 1, 'easyCount': 99} for i in range(20)]
        out = wp.format_weekly_results({'total': 15, 'completedCount': 20, 'players': players})
        shown = [l for l in out.splitlines() if l.startswith('✅')]
        more = next((l for l in out.splitlines() if l.startswith('+')), '')
        check('Feldwert <= 1024', len(out) <= 1024)
        check('Fusszeile bleibt', out.endswith('\n_(20 erledigt)_'))
        check('+N weitere zaehlt die weggefallenen mit', more == f'+{20 - len(shown)} weitere' and len(shown) < 15)
    finally:
        wp.rookhub.get_weekly_results = orig_results
        teardown_temp_config(tmpdir)
    print()
