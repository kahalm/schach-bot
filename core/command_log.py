"""Protokoll der Slash-Befehle, die Nutzer aufrufen.

Jeder Aufruf wird als Info-Log mit Tag ``command`` geschrieben — über den ES-Handler aus
``core/log_setup.py`` landet er in ``schach-bot-logs-*`` (Felder unter ``labels.*``):
Befehl, Nutzer, Ort (Server/Kanal oder DM), Parameter (gekürzt), Ergebnis und Dauer.

Aufgerufen aus ``bot.py``: der Listener für ``on_app_command_completion`` (erfolgreich
beendete Befehle) und der Tree-Error-Handler (Cooldown, fehlende Rechte, Fehler).
Discord-Objekte werden nur per Duck-Typing gelesen — Logging darf nie einen Befehl stören.
"""

import logging
from datetime import datetime, timezone

log = logging.getLogger('schach-bot')

TAG = 'command'

# Längere Parameterwerte (z.B. Freitext) werden gekürzt.
MAX_VALUE_LEN = 100


def _short(value) -> str:
    """Parameterwert als kurzer Text; Discord-Objekte (Member, Kanal, Rolle) als ``name (id)``."""
    if hasattr(value, 'id') and hasattr(value, 'name'):
        text = f'{value.name} ({value.id})'
    elif hasattr(value, 'filename'):
        text = str(value.filename)
    else:
        text = str(value)
    text = ' '.join(text.split())
    if len(text) > MAX_VALUE_LEN:
        text = text[:MAX_VALUE_LEN] + '…'
    return text


def build_entry(*, command: str, user_id, user_name, guild_id, guild_name, channel_id,
                channel_name, options: dict | None, outcome: str, error: str | None = None,
                duration_ms: int | None = None) -> tuple[str, dict]:
    """Baut Nachricht und ES-Felder für einen Befehlsaufruf.

    IDs werden als String abgelegt: Discord-Snowflakes sind größer als 2^53.
    ``options`` landet als EIN String (``name=wert …``), damit ``labels`` flach bleibt."""
    opts = ' '.join(f'{k}={_short(v)}' for k, v in (options or {}).items() if v is not None)
    where = (guild_name or str(guild_id)) if guild_id else 'DM'

    msg = f'Befehl /{command} von {user_name} ({user_id}) in {where}'
    if opts:
        msg += f' {opts}'
    if outcome != 'ok':
        msg += f' → {outcome}' + (f' ({error})' if error else '')

    fields = {
        'tags': [TAG],
        'command': command,
        'user_id': str(user_id),
        'user_name': user_name,
        'location': 'guild' if guild_id else 'dm',
        'guild_id': str(guild_id) if guild_id else None,
        'guild_name': guild_name if guild_id else None,
        'channel_id': str(channel_id) if channel_id else None,
        'channel_name': channel_name,
        'options': opts or None,
        'outcome': outcome,
        'error': error,
        'duration_ms': duration_ms,
    }
    return msg, {k: v for k, v in fields.items() if v is not None}


def outcome_for(error: BaseException) -> str:
    """Ergebnis eines fehlgeschlagenen Befehls: ``cooldown``, ``denied`` (Check/Rechte) oder
    ``error``. Über die Klassennamen der MRO — so auch ohne echtes discord-Modul testbar."""
    names = {cls.__name__ for cls in type(error).__mro__}
    if 'CommandOnCooldown' in names:
        return 'cooldown'
    if 'CheckFailure' in names:
        return 'denied'
    return 'error'


def log_command(interaction, command=None, outcome: str = 'ok', error=None) -> None:
    """Protokolliert einen Befehlsaufruf. Wirft nie."""
    try:
        command = command or getattr(interaction, 'command', None)
        name = getattr(command, 'qualified_name', None) or getattr(command, 'name', None) or '?'
        user = interaction.user
        guild = getattr(interaction, 'guild', None)
        channel = getattr(interaction, 'channel', None)
        namespace = getattr(interaction, 'namespace', None)
        try:
            options = dict(iter(namespace)) if namespace is not None else {}
        except TypeError:
            options = {}
        duration_ms = None
        created = getattr(interaction, 'created_at', None)
        if isinstance(created, datetime):
            duration_ms = int((datetime.now(timezone.utc) - created).total_seconds() * 1000)
        if isinstance(error, BaseException):
            error = type(error).__name__

        msg, fields = build_entry(
            command=name,
            user_id=getattr(user, 'id', '?'),
            user_name=getattr(user, 'name', None) or '?',
            guild_id=getattr(guild, 'id', None) if guild is not None else None,
            guild_name=getattr(guild, 'name', None) if guild is not None else None,
            channel_id=getattr(interaction, 'channel_id', None),
            channel_name=getattr(channel, 'name', None) if channel is not None else None,
            options=options,
            outcome=outcome,
            error=error,
            duration_ms=duration_ms,
        )
        log.info(msg, extra={'es_fields': fields})
    except Exception as e:
        log.debug('Befehls-Log fehlgeschlagen: %s', e)
