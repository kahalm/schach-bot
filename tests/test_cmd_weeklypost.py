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
    print()
