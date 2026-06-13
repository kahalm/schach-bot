"""Tests fuer die Tagespuzzle-Bestenlisten (commands/leaderboard.py + puzzle/daily_leaderboard.py)."""

from datetime import datetime, timezone

from test_helpers import (
    check, run_async, setup_temp_config, teardown_temp_config,
    make_interaction, _captured_commands, atomic_read, FakeChannel,
)
import commands.leaderboard as lb
from puzzle import daily_leaderboard as dlb


def _ladder(entries, period='2026-06'):
    return {'period': period, 'entries': entries}


def _sample_ladder():
    return _ladder([
        {'name': 'Anna', 'discordId': '111', 'points': 28, 'solved': 2, 'golds': 1},
        {'name': 'Ben', 'discordId': None, 'points': 15, 'solved': 1, 'golds': 1},
    ])


def _sample_hof():
    return {
        'mostSolved': [{'name': 'Anna', 'discordId': '111', 'value': 12}],
        'mostGolds': [{'name': 'Ben', 'discordId': None, 'value': 4}],
        'fastest': {'name': 'Anna', 'discordId': '111', 'timeSeconds': 9, 'date': '2026-06-02'},
    }


def test_leaderboard_format():
    """Reine Formatter aus puzzle/daily_leaderboard.py."""
    print('[leaderboard format]')

    check('period: 2026-06 → Juni 2026', dlb.format_period('2026-06') == 'Juni 2026')
    check('period: kaputt → Fallback', dlb.format_period('quatsch') == 'quatsch')

    empty = dlb.format_ladder(_ladder([]))
    check('leere Ladder → Hinweis', 'Noch keine Wertung' in empty)

    out = dlb.format_ladder(_sample_ladder())
    check('Ladder: 🥇 für Platz 1', '🥇' in out)
    check('Ladder: verknüpft → @mention', '<@111>' in out)
    check('Ladder: Name-Fallback (Ben)', 'Ben' in out)
    check('Ladder: Punkte', '**28** Pkt' in out)
    check('Ladder: gelöst + golds', '(2 gelöst · 1×🥇)' in out)

    # max_entries kappt + "weitere"
    many = _ladder([{'name': f'U{i}', 'points': 10, 'solved': 1, 'golds': 0} for i in range(12)])
    capped = dlb.format_ladder(many, max_entries=10)
    check('Ladder: Kappung → "weitere"', '…und 2 weitere' in capped)

    hof = _sample_hof()
    solved_line = dlb.format_hof_list(hof['mostSolved'], 'gelöst')
    check('HoF solved: Wert + Einheit', '12 gelöst' in solved_line and '<@111>' in solved_line)
    check('HoF leer → —', dlb.format_hof_list([], 'gelöst') == '—')

    fast = dlb.format_fastest(hof['fastest'])
    check('HoF fastest: Zeit (9s) + Datum', '9s' in fast and '2026-06-02' in fast)
    check('HoF fastest None → —', dlb.format_fastest(None) == '—')
    check('fmt_time m:ss', dlb._fmt_time(90) == '1:30')
    print()


def test_leaderboard_monthly_schedule():
    """should_post_monthly / previous_month: am 1. genau einmal den Vormonat."""
    print('[leaderboard schedule]')
    check('previous_month Jan → Vorjahr Dez',
          dlb.previous_month(datetime(2026, 1, 15, tzinfo=timezone.utc)) == (2025, 12))
    check('previous_month Juni → Mai',
          dlb.previous_month(datetime(2026, 6, 3, tzinfo=timezone.utc)) == (2026, 5))

    first = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    check('am 1. → Mai posten', dlb.should_post_monthly({}, first) == '2026-05')
    check('am 1. + schon gepostet → None',
          dlb.should_post_monthly({'last_posted': '2026-05'}, first) is None)
    check('nicht der 1. → None',
          dlb.should_post_monthly({}, datetime(2026, 6, 2, 8, 0, tzinfo=timezone.utc)) is None)
    print()


