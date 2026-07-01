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
import os
import time
from typing import Any

from aiohttp import web

log = logging.getLogger('schach-bot')

# Replay-/Timestamp-Schutz: wird ein ``X-Webhook-Timestamp``-Header mitgeschickt,
# fliesst er in die HMAC ein UND muss innerhalb dieses Fensters (Sekunden) liegen.
# Fehlt der Header (rookhub-Gegenstelle noch nicht nachgezogen), greift der alte
# Pfad (HMAC nur ueber den Body) — rueckwaertskompatibel, s. _verify_signature.
_TIMESTAMP_HEADER = 'X-Webhook-Timestamp'
_TIMESTAMP_TOLERANCE = 300  # ±5 min
# Maximale akzeptierte Body-Groesse fuer Webhook-POSTs (Schutz vor Speicher-DoS).
_MAX_BODY_SIZE = 256 * 1024  # 256 KiB


def _verify_signature(secret: str, body: bytes, signature_header: str | None,
                      timestamp_header: str | None = None, now: float | None = None) -> bool:
    """Prueft den ``X-Webhook-Signature``-Header gegen HMAC-SHA256.

    Replay-Schutz (opt-in, rueckwaertskompatibel): Wird ``timestamp_header``
    (Wert des ``X-Webhook-Timestamp``-Headers, Unix-Sekunden) mitgegeben, MUSS
    er innerhalb ±``_TIMESTAMP_TOLERANCE`` liegen und die HMAC wird ueber
    ``"<ts>.<body>"`` gebildet (so kann ein abgefangener Request nach Ablauf des
    Fensters nicht erneut eingespielt werden). Fehlt der Header, faellt die
    Verifikation auf den alten Pfad (HMAC nur ueber ``body``) zurueck — damit
    bricht nichts, solange die rookhub-Seite (``SchachBotWebhookService``) den
    Timestamp noch nicht mitschickt. **rookhub muss separat nachgezogen werden.**
    """
    if not signature_header:
        return False
    if signature_header.startswith('sha256='):
        signature_header = signature_header[len('sha256='):]

    if timestamp_header is not None and str(timestamp_header).strip() != '':
        # Timestamp vorhanden → Fenster pruefen + in die HMAC einbeziehen.
        try:
            ts = int(str(timestamp_header).strip())
        except (ValueError, TypeError):
            log.warning('Webhook: ungueltiger Timestamp-Header %r', timestamp_header)
            return False
        if now is None:
            now = time.time()
        if abs(now - ts) > _TIMESTAMP_TOLERANCE:
            log.warning('Webhook: Timestamp ausserhalb Fenster (ts=%s now=%s diff=%.0fs)',
                        ts, int(now), abs(now - ts))
            return False
        signed = str(ts).encode('utf-8') + b'.' + body
    else:
        # Kein Timestamp-Header → alter Pfad (rueckwaertskompatibel).
        signed = body

    expected = hmac.new(secret.encode('utf-8'), signed, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected, signature_header)
    except Exception:
        return False


def _verify_request(secret: str, raw: bytes, request: web.Request) -> bool:
    """Bequemer Wrapper: zieht Signatur- + Timestamp-Header aus dem Request."""
    return _verify_signature(
        secret, raw,
        request.headers.get('X-Webhook-Signature'),
        request.headers.get(_TIMESTAMP_HEADER),
    )


def _is_int(value: Any) -> bool:
    """True nur fuer echte ints — ``bool`` (Subklasse von int) wird abgelehnt."""
    return type(value) is int


