"""Logging-Setup: Rolling File-Log + Stream-Filter für python-chess Warnungen."""

import logging
import sys
from logging.handlers import RotatingFileHandler


class _SuppressEmptyFen:
    """python-chess schreibt Parsing-Warnungen direkt auf stdout/stderr –
    nicht über das logging-Modul. Beide Streams filtern."""
    _SUPPRESS = ('empty fen while parsing', 'illegal san:', 'invalid san:',
                 'no matching legal move', 'ambiguous san:')

    def __init__(self, stream):
        self._s = stream

    def write(self, s):
        if not any(p in s for p in self._SUPPRESS):
            try:
                return self._s.write(s)
            except (UnicodeEncodeError, UnicodeDecodeError):
                return self._s.write(s.encode('ascii', 'replace').decode('ascii'))
        return len(s)

    def flush(self):
        self._s.flush()

    def __getattr__(self, n):
        return getattr(self._s, n)


_setup_done = False


def setup() -> logging.Logger:
    """Initialisiert globales Logging und gibt den 'schach-bot'-Logger zurück.

    Wird einmal aus bot.py beim Start aufgerufen."""
    global _setup_done
    log = logging.getLogger('schach-bot')
    if _setup_done:
        return log
    _setup_done = True

    sys.stdout = _SuppressEmptyFen(sys.stdout)
    sys.stderr = _SuppressEmptyFen(sys.stderr)

    fmt = logging.Formatter('%(asctime)s [%(levelname)-8s] %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')

    file_handler = RotatingFileHandler(
        'bot.log', maxBytes=1_000_000, backupCount=5, encoding='utf-8')
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)

    term_handler = logging.StreamHandler(sys.stderr)
    term_handler.setFormatter(fmt)
    term_handler.setLevel(logging.ERROR)

    log.setLevel(logging.DEBUG)
    log.addHandler(file_handler)
    log.addHandler(term_handler)
    log.propagate = False
    return log
