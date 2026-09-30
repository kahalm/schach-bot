"""Elasticsearch-Client (fire-and-forget, non-blocking).

Konfiguration via Umgebungsvariablen:
  ES_URL          http://host:9200  (leer = ES deaktiviert)
  ES_INDEX_PREFIX schach-bot-logs   (Default)

Netzwerkfehler erreichen den Bot nie – ES-Ausfall darf ihn nicht beeinträchtigen. Verlorene
Dokumente (ES-Antwort >= 300, Fehler/Timeout, volle Warteschlange) werden aber gezählt und
höchstens einmal je Stunde als Warnung ins Log geschrieben (Datei-Log, nicht still).
Beim Beenden sendet :func:`shutdown` die Warteschlange kurz nach.
"""

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger('schach-bot')

_ES_URL: str | None = os.environ.get('ES_URL', '').strip() or None
_INDEX_PREFIX: str = os.environ.get('ES_INDEX_PREFIX', 'schach-bot-logs')

# Hintergrund-Queue damit kein HTTP-Call den Event-Loop blockiert
_queue: queue.Queue = queue.Queue(maxsize=2000)
_worker_started = False
_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_stop = threading.Event()

_POST_TIMEOUT = 3          # Sekunden je Dokument
_FLUSH_SECONDS = 2.0       # beim Beenden hoechstens so lange nachsenden
_WARN_INTERVAL = 3600.0    # Verlust-Warnung hoechstens einmal je Stunde

# Verlorene Dokumente seit der letzten Warnung (Zugriff aus Worker UND Aufrufer-Threads).
_stats_lock = threading.Lock()
_stats = {'rejected': 0, 'failed': 0, 'dropped': 0}
_last_status: int | None = None
_last_warn: float | None = None


def _count(key: str, status: int | None = None) -> None:
    global _last_status
    with _stats_lock:
        _stats[key] += 1
        if status is not None:
            _last_status = status


def _new_session():
    import requests
    session = requests.Session()
    session.headers['Content-Type'] = 'application/json'
    return session


def _post(session, url, doc) -> None:
    """Ein Dokument senden; Fehler nie nach oben, aber zaehlen."""
    try:
        resp = session.post(url, data=json.dumps(doc, ensure_ascii=False, default=str),
                            timeout=_POST_TIMEOUT)
    except Exception:
        _count('failed')
        return
    status = getattr(resp, 'status_code', None)
    if isinstance(status, int) and status >= 300:
        _count('rejected', status)   # z. B. fehlende Pipeline, Mapping-Konflikt unter labels.*


def _maybe_warn(force: bool = False) -> None:
    """Hoechstens einmal je Stunde (``force``: beim Beenden) verlorene Dokumente melden."""
    global _last_status, _last_warn
    now = time.monotonic()
    with _stats_lock:
        if not any(_stats.values()):
            return
        if not force and _last_warn is not None and now - _last_warn < _WARN_INTERVAL:
            return
        snap, status = dict(_stats), _last_status
        for key in _stats:
            _stats[key] = 0
        _last_status, _last_warn = None, now
    log.warning('ES-Versand: %d Dokument(e) von ES abgelehnt (zuletzt HTTP %s), %d nicht gesendet '
                '(Fehler/Timeout), %d verworfen (Warteschlange voll bzw. beim Beenden).',
                snap['rejected'], status or '-', snap['failed'], snap['dropped'])


def _worker():
    session = _new_session()
    while not _stop.is_set():
        try:
            url, doc = _queue.get(timeout=1)
        except queue.Empty:
            _maybe_warn()
            continue
        try:
            _post(session, url, doc)
        finally:
            _queue.task_done()
        _maybe_warn()
    # Beenden: kurz nachsenden, den Rest als verworfen zaehlen und einmal melden.
    deadline = time.monotonic() + _FLUSH_SECONDS
    while True:
        try:
            url, doc = _queue.get_nowait()
        except queue.Empty:
            break
        try:
            if time.monotonic() < deadline:
                _post(session, url, doc)
            else:
                _count('dropped')
        finally:
            _queue.task_done()
    _maybe_warn(force=True)


def _ensure_worker():
    global _worker_started, _worker_thread
    if _worker_started:
        return
    with _worker_lock:
        if not _worker_started:
            t = threading.Thread(target=_worker, daemon=True, name='es-sender')
            t.start()
            _worker_thread = t
            _worker_started = True


def shutdown() -> None:
    """Beim Beenden des Bots: Worker stoppen, Warteschlange hoechstens ``_FLUSH_SECONDS``
    nachsenden, Verluste einmal ins Log. Ohne laufenden Worker (ES aus) ein No-op."""
    _stop.set()
    t = _worker_thread
    if t is not None and t.is_alive():
        t.join(_FLUSH_SECONDS + _POST_TIMEOUT + 2)


def enabled() -> bool:
    return _ES_URL is not None


def _index_name(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y.%m')}"


def _normalize_tags(raw) -> list[str]:
    """Normalisiert einen tags-Wert auf eine deduplizierte Liste nicht-leerer Strings.

    Akzeptiert einen einzelnen String (→ 1-Element-Liste) oder eine Liste/Tuple.
    Leere/whitespace-only Eintraege fallen raus; Reihenfolge bleibt erhalten.
    """
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, (list, tuple, set)):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for t in raw:
        s = str(t).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def send_log(level: str, message: str, extra: dict | None = None):
    """Log-Eintrag im kanonischen ECS-Schema nach ES senden (fire-and-forget).

    Felder gemaess log-watcher/schema/logging-schema.md (log.level, message,
    service.name, log.logger, labels.*). Das Dokument laeuft zusaetzlich durch die
    zentrale Ingest-Pipeline logs-schema-normalize (Pflichtfelder/Defaults).
    """
    if not _ES_URL:
        return
    _ensure_worker()
    extra = dict(extra or {})
    logger = extra.pop('logger', None)
    exception = extra.pop('exception', None)
    tags = _normalize_tags(extra.pop('tags', None))
    log_obj = {'level': level}
    if logger:
        log_obj['logger'] = logger
    doc = {
        '@timestamp': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        'log': log_obj,
        'message': message,
        'service': {'name': 'schach-bot'},
    }
    if tags:
        doc['tags'] = tags  # native ECS keyword[]-Feld (siehe logging-schema.md)
    if exception:
        doc['error'] = {'stack_trace': exception}
    if extra:
        doc['labels'] = extra
    try:
        url = f"{_ES_URL}/{_index_name(_INDEX_PREFIX)}/_doc?pipeline=logs-schema-normalize"
        _queue.put_nowait((url, doc))
    except queue.Full:
        _count('dropped')


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
        _count('dropped')