def _make_handler(bot, secret: str):
    """Baut den aiohttp-Handler, der den Bot per Closure mitnimmt."""
    from puzzle import daily_results

    async def handle(request: web.Request) -> web.Response:
        raw = await request.read()
        if not _verify_request(secret, raw, request):
            log.warning('Webhook: HMAC-Signatur ungueltig (len=%d)', len(raw))
            return web.Response(status=401, text='invalid signature')

        try:
            payload: dict[str, Any] = json.loads(raw.decode('utf-8'))
        except Exception as e:
            log.warning('Webhook: kaputter JSON-Body: %s', e)
            return web.Response(status=400, text='invalid json')

        puzzle_id = payload.get('puzzleId')
        if not _is_int(puzzle_id):
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


def _make_daily_regenerate_handler(bot, secret: str, daily_channels):
    """Handler für ``POST /webhook/daily-regenerate`` — postet das neu generierte Tagespuzzle.

    ``daily_channels``: Liste von ``(channel_id, lang)`` (Haupt-Guild + gespiegelte
    2. Guild; lang = de/en pro Channel). Einzelne IDs (ohne Sprache) werden toleriert.
    Der alte Post wird in JEDEM gemerkten Channel in dessen Sprache als ersetzt markiert;
    das neue Daily wird in ALLE konfigurierten Channels gepostet (gleiches Puzzle, da
    RookHubs ``daily`` pro Tag deterministisch ist)."""
    from puzzle import daily_results
    from core import i18n

    # Normalisieren auf Liste von (channel_id, lang). Einzel-int/Liste-von-int tolerieren.
    if isinstance(daily_channels, int):
        daily_channels = [daily_channels]
    norm_channels: list[tuple[int, str]] = []
    for entry in (daily_channels or []):
        if isinstance(entry, (tuple, list)):
            cid = int(entry[0]); lang = i18n.norm(entry[1] if len(entry) > 1 else None)
        else:
            cid = int(entry); lang = i18n.DEFAULT_LANG
        if cid:
            norm_channels.append((cid, lang))

    async def handle(request: web.Request) -> web.Response:
        raw = await request.read()
        if not _verify_request(secret, raw, request):
            log.warning('DailyRegenerate-Webhook: HMAC-Signatur ungültig')
            return web.Response(status=401, text='invalid signature')
        try:
            payload: dict[str, Any] = json.loads(raw.decode('utf-8'))
        except Exception as e:
            log.warning('DailyRegenerate-Webhook: kaputter JSON-Body: %s', e)
            return web.Response(status=400, text='invalid json')

        date_str = payload.get('date')
        new_puzzle_id = payload.get('puzzleId')
        if not date_str or not _is_int(new_puzzle_id):
            return web.Response(status=400, text='missing date or puzzleId')

        log.info('DailyRegenerate-Webhook: date=%s newPuzzleId=%s', date_str, new_puzzle_id)

        cur = daily_results.current()
        # Idempotenz: feuert RookHub den Regenerate mehrfach (Retry/Doppel-Klick),
        # darf NICHT wiederholt ein neues Daily gepostet werden. Steht das aktuell
        # gemerkte Puzzle bereits auf ``new_puzzle_id``, ist die Regeneration schon
        # verarbeitet → no-op (sonst entstuenden Duplikat-Posts/Reinforcement-DMs).
        if cur and cur.get('date') == date_str and cur.get('puzzle_id') == new_puzzle_id:
            log.info('DailyRegenerate: puzzle %s bereits aktuell (date=%s) – idempotenter no-op.',
                     new_puzzle_id, date_str)
            return web.Response(status=200, text='already current')

        if cur and cur.get('date') == date_str:
            # Alten Post in JEDEM gemerkten Channel als ersetzt markieren
            # (_posts_of normalisiert auch migriertes Einzel-Format).
            for post in daily_results._posts_of(cur):
                try:
                    old_ch = bot.get_channel(post['channel_id']) or await bot.fetch_channel(post['channel_id'])
                    old_msg = await old_ch.fetch_message(post['message_id'])
                    await old_msg.reply(i18n.t('daily.replaced', post.get('lang')))
                except Exception as e:
                    log.warning('DailyRegenerate: Alter Post (Channel %s) nicht erreichbar: %s',
                                post.get('channel_id'), e)

            # Neues Daily in ALLE Channels posten (holt frisches Puzzle von RookHub;
            # remember() sammelt die Posts unter dem neuen Puzzle). Sprache pro Channel.
            from puzzle import posting
            for cid, lang in norm_channels:
                try:
                    channel = bot.get_channel(cid) or await bot.fetch_channel(cid)
                    await posting.post_rookhub_puzzle(channel, 'daily', with_board=True, lang=lang)
                except Exception as e:
                    log.exception('DailyRegenerate: Neues Daily (Channel %s) fehlgeschlagen: %s', cid, e)
            log.info('DailyRegenerate: Neues Daily in %d Channel(s) gepostet (date=%s)',
                     len(norm_channels), date_str)
        else:
            log.debug('DailyRegenerate: date=%s nicht aktuell (current=%s) – kein Discord-Update.',
                      date_str, cur.get('date') if cur else None)

        return web.Response(status=200, text='ok')

    return handle


