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
        check('Thread-Name = Titel', ch.threads[0].name == 'Neu faellig')

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
