"""Standalone-Tests für den Build-Info-Endpoint des Webhook-Servers (core/webhook_server.py).

Ausführen: python tests/test_webhook_build_info.py
Prüft zweierlei:
1. GET /webhook/build-info ist NICHT mehr unauthentifiziert abrufbar — der Webhook-Port ist
   host-published, die Commit-SHA soll nicht öffentlich lesbar sein. Festes Header-Schema
   (identisch auf der rookhub-Abrufseite): ``X-Bot-Timestamp`` (Unix-Sekunden) +
   ``X-Bot-Signature`` = ``"sha256=" + HMAC_SHA256(ROOKHUB_STATS_SECRET, "<ts>")`` hex,
   Toleranz ±300 s; fehlend/falsch/abgelaufen → 401.
2. Mit gültigen Headern spiegelt die Antwort GIT_SHA/GIT_REF-ENV des laufenden Images —
   RookHubs Admin-CI-Seite markiert damit den GitHub-Actions-Run des laufenden Bot-Images.
"""

import asyncio
import hashlib
import hmac
import json
import os
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from core import webhook_server as ws

SECRET = 'stats-s3cret'

_failures = []


def check(name, cond):
    print(('  OK   ' if cond else '  FAIL ') + name)
    if not cond:
        _failures.append(name)


class _Req:
    """Minimaler Request-Ersatz — der Handler liest nur ``request.headers``."""

    def __init__(self, headers=None):
        self.headers = headers or {}


def _signed_headers(ts, secret=SECRET):
    """Baut das Header-Paar exakt nach dem Schema der rookhub-Gegenstelle."""
    sig = 'sha256=' + hmac.new(secret.encode('utf-8'), str(ts).encode('utf-8'),
                               hashlib.sha256).hexdigest()
    return {'X-Bot-Timestamp': str(ts), 'X-Bot-Signature': sig}


def _call(headers, secret=SECRET):
    handler = ws._make_build_info_handler(secret)
    return asyncio.run(handler(_Req(headers)))


def test_valid_auth_reflects_env():
    os.environ['GIT_SHA'] = 'abc123'
    os.environ['GIT_REF'] = 'master'
    try:
        resp = _call(_signed_headers(int(time.time())))
        check('gueltige Header → 200', resp.status == 200)
        data = json.loads(resp.body.decode('utf-8'))
        check('sha == env', data.get('sha') == 'abc123')
        check('ref == env', data.get('ref') == 'master')
    finally:
        os.environ.pop('GIT_SHA', None)
        os.environ.pop('GIT_REF', None)


def test_missing_env_empty():
    os.environ.pop('GIT_SHA', None)
    os.environ.pop('GIT_REF', None)
    resp = _call(_signed_headers(int(time.time())))
    data = json.loads(resp.body.decode('utf-8'))
    check('sha leer ohne env', data.get('sha') == '')
    check('ref leer ohne env', data.get('ref') == '')


def test_wrong_signature_401():
    ts = int(time.time())
    headers = _signed_headers(ts)
    # Mit fremdem Secret signiert → muss abgelehnt werden.
    headers['X-Bot-Signature'] = _signed_headers(ts, secret='anderes-secret')['X-Bot-Signature']
    check('falsche Signatur → 401', _call(headers).status == 401)
    # Kaputter Hex-Wert ebenso.
    headers['X-Bot-Signature'] = 'sha256=' + 'deadbeef' * 8
    check('kaputte Signatur → 401', _call(headers).status == 401)
    # Ohne das feste "sha256="-Praefix ebenso (Schema ist fix, keine Varianten).
    headers = _signed_headers(ts)
    headers['X-Bot-Signature'] = headers['X-Bot-Signature'][len('sha256='):]
    check('Signatur ohne sha256=-Praefix → 401', _call(headers).status == 401)


def test_stale_timestamp_401():
    # Gueltig signiert, aber ausserhalb ±300 s → Replay wird abgelehnt.
    check('Timestamp zu alt (>300s) → 401',
          _call(_signed_headers(int(time.time()) - 400)).status == 401)
    check('Timestamp zu weit in der Zukunft → 401',
          _call(_signed_headers(int(time.time()) + 400)).status == 401)
    # Knapp im Fenster → ok (Uhr-Drift zwischen Containern toleriert).
    check('Timestamp knapp im Fenster → 200',
          _call(_signed_headers(int(time.time()) - 200)).status == 200)


def test_missing_headers_401():
    ts = int(time.time())
    check('ohne Header → 401', _call({}).status == 401)
    check('nur Timestamp → 401',
          _call({'X-Bot-Timestamp': str(ts)}).status == 401)
    check('nur Signatur → 401',
          _call({'X-Bot-Signature': _signed_headers(ts)['X-Bot-Signature']}).status == 401)
    headers = _signed_headers(ts)
    headers['X-Bot-Timestamp'] = 'gestern'
    check('unparsbarer Timestamp → 401', _call(headers).status == 401)


def test_empty_secret_disables():
    # Leeres Secret (ENV nicht gesetzt) darf den Endpoint NICHT oeffnen — auch nicht fuer
    # eine mit leerem Key gebildete "gueltige" Signatur.
    ts = int(time.time())
    check('leeres Secret → 401 trotz passender Sig',
          _call(_signed_headers(ts, secret=''), secret='').status == 401)


def main():
    for t in (test_valid_auth_reflects_env, test_missing_env_empty, test_wrong_signature_401,
              test_stale_timestamp_401, test_missing_headers_401, test_empty_secret_disables):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle Build-Info-Webhook-Tests bestanden.')


if __name__ == '__main__':
    main()
