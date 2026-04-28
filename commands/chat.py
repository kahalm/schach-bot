"""KI-Schachtrainer: Claude-Chat per DM fuer whitelisted User."""

import asyncio
import logging
import os

import discord
from discord.ext import commands

from core.paths import CONFIG_DIR
from core.json_store import atomic_read, atomic_update
from core.permissions import is_privileged

log = logging.getLogger('schach-bot')

CHAT_FILE = os.path.join(CONFIG_DIR, 'chat.json')

_CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY', '').strip()
_client = None

if _CLAUDE_API_KEY:
    try:
        import anthropic
        _client = anthropic.AsyncAnthropic(api_key=_CLAUDE_API_KEY)
    except Exception as e:
        log.warning('anthropic-Client konnte nicht erstellt werden: %s', e)

_MODEL = 'claude-sonnet-4-6'
_MAX_HISTORY = 20  # 10 Austausche (user + assistant)

_SYSTEM_PROMPT = (
    'Du bist ein strenger, aber lustiger Schachtrainer. '
    'Du sprichst Deutsch und hilfst Schachspielern aller Stufen. '
    'Du gibst klare, direkte Antworten mit einer Prise Humor. '
    'Wenn jemand einen schlechten Zug vorschlaegt, sagst du es ehrlich — '
    'aber immer mit einem Augenzwinkern. '
    'Du liebst Taktik, hasst passive Zuege und zitierst gerne alte Meister. '
    'Halte deine Antworten kompakt (max. 3-4 Absaetze), '
    'ausser der User bittet explizit um eine ausfuehrliche Erklaerung.'
)


def _is_whitelisted(user_id: int) -> bool:
    """Prueft ob der User auf der Chat-Whitelist steht.

    Aktuell fuer alle User freigeschaltet (vorerst).
    Original-Check: ``user_id in data.get('whitelist', [])``
    """
    return True


def _append_and_get_history(user_id: int, text: str) -> list[dict]:
    """Fuegt User-Nachricht an History an und gibt die History zurueck."""
    result = {}

    def _update(data):
        history = data.setdefault('history', {})
        uid_key = str(user_id)
        msgs = history.setdefault(uid_key, [])
        msgs.append({'role': 'user', 'content': text})
        # Auf _MAX_HISTORY begrenzen
        if len(msgs) > _MAX_HISTORY:
            msgs[:] = msgs[-_MAX_HISTORY:]
        # Claude API verlangt erste Nachricht mit role=user
        while msgs and msgs[0]['role'] != 'user':
            msgs.pop(0)
        result['messages'] = list(msgs)
        return data

    atomic_update(CHAT_FILE, _update, default=dict)
    return result.get('messages', [])


def _save_assistant_response(user_id: int, text: str):
    """Speichert die Assistant-Antwort in der History."""
    def _update(data):
        history = data.setdefault('history', {})
        uid_key = str(user_id)
        msgs = history.setdefault(uid_key, [])
        msgs.append({'role': 'assistant', 'content': text})
        if len(msgs) > _MAX_HISTORY:
            msgs[:] = msgs[-_MAX_HISTORY:]
        while msgs and msgs[0]['role'] != 'user':
            msgs.pop(0)
        return data

    atomic_update(CHAT_FILE, _update, default=dict)


def _build_system_prompt(user_id: int) -> str:
    """System-Prompt mit optionalem Puzzle-Kontext erweitern."""
    from puzzle.state import get_puzzle_context
    system = _SYSTEM_PROMPT
    ctx = get_puzzle_context(user_id)
    if ctx:
        system += (
            f'\n\nAktuelles Puzzle des Users:\n'
            f'Buch: {ctx["book"]}\n'
            f'Kapitel: {ctx["chapter"]}\n'
            f'Stellung (FEN): {ctx["fen"]}\n'
            f'{ctx["turn"]} am Zug\n'
            f'Schwierigkeit: {ctx["difficulty"]}\n'
        )
        if ctx.get('solution'):
            system += f'Loesung: {ctx["solution"]}\n'
        system += (
            'Gib die Loesung NICHT ungefragt preis — '
            'hilf dem User stattdessen mit Hinweisen.'
        )
    return system


async def _chat_response(user_id: int, text: str) -> str:
    """Sendet Nachricht an Claude API und gibt die Antwort zurueck."""
    messages = await asyncio.to_thread(_append_and_get_history, user_id, text)
    system = _build_system_prompt(user_id)
    try:
        response = await _client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        reply = response.content[0].text
    except Exception as e:
        log.exception('Claude API Fehler fuer User %s', user_id)
        reply = 'Entschuldigung, da ist etwas schiefgelaufen. Versuche es spaeter nochmal.'

    await asyncio.to_thread(_save_assistant_response, user_id, reply)
    return reply


