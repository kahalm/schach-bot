"""Standalone-Tests für den Build-Info-Endpoint des Webhook-Servers (core/webhook_server.py).

Ausführen: python tests/test_webhook_build_info.py
Prüft, dass GET /webhook/build-info die GIT_SHA/GIT_REF-ENV des laufenden Images spiegelt —
RookHubs Admin-CI-Seite markiert damit den GitHub-Actions-Run des laufenden Bot-Images.
"""

import asyncio
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from core import webhook_server as ws

_failures = []


def check(name, cond):
    print(('  OK   ' if cond else '  FAIL ') + name)
    if not cond:
        _failures.append(name)


def _call():
    resp = asyncio.run(ws._build_info_handler(None))
    return json.loads(resp.body.decode('utf-8'))


def test_reflects_env():
    os.environ['GIT_SHA'] = 'abc123'
    os.environ['GIT_REF'] = 'master'
    try:
        data = _call()
        check('sha == env', data.get('sha') == 'abc123')
        check('ref == env', data.get('ref') == 'master')
    finally:
        os.environ.pop('GIT_SHA', None)
        os.environ.pop('GIT_REF', None)


def test_missing_env_empty():
    os.environ.pop('GIT_SHA', None)
    os.environ.pop('GIT_REF', None)
    data = _call()
    check('sha leer ohne env', data.get('sha') == '')
    check('ref leer ohne env', data.get('ref') == '')


def main():
    for t in (test_reflects_env, test_missing_env_empty):
        print(f'== {t.__name__} ==')
        t()
    print()
    if _failures:
        print(f'FAILED: {len(_failures)} Checks')
        sys.exit(1)
    print('Alle Build-Info-Webhook-Tests bestanden.')


if __name__ == '__main__':
    main()
