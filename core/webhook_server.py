"""HTTP-Webhook-Empfaenger fuer RookHub-Events (z. B. Daily-Puzzle-Solve).

RookHub feuert ``POST /webhook/puzzle-attempt`` mit HMAC-signiertem Body. Der
Server laeuft als aiohttp-Site neben dem discord.py-Bot-Loop (gleiches Event-
Loop, kein eigener Thread). Wenn das Puzzle in der Nachricht dem gemerkten
Daily-Post entspricht, wird der Embed aktualisiert.

Konfig via Env:
- ``WEBHOOK_PORT`` (default 9000) — interne Bind-Port im Compose-Netz.
- ``WEBHOOK_BIND_HOST`` (default 0.0.0.0).
- ``WEBHOOK_SECRET`` — Shared-Secret mit RookHub. Leer = Webhook deaktiviert.

Schnittstelle:
- :func:`start(bot, host, port, secret)` startet den Server, gibt das ``AppRunner``-
  Objekt zurueck (oder ``None`` wenn deaktiviert).
- :func:`stop(runner)` schliesst sauber.

Sicherheit:
- HMAC-SHA256 ueber den rohen Request-Body, signed mit ``WEBHOOK_SECRET``.
- Header ``X-Webhook-Signature: sha256=<hex>``.
- ``hmac.compare_digest`` gegen Timing-Angriffe.
- 401 bei fehlender/falscher Signatur, 400 bei kaputtem JSON, 200 sonst (auch
  wenn der Daily-Post nicht zur gelieferten puzzleId passt — vermeidet
  Retry-Loops auf RookHub-Seite, dort steht das schliesslich nur als „Info").
"""

import hashlib
import hmac
import json
import logging
from typing import Any

from aiohttp import web

log = logging.getLogger('schach-bot')


def _verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Prueft den ``X-Webhook-Signature``-Header gegen HMAC-SHA256 ueber body."""
    if not signature_header:
        return False
    if signature_header.startswith('sha256='):
        signature_header = signature_header[len('sha256='):]
    expected = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected, signature_header)
    except Exception:
        return False


def _make_handler(bot, secret: str):
    """Baut den aiohttp-Handler, der den Bot per Closure mitnimmt."""
    from puzzle import daily_results

    async def handle(request: web.Request) -> web.Response:
        raw = await request.read()
        sig = request.headers.get('X-Webhook-Signature')
        if not _verify_signature(secret, raw, sig):
            log.warning('Webhook: HMAC-Signatur ungueltig (sig=%r len=%d)', sig, len(raw))
            return web.Response(status=401, text='invalid signature')

        try:
            payload: dict[str, Any] = json.loads(raw.decode('utf-8'))
        except Exception as e:
            log.warning('Webhook: kaputter JSON-Body: %s', e)
            return web.Response(status=400, text='invalid json')

        puzzle_id = payload.get('puzzleId')
        if not isinstance(puzzle_id, int):
            return web.Response(status=400, text='missing puzzleId')

        cur = daily_results.current()
        if not cur:
            log.debug('Webhook fuer puzzle %s erhalten, aber kein aktueller Daily-Post.', puzzle_id)
            return web.Response(status=200, text='no current daily')
        if cur.get('puzzle_id') != puzzle_id:
            log.debug('Webhook fuer puzzle %s passt nicht zum aktuellen Daily (%s).',
                      puzzle_id, cur.get('puzzle_id'))
            return web.Response(status=200, text='not current daily')

        # RookHub liefert ein Sub-Objekt ``results`` mit den Solver-Daten,
        # akzeptiert aber auch eine flache Form (alle Keys auf Top-Level) —
        # so kann RookHub den Payload-Schaden des aufrufenden Codes minimal halten.
        results = payload.get('results') if isinstance(payload.get('results'), dict) else payload
        await daily_results.apply_solver_update(bot, cur, results)
        return web.Response(status=200, text='ok')

    return handle


async def start(bot, host: str, port: int, secret: str) -> web.AppRunner | None:
    """Startet den aiohttp-Webhook-Server. Gibt den ``AppRunner`` zurueck (zum spaeteren Stop).

    Wird ``secret`` leer uebergeben, ist der Webhook deaktiviert → ``None``-Return.
    """
    if not secret:
        log.info('Webhook-Server deaktiviert (WEBHOOK_SECRET nicht gesetzt).')
        return None

    app = web.Application()
    app.router.add_post('/webhook/puzzle-attempt', _make_handler(bot, secret))
    # Health-Endpoint fuer Compose-Healthcheck.
    app.router.add_get('/webhook/health', lambda r: web.Response(status=200, text='ok'))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info('Webhook-Server gestartet auf %s:%d', host, port)
    return runner


async def stop(runner: web.AppRunner | None) -> None:
    """Beendet den Webhook-Server sauber. ``None`` ist no-op."""
    if runner is None:
        return
    try:
        await runner.cleanup()
        log.info('Webhook-Server gestoppt.')
    except Exception as e:
        log.warning('Webhook-Server Cleanup fehlgeschlagen: %s', e)
