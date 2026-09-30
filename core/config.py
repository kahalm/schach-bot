"""Bot-Konfiguration aus der Umgebung (.env) – als Funktion statt als Modul-Nebenwirkung.

``load()`` liest und prüft alle Werte, die ``bot.py`` beim Start braucht, und gibt sie als
``BotConfig`` zurück. Ungültige Zahlen brechen wie bisher mit ``SystemExit`` und derselben
Meldung ab. Das Token prüft erst ``bot.main()`` (``TOKEN_MISSING``): ``import bot`` – etwa in
Tests – braucht keins und verbindet nicht.

Bewusst nur stdlib + ``core``: ohne discord testbar (``tests/test_config.py``).
"""

import os
from dataclasses import dataclass, field
from typing import Mapping

from core import i18n
from core.secret_env import secret_from_env

TOKEN_MISSING = 'DISCORD_TOKEN fehlt in .env – siehe .env.example'


@dataclass(frozen=True)
class BotConfig:
    discord_token: str = ''
    channel_id: int = 0
    daily_default_lang: str = i18n.DEFAULT_LANG
    daily_channel_ids: list[int] = field(default_factory=list)
    daily_channel_lang: dict[int, str] = field(default_factory=dict)
    tournament_channel_id: int = 0
    guild_id: int = 0
    wochenpost_channel_id: int = 0
    puzzle_hour: int = 9
    puzzle_minute: int = 0
    webhook_bind_host: str = '0.0.0.0'
    webhook_port: int = 9000
    webhook_secret: str = ''
    rookhub_web_url: str = ''


def _int(env: Mapping[str, str], name: str, default: str, raw: str | None = None) -> int:
    value = env.get(name, default) if raw is None else raw
    try:
        return int(value)
    except ValueError:
        raise SystemExit(f'{name} ungültig: {env.get(name)!r} — muss eine Zahl sein')


def _daily_channels(env: Mapping[str, str], channel_id: int,
                    default_lang: str) -> tuple[list[int], dict[int, str]]:
    """CHANNEL_ID + DAILY_EXTRA_CHANNEL_IDS (``ID`` oder ``ID:sprache``, komma-getrennt).

    Zusaetzliche Daily-Channels (auch in anderen Guilds) — das Tagespuzzle wird in jeden
    gepostet (gespiegelt), Solver-Tracking laeuft fuer alle. Sprache pro Channel waehlbar —
    Default DAILY_DEFAULT_LANG (sonst de). CHANNEL_ID nutzt den Default."""
    ids: list[int] = [channel_id] if channel_id else []
    langs: dict[int, str] = {channel_id: default_lang} if channel_id else {}
    for part in env.get('DAILY_EXTRA_CHANNEL_IDS', '').replace(' ', '').split(','):
        if not part:
            continue
        raw_id, _, lang = part.partition(':')
        try:
            cid = int(raw_id)
        except ValueError:
            raise SystemExit(f"DAILY_EXTRA_CHANNEL_IDS enthält ungültige ID: {raw_id!r} — Format: ID oder ID:sprache (de/en), komma-getrennt")
        if not cid:
            continue
        if cid not in ids:
            ids.append(cid)
        langs[cid] = i18n.norm(lang) if lang else default_lang
    return ids, langs


def load(env: Mapping[str, str] | None = None) -> BotConfig:
    """Liest die Konfiguration aus ``env`` (Standard: ``os.environ``) und prüft sie."""
    env = os.environ if env is None else env
    channel_id = _int(env, 'CHANNEL_ID', '0')
    default_lang = i18n.norm(env.get('DAILY_DEFAULT_LANG', 'de'))
    daily_ids, daily_langs = _daily_channels(env, channel_id, default_lang)
    tournament = _int(env, 'TOURNAMENT_CHANNEL_ID', '0',
                      raw=env.get('TOURNAMENT_CHANNEL_ID') or env.get('RALLYE_CHANNEL_ID', '0'))
    try:
        hour = int(env.get('PUZZLE_HOUR', '9'))
        minute = int(env.get('PUZZLE_MINUTE', '0'))
    except ValueError:
        raise SystemExit(
            f"PUZZLE_HOUR/PUZZLE_MINUTE ungültig: "
            f"{env.get('PUZZLE_HOUR')!r}/{env.get('PUZZLE_MINUTE')!r} — müssen Zahlen sein")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SystemExit(f'PUZZLE_HOUR/PUZZLE_MINUTE ungültig: {hour}:{minute}')
    return BotConfig(
        discord_token=env.get('DISCORD_TOKEN') or '',
        channel_id=channel_id,
        daily_default_lang=default_lang,
        daily_channel_ids=daily_ids,
        daily_channel_lang=daily_langs,
        tournament_channel_id=tournament,
        guild_id=_int(env, 'GUILD_ID', '0'),
        wochenpost_channel_id=_int(env, 'WOCHENPOST_CHANNEL_ID', '0'),
        puzzle_hour=hour,
        puzzle_minute=minute,
        # Webhook-Empfaenger: HTTP-Server fuer RookHub-Solver-Events. Leer = deaktiviert.
        webhook_bind_host=env.get('WEBHOOK_BIND_HOST', '0.0.0.0'),
        webhook_port=_int(env, 'WEBHOOK_PORT', '9000'),
        # Platzhalter aus .env.example (change_me_…) zaehlt wie leer (ERROR im Log).
        webhook_secret=secret_from_env('WEBHOOK_SECRET',
                                       'Webhook-Empfaenger (RookHub-Solver-Events)', env=env),
        rookhub_web_url=env.get('ROOKHUB_WEB_URL', '').rstrip('/'),
    )
