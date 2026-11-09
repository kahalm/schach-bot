"""Logging-Setup: Rolling File-Log + Stream-Filter für python-chess Warnungen."""

import logging
import re
import sys
from logging.handlers import RotatingFileHandler

from core import es_client


_LEVEL_MAP = {
    logging.DEBUG: 'Debug',
    logging.INFO: 'Information',
    logging.WARNING: 'Warning',
    logging.ERROR: 'Error',
    logging.CRITICAL: 'Fatal',
}


_TEMPLATE_MAX = 300
# Zahlenfolgen (Discord-/Puzzle-Ids, Zaehler, Zeiten) — in einem schon formatierten Text der
# einzige verlaessliche Wechselteil; ohne Normalisierung waere jede Zeile eine eigene „Fehlerart“.
_NUMBER_RE = re.compile(r'\d+')


def message_template(record: logging.LogRecord) -> str:
    """Gruppierschluessel fuer den log-watcher (``labels.MessageTemplate``, S2-012).

    Mit ``record.args`` (``log.warning('X %s', y)``) ist ``record.msg`` das unformatierte
    Template — ohne eingesetzte Werte, also auch PII-arm. Ohne args (f-String oder fester Text)
    ist ``record.msg`` schon der fertige Text: dann Zahlenfolgen durch ``{n}`` ersetzen, damit
    gleiche Meldungen mit anderen Ids zusammenfallen. Laenge gedeckelt."""
    raw = str(record.msg)
    tpl = raw if record.args else _NUMBER_RE.sub('{n}', raw)
    return tpl[:_TEMPLATE_MAX]


class _ESHandler(logging.Handler):
    """Sendet Log-Records fire-and-forget an Elasticsearch."""

    def emit(self, record: logging.LogRecord):
        try:
            level = _LEVEL_MAP.get(record.levelno, 'Information')
            msg = self.format(record)
            extra = {'logger': record.name, 'MessageTemplate': message_template(record)}
            if record.exc_info:
                import traceback
                extra['exception'] = ''.join(traceback.format_exception(*record.exc_info))
            if hasattr(record, 'es_fields') and isinstance(record.es_fields, dict):
                extra.update(record.es_fields)
            es_client.send_log(level, msg, extra)
        except Exception:
            pass


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

    if es_client.enabled():
        es_handler = _ESHandler()
        es_handler.setLevel(logging.INFO)
        # Nur die reine Message ohne Zeitstempel (ES bekommt @timestamp separat)
        es_handler.setFormatter(logging.Formatter('%(message)s'))
        log.addHandler(es_handler)

    log.propagate = False
    return log