def test_leaderboard_command():
    """/bestenliste: holt Ladder + HoF und sendet ein Embed im Followup."""
    print('[/bestenliste]')
    tmpdir = setup_temp_config()
    orig_lb, orig_hof = lb.rookhub.get_daily_leaderboard, lb.rookhub.get_daily_hall_of_fame
    try:
        cmd = _captured_commands.get('bestenliste')
        check('cmd_bestenliste gefunden', cmd is not None)
        if not cmd:
            return

        captured = {}
        lb.rookhub.get_daily_leaderboard = lambda month=None: (captured.update(month=month) or _sample_ladder())
        lb.rookhub.get_daily_hall_of_fame = lambda: _sample_hof()

        ia = make_interaction()
        run_async(cmd(ia, monat='2026-06'))
        check('month durchgereicht', captured.get('month') == '2026-06')
        sends = [c for c in ia.followup.calls if c['type'] == 'send']
        check('Embed gesendet', len(sends) == 1 and sends[0].get('embed') is not None)
        embed = sends[0]['embed']
        joined = ' | '.join(f.get('value', '') for f in embed.fields)
        check('Embed: Ladder-Inhalt', '**28** Pkt' in joined)
        check('Embed: HoF-Inhalt', '12 gelöst' in joined)

        # API None → freundlicher Fehler (ephemeral), kein Embed
        lb.rookhub.get_daily_leaderboard = lambda month=None: None
        ia2 = make_interaction()
        run_async(cmd(ia2, monat='kaputt'))
        errs = [c for c in ia2.followup.calls if c['type'] == 'send']
        check('Fehlerfall: Hinweis statt Embed',
              len(errs) == 1 and errs[0].get('embed') is None and 'nicht laden' in (errs[0].get('content') or ''))
    finally:
        lb.rookhub.get_daily_leaderboard, lb.rookhub.get_daily_hall_of_fame = orig_lb, orig_hof
        teardown_temp_config(tmpdir)
    print()


def test_leaderboard_monthly_post():
    """run_monthly_post: postet den Vormonat in den Channel + dedupliziert; leerer Monat → kein Post."""
    print('[monthly auto-post]')
    tmpdir = setup_temp_config()
    orig_lb, orig_hof = lb.rookhub.get_daily_leaderboard, lb.rookhub.get_daily_hall_of_fame
    orig_should = dlb.should_post_monthly
    old_bot, old_cid = lb._bot, lb._channel_id

    ch = FakeChannel(channel_id=77777)
    fake_bot = type('B', (), {'get_channel': staticmethod(lambda cid: ch if cid == 77777 else None)})()
    lb._bot, lb._channel_id = fake_bot, 77777
    try:
        # should_post liefert Mai (so tun, als wäre der 1.)
        dlb.should_post_monthly = lambda state, now: ('2026-05' if not (state or {}).get('last_posted') == '2026-05' else None)
        lb.rookhub.get_daily_leaderboard = lambda month=None: _sample_ladder()
        lb.rookhub.get_daily_hall_of_fame = lambda: _sample_hof()

        run_async(lb.run_monthly_post())
        check('Auto-Post: 1 Nachricht im Channel', len(ch.sent) == 1)
        posted_embed = ch.sent[0].kwargs.get('embed') if ch.sent else None
        check('Auto-Post: Embed mit Endstand-Titel',
              posted_embed is not None and 'Endstand' in posted_embed.title)
        state = atomic_read(lb.STATE_FILE, default=dict)
        check('Auto-Post: Monat als gepostet gemerkt', state.get('last_posted') == '2026-05')

        # zweiter Lauf: dedupliziert (should_post → None)
        run_async(lb.run_monthly_post())
        check('Auto-Post: kein Doppelposten', len(ch.sent) == 1)

        # leerer Monat → kein Post, aber gemerkt
        ch.sent.clear()
        dlb.should_post_monthly = lambda state, now: '2026-04'
        lb.rookhub.get_daily_leaderboard = lambda month=None: _ladder([], period='2026-04')
        run_async(lb.run_monthly_post())
        check('leerer Monat: kein Post', len(ch.sent) == 0)
        check('leerer Monat: trotzdem gemerkt',
              atomic_read(lb.STATE_FILE, default=dict).get('last_posted') == '2026-04')
    finally:
        lb.rookhub.get_daily_leaderboard, lb.rookhub.get_daily_hall_of_fame = orig_lb, orig_hof
        dlb.should_post_monthly = orig_should
        lb._bot, lb._channel_id = old_bot, old_cid
        teardown_temp_config(tmpdir)
    print()
