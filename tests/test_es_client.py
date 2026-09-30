"""Standalone-Tests fuer core/es_client.py: Stopp mit Flush, Verlust-Zaehler, Warn-Drossel.

Review W4s N10-004: der Sender war ein Daemon-Thread mit ``while True`` ohne Stopp und Flush,
ignorierte den HTTP-Status und verwarf bei voller Warteschlange still.

Ausfuehren: python tests/test_es_client.py   (laeuft auch in tests/run_all.py)
"""

import logging
import os
import queue
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import es_client  # noqa: E402

_failures = []


def check(name, cond, detail=''):
    print(('  OK   ' if cond else '  FAIL ') + name + (f'  [{detail}]' if detail and not cond else ''))
    if not cond:
        _failures.append(name)


class _Resp:
    def __init__(self, status):
        self.status_code = status


class _Session:
    """Antwortet der Reihe nach mit den Statuscodes; eine Ausnahme-Instanz wird geworfen."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.posted = []

    def post(self, url, data=None, timeout=None):
        self.posted.append(url)
        a = self.answers.pop(0) if self.answers else 201
        if isinstance(a, Exception):
            raise a
        return _Resp(a)


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


def _reset(session):
    """Frischer Modulzustand fuer einen Lauf (ohne echten Netzverkehr)."""
    es_client._ES_URL = 'http://es.invalid:9200'
    es_client._queue = queue.Queue(maxsize=2000)
    es_client._stop = threading.Event()
    es_client._worker_started = False
    es_client._worker_thread = None
    es_client._last_warn = None
    es_client._last_status = None
    for k in es_client._stats:
        es_client._stats[k] = 0
    es_client._new_session = lambda: session


def _with_capture(fn):
    cap = _Capture()
    lg = logging.getLogger('schach-bot')
    lg.addHandler(cap)
    old_level = lg.level
    lg.setLevel(logging.DEBUG)
    try:
        fn(cap)
    finally:
        lg.removeHandler(cap)
        lg.setLevel(old_level)
    return cap


def test_rejected_and_failed_counted():
    print('== test_rejected_and_failed_counted ==')
    session = _Session([201, 400, 503, ConnectionError('ES weg'), 201])
    _reset(session)

    def run(cap):
        for i in range(5):
            es_client.send_log('Information', f'm{i}', {'foo': 'bar'})
        es_client._queue.join()               # Worker hat alles abgearbeitet
        es_client.shutdown()
        check('Worker beendet sich nach shutdown()', not es_client._worker_thread.is_alive())
        check('alle 5 Dokumente gesendet', len(session.posted) == 5, str(len(session.posted)))
        warn = [m for m in cap.records if 'ES-Versand' in m]
        # Erster Verlust sofort, der Rest gedrosselt – beim Beenden einmal nachgemeldet.
        check('zwei Warnungen (sofort + beim Beenden)', len(warn) == 2, str(cap.records))
        if len(warn) == 2:
            check('erste: 1 abgelehnt, HTTP 400', '1 Dokument(e) von ES abgelehnt (zuletzt HTTP 400)' in warn[0],
                  warn[0])
            check('zweite: 1 abgelehnt (HTTP 503) + 1 nicht gesendet',
                  '1 Dokument(e) von ES abgelehnt (zuletzt HTTP 503)' in warn[1]
                  and '1 nicht gesendet' in warn[1], warn[1])
        check('Zaehler nach der Warnung zurueck', not any(es_client._stats.values()))

    _with_capture(run)


def test_shutdown_flushes_queue():
    print('== test_shutdown_flushes_queue ==')
    session = _Session([])
    _reset(session)
    es_client._worker_started = True          # Dokumente liegen schon, bevor der Worker laeuft
    for i in range(4):
        es_client.send_log('Information', f'm{i}')

    def run(cap):
        es_client._stop.set()                 # Stopp gesetzt → Worker sendet nur noch nach
        es_client._worker()
        check('wartende Dokumente beim Beenden nachgesendet', len(session.posted) == 4,
              str(len(session.posted)))
        check('ohne Verluste keine Warnung', cap.records == [], str(cap.records))

    _with_capture(run)


def test_queue_full_counted():
    print('== test_queue_full_counted ==')
    _reset(_Session([]))
    es_client._worker_started = True          # kein Worker: die Warteschlange laeuft voll
    es_client._queue = queue.Queue(maxsize=2)
    for i in range(5):
        es_client.send_log('Information', f'm{i}')
    es_client.send_event('stat_inc', {'n': 1})
    check('Ueberlauf gezaehlt statt still verworfen', es_client._stats['dropped'] == 4,
          str(es_client._stats))


def test_warning_throttled_hourly():
    print('== test_warning_throttled_hourly ==')
    _reset(_Session([]))

    def run(cap):
        es_client._count('rejected', 400)
        es_client._maybe_warn()
        es_client._count('rejected', 400)
        es_client._maybe_warn()
        es_client._maybe_warn()
        check('innerhalb einer Stunde nur eine Warnung', len(cap.records) == 1, str(cap.records))
        es_client._last_warn -= es_client._WARN_INTERVAL + 1
        es_client._maybe_warn()
        check('nach einer Stunde die naechste (mit dem Rest)', len(cap.records) == 2
              and '1 Dokument(e) von ES abgelehnt' in cap.records[-1], str(cap.records))
        es_client._maybe_warn()
        check('ohne Verluste keine Warnung', len(cap.records) == 2)

    _with_capture(run)


def test_shutdown_drops_rest_after_deadline():
    print('== test_shutdown_drops_rest_after_deadline ==')
    session = _Session([])
    _reset(session)
    es_client._worker_started = True      # Dokumente liegen schon, bevor der Worker startet
    for i in range(3):
        es_client.send_log('Information', f'm{i}')
    old_flush = es_client._FLUSH_SECONDS
    es_client._FLUSH_SECONDS = 0          # keine Zeit zum Nachsenden → alles als verworfen
    try:
        def run(cap):
            es_client._stop.set()
            es_client._worker()
            check('nichts mehr gesendet', session.posted == [])
            check('Rest als verworfen gemeldet', any('3 verworfen' in m for m in cap.records), str(cap.records))
        _with_capture(run)
    finally:
        es_client._FLUSH_SECONDS = old_flush


def test_shutdown_without_worker_is_noop():
    print('== test_shutdown_without_worker_is_noop ==')
    _reset(_Session([]))
    es_client._ES_URL = None
    es_client.send_log('Information', 'm')
    es_client.shutdown()
    check('ES aus: kein Worker, shutdown ohne Fehler', es_client._worker_thread is None)


def main():
    for t in (test_rejected_and_failed_counted, test_shutdown_flushes_queue, test_queue_full_counted, test_warning_throttled_hourly,
              test_shutdown_drops_rest_after_deadline, test_shutdown_without_worker_is_noop):
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle es_client-Tests bestanden.')


if __name__ == '__main__':
    main()
