"""DM-Log: jede ausgehende DM wird pro User in config/dm_log.json festgehalten.

Aktivierung einmalig über ``install()`` beim Bot-Start. Danach wird
``discord.DMChannel.send`` transparent gewrappt — keine Call-Site muss
geändert werden.

JSON-Format:
    {
      "123456789": [
        {"ts": "2026-04-25T18:00:00+00:00", "text": "Hallo!"},
        {"ts": "...", "text": "[embed: 🧩 Checkmate Patterns Manual]"},
        ...
      ]
    }
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import discord

from core.json_store import atomic_update
from core.paths import CONFIG_DIR

log = logging.getLogger('schach-bot')

DM_LOG_FILE = os.path.join(CONFIG_DIR, 'dm_log.json')

_DM_LOG_MAX_AGE_DAYS = 30


def _describe(*args, **kwargs) -> str:
    """Kurze lesbare Beschreibung des gesendeten Inhalts."""
    # Positionaler Text-Inhalt
    if args and isinstance(args[0], str):
        text = args[0]
        return text[:300] + ('…' if len(text) > 300 else '')

    content = kwargs.get('content')
    if content:
        return content[:300] + ('…' if len(content) > 300 else '')

    embed = kwargs.get('embed')
    if embed is not None:
        title = getattr(embed, 'title', '') or ''
        desc  = getattr(embed, 'description', '') or ''
        return f'[embed: {title}]' + (f' — {desc[:100]}' if desc else '')

    if kwargs.get('file') is not None:
        return '[file]'

    return '[unbekannter Inhalt]'


def _append(user_id: int, text: str):
    """Hängt einen Eintrag an das DM-Log an (sync, für asyncio.to_thread).
    Entfernt Einträge älter als 30 Tage für diesen User."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_DM_LOG_MAX_AGE_DAYS)).isoformat()

    def _update(data):
        key = str(user_id)
        entries = data.setdefault(key, [])
        entries.append({
            'ts':   datetime.now(timezone.utc).isoformat(),
            'text': text,
        })
        data[key] = [e for e in entries if e.get('ts', '') >= cutoff]
        return data

    atomic_update(DM_LOG_FILE, _update)


_installed = False


def install():
    """Monkey-patcht discord.DMChannel.send einmalig beim Bot-Start."""
    import asyncio

    global _installed
    if _installed:
        return
    _installed = True

    _original_send = discord.DMChannel.send

    async def _patched_send(self: discord.DMChannel, *args, **kwargs):
        try:
            recipient = getattr(self, 'recipient', None)
            user_id   = recipient.id if recipient else None
            if user_id:
                text = _describe(*args, **kwargs)
                await asyncio.to_thread(_append, user_id, text)
        except Exception as e:
            log.warning('DM-Log fehlgeschlagen: %s', e)
        return await _original_send(self, *args, **kwargs)

    discord.DMChannel.send = _patched_send
    log.info('DM-Log aktiv → %s', DM_LOG_FILE)
