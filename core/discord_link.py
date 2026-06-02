"""HMAC-signierte Tokens für die automatische RookHub↔Discord-Verknüpfung.

Ein Token transportiert die Discord-User-ID (Snowflake) signiert an RookHub. Öffnet
ein User einen Link mit ``?dl=<token>``, verifiziert RookHub die Signatur (gemeinsames
Secret ``ROOKHUB_LINK_SECRET`` == RookHubs ``Discord:LinkSecret``) und verknüpft das
Konto. Format identisch zu RookHubs ``DiscordLinkService``:

    token = body + "." + sig
    body  = base64url(utf8(JSON {"id","u","exp"}))   (ohne Padding)
    sig   = base64url(HMAC_SHA256(secret, body))      (ohne Padding)

WICHTIG: Token nur an PRIVATE Empfänger hängen (DMs / ``/link`` / Hello-Post-DM),
niemals in öffentliche Channel-Posts – sonst könnte ein Dritter die fremde Discord-ID
auf seinen Account verknüpfen.

Bewusst ohne discord-Abhängigkeit (nur stdlib), damit eigenständig testbar.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

# Gemeinsames Secret. Leer -> Feature inaktiv (kein Token wird erzeugt/angehängt).
LINK_SECRET = os.getenv('ROOKHUB_LINK_SECRET', '')

# Gültigkeitsdauer eines Link-Tokens (großzügig: der User klickt evtl. erst Tage später).
DEFAULT_TTL = 30 * 24 * 3600  # 30 Tage


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def is_enabled(secret: str | None = None) -> bool:
    return bool(secret if secret is not None else LINK_SECRET)


def make_link_token(discord_id, username: str | None = None,
                    ttl_seconds: int = DEFAULT_TTL,
                    secret: str | None = None,
                    now: float | None = None) -> str | None:
    """Erzeugt ein signiertes Link-Token oder ``None``, wenn kein Secret gesetzt ist."""
    secret = secret if secret is not None else LINK_SECRET
    if not secret:
        return None
    exp = int((now if now is not None else time.time())) + int(ttl_seconds)
    payload = {'id': str(discord_id), 'u': username or '', 'exp': exp}
    # Kompakte, deterministische Serialisierung. RookHub verifiziert ueber genau diesen
    # uebertragenen body-String (nicht re-serialisiert), daher ist das Format unkritisch.
    body_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    body = _b64url(body_json.encode('utf-8'))
    sig = _b64url(hmac.new(secret.encode('utf-8'), body.encode('utf-8'), hashlib.sha256).digest())
    return f'{body}.{sig}'


def append_dl(url: str | None, discord_id, username: str | None = None,
              secret: str | None = None, **kw) -> str | None:
    """Hängt ``?dl=<token>`` an eine URL an.

    Gibt die URL unverändert zurück, wenn sie leer ist oder kein Secret gesetzt ist.
    """
    if not url:
        return url
    token = make_link_token(discord_id, username, secret=secret, **kw)
    if not token:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query['dl'] = token
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(query), parts.fragment))