def _make_weekly_handler(bot, secret: str):
    """Handler für ``POST /webhook/weekly-progress`` — aktualisiert den Wochenpost-Thread."""
    from commands import weeklypost

    async def handle(request: web.Request) -> web.Response:
        raw = await request.read()
        if not _verify_request(secret, raw, request):
            log.warning('Weekly-Webhook: HMAC-Signatur ungueltig')
            return web.Response(status=401, text='invalid signature')
        try:
            payload: dict[str, Any] = json.loads(raw.decode('utf-8'))
        except Exception as e:
            log.warning('Weekly-Webhook: kaputter JSON-Body: %s', e)
            return web.Response(status=400, text='invalid json')

        wid = payload.get('weeklyPostId')
        if not _is_int(wid):
            return web.Response(status=400, text='missing weeklyPostId')

        results = payload.get('results') if isinstance(payload.get('results'), dict) else payload
        await weeklypost.apply_weekly_update(bot, wid, results)
        return web.Response(status=200, text='ok')

    return handle


async def _build_info_handler(request: web.Request) -> web.Response:
    """GET /webhook/build-info → {sha, ref} des laufenden Images (aus GIT_SHA/GIT_REF-ENV)."""
    return web.json_response({
        'sha': os.environ.get('GIT_SHA', ''),
        'ref': os.environ.get('GIT_REF', ''),
    })


async def start(bot, host: str, port: int, secret: str, daily_channels=None) -> web.AppRunner | None:
    """Startet den aiohttp-Webhook-Server. Gibt den ``AppRunner`` zurueck (zum spaeteren Stop).

    Wird ``secret`` leer uebergeben, ist der Webhook deaktiviert → ``None``-Return.
    """
    if not secret:
        log.info('Webhook-Server deaktiviert (WEBHOOK_SECRET nicht gesetzt).')
        return None

    # client_max_size kappt zu grosse Bodies serverseitig (413 statt unbegrenztem
    # Speicher-Verbrauch beim .read()) — der Webhook erwartet nur kleine JSON-Payloads.
    app = web.Application(client_max_size=_MAX_BODY_SIZE)
    app.router.add_post('/webhook/puzzle-attempt', _make_handler(bot, secret))
    app.router.add_post('/webhook/weekly-progress', _make_weekly_handler(bot, secret))
    app.router.add_post('/webhook/daily-regenerate', _make_daily_regenerate_handler(bot, secret, daily_channels))
    # Health-Endpoint fuer Compose-Healthcheck.
    app.router.add_get('/webhook/health', lambda r: web.Response(status=200, text='ok'))
    # Build-Herkunft (CI setzt GIT_SHA/GIT_REF als Build-Arg → ENV). RookHubs Admin-CI-Seite
    # ruft das ab, um den GitHub-Actions-Run des laufenden Bot-Images zu markieren.
    app.router.add_get('/webhook/build-info', _build_info_handler)

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
