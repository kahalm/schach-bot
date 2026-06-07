"""Elasticsearch-Client (fire-and-forget, non-blocking).

Konfiguration via Umgebungsvariablen:
  ES_URL          http://host:9200  (leer = ES deaktiviert)
  ES_INDEX_PREFIX schach-bot-logs   (Default)

Alle Netzwerkfehler werden still geschluckt – ES-Ausfall darf den Bot
nicht beeinträchtigen.
"""

import json
import logging
import os
import queue
import threading
from datetime import datetime, timezone

log = logging.getLogger('schach-bot')

_ES_URL: str | None = os.environ.get('ES_URL', '').strip() or None
_INDEX_PREFIX: str = os.environ.get('ES_INDEX_PREFIX', 'schach-bot-logs')

# Hintergrund-Queue damit kein HTTP-Call den Event-Loop blockiert
_queue: queue.Queue = queue.Queue(maxsize=2000)
_worker_started = False
_worker_lock = threading.Lock()


def _worker():
    import requests
    session = requests.Session()
    session.headers['Content-Type'] = 'application/json'
    while True:
        try:
            url, doc = _queue.get(timeout=5)
            try:
                session.post(url, data=json.dumps(doc, ensure_ascii=False, default=str),
                             timeout=3)
            except Exception:
                pass  # ES-Fehler nie nach oben propagieren
            finally:
                _queue.task_done()
        except queue.Empty:
            continue


def _ensure_worker():
    global _worker_started
    if _worker_started:
        return
    with _worker_lock:
        if not _worker_started:
            t = threading.Thread(target=_worker, daemon=True, name='es-sender')
            t.start()
            _worker_started = True


def enabled() -> bool:
    return _ES_URL is not None


def _index_name(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y.%m')}"


def send_log(level: str, message: str, extra: dict | None = None):
    """Log-Eintrag nach ES senden (fire-and-forget)."""
    if not _ES_URL:
        return
    _ensure_worker()
    doc = {
        '@timestamp': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        'level': level,
        'message': message,
        'fields': {'Application': 'schach-bot', **(extra or {})},
    }
    try:
        url = f"{_ES_URL}/{_index_name(_INDEX_PREFIX)}/_doc"
        _queue.put_nowait((url, doc))
    except queue.Full:
        pass


def send_event(event_type: str, payload: dict):
    """Strukturiertes Event (Reaktion, Stat, …) in separaten Events-Index."""
    if not _ES_URL:
        return
    _ensure_worker()
    event_prefix = _INDEX_PREFIX.replace('-logs', '') + '-events'
    doc = {
        '@timestamp': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        'event_type': event_type,
        **payload,
    }
    try:
        url = f"{_ES_URL}/{_index_name(event_prefix)}/_doc"
        _queue.put_nowait((url, doc))
    except queue.Full:
        pass