def setup(bot: commands.Bot):
    """Registriert Chat-Commands und DM-Listener."""
    tree = bot.tree

    # --- DM-Listener ---

    @bot.listen('on_message')
    async def _on_dm_chat(message: discord.Message):
        if _client is None:
            return
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return
        if not message.content or message.content.startswith('/'):
            return
        if not await asyncio.to_thread(_is_whitelisted, message.author.id):
            return

        async with message.channel.typing():
            response = await _chat_response(message.author.id, message.content)
            # Discord-Limit: 2000 Zeichen (sauber am Satzende kuerzen)
            if len(response) > 2000:
                cut = response[:1997]
                # Am letzten Satzende abschneiden (oder Wortgrenze)
                for sep in ('.', '\n', ' '):
                    idx = cut.rfind(sep)
                    if idx > 1500:
                        cut = cut[:idx + 1]
                        break
                response = cut + '...'
            await message.channel.send(response)

    # --- /chat_whitelist ---

    @tree.command(name='chat_whitelist',
                  description='KI-Chat Whitelist verwalten (Admin)')
    @discord.app_commands.describe(
        user='User hinzufuegen/entfernen',
        aktion='add/remove/list (Standard: add)')
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_chat_whitelist(interaction: discord.Interaction,
                                 user: discord.User = None,
                                 aktion: str = 'add'):
        if not is_privileged(interaction):
            await interaction.response.send_message(
                '⚠️ Nur fuer Admins/Moderatoren.', ephemeral=True)
            return

        aktion = aktion.lower().strip()

        if aktion == 'list' or (user is None and aktion != 'list'):
            data = await asyncio.to_thread(atomic_read, CHAT_FILE, dict)
            wl = data.get('whitelist', [])
            if not wl:
                await interaction.response.send_message(
                    'Chat-Whitelist ist leer.', ephemeral=True)
                return
            lines = []
            for uid in wl:
                u = interaction.client.get_user(uid)
                name = u.display_name if u else f'User {uid}'
                lines.append(f'- **{name}** (`{uid}`)')
            await interaction.response.send_message(
                f'**Chat-Whitelist ({len(wl)}):**\n' + '\n'.join(lines),
                ephemeral=True)
            return

        if user is None:
            await interaction.response.send_message(
                '⚠️ Bitte einen User angeben.', ephemeral=True)
            return

        uid = user.id
        result = {}

        if aktion == 'add':
            def _add(data):
                wl = data.setdefault('whitelist', [])
                if uid in wl:
                    result['already'] = True
                else:
                    wl.append(uid)
                return data

            await asyncio.to_thread(atomic_update, CHAT_FILE, _add, dict)
            if result.get('already'):
                await interaction.response.send_message(
                    f'**{user.display_name}** ist bereits auf der Whitelist.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    f'**{user.display_name}** zur Chat-Whitelist hinzugefuegt.',
                    ephemeral=True)

        elif aktion == 'remove':
            def _remove(data):
                wl = data.setdefault('whitelist', [])
                if uid in wl:
                    wl.remove(uid)
                else:
                    result['not_found'] = True
                return data

            await asyncio.to_thread(atomic_update, CHAT_FILE, _remove, dict)
            if result.get('not_found'):
                await interaction.response.send_message(
                    f'**{user.display_name}** ist nicht auf der Whitelist.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    f'**{user.display_name}** von der Chat-Whitelist entfernt.',
                    ephemeral=True)
        else:
            await interaction.response.send_message(
                '⚠️ Ungueltige Aktion. Verwende `add`, `remove` oder `list`.',
                ephemeral=True)

    # --- /chat_clear ---

    @tree.command(name='chat_clear',
                  description='Eigene KI-Chat-Historie loeschen')
    async def cmd_chat_clear(interaction: discord.Interaction):
        uid_key = str(interaction.user.id)
        result = {}

        def _clear(data):
            history = data.get('history', {})
            if uid_key in history:
                del history[uid_key]
                result['cleared'] = True
            return data

        await asyncio.to_thread(atomic_update, CHAT_FILE, _clear, dict)
        if result.get('cleared'):
            await interaction.response.send_message(
                'Chat-Historie geloescht.', ephemeral=True)
        else:
            await interaction.response.send_message(
                'Keine Chat-Historie vorhanden.', ephemeral=True)
