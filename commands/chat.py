"""KI-Schachtrainer: Claude-Chat per DM fuer whitelisted User."""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

from core.paths import CONFIG_DIR
from core.json_store import atomic_read, atomic_update
from core.permissions import is_privileged
from commands.chat_tools import TOOLS, execute_tool

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
_MAX_TOOL_ROUNDS = 5
_NOT_GIVEN = None  # Sentinel: tools weglassen wenn kein Channel

_SYSTEM_PROMPT = (
    'Du bist ein strenger, aber lustiger Schachtrainer. '
    'Du sprichst Deutsch und hilfst Schachspielern aller Stufen. '
    'Du gibst klare, direkte Antworten mit einer Prise Humor. '
    'Wenn jemand einen schlechten Zug vorschlaegt, sagst du es ehrlich — '
    'aber immer mit einem Augenzwinkern. '
    'Du liebst Taktik, hasst passive Zuege und zitierst gerne alte Meister. '
    'Halte deine Antworten kompakt (max. 2-3 Saetze), '
    'ausser der User bittet explizit um eine ausfuehrliche Erklaerung.\n\n'
    'Du hast Zugriff auf Tools um Puzzles zu senden, Training zu verwalten '
    'und Buecher vorzuschlagen. Nutze sie wenn der User danach fragt.\n'
    'Wenn der User nach Version, Hilfe oder Release-Notes fragt, nutze die '
    'entsprechenden Tools (get_version, get_help, get_release_notes).\n'
    'Wenn der User ein Buch aus der Bibliothek haben moechte, nutze send_library_book '
    'um es direkt per DM zu senden.\n\n'
    'WICHTIG fuer Zuganalyse:\n'
    '- Erfinde NIEMALS eigene Schachanalysen oder Zugfolgen. '
    'Du bist KEIN Schachcomputer. Verlass dich AUSSCHLIEßLICH auf das analyze_move Tool.\n'
    '- Nutze IMMER das analyze_move Tool wenn der User einen Zug vorschlaegt.\n'
    '- Wenn der Zug FALSCH ist: Sage NUR "Nach [user_move] kommt [best_response_san]." '
    'und frage "Was spielst du dann?". KEIN weiterer Kommentar zum Zug.\n'
    '- ABER: Wenn eval_cp > +300 oder eval_mate vorhanden ist, ist der Zug zwar nicht '
    'die Puzzle-Loesung aber trotzdem stark. Sage dann: "Dein Zug ist stark, '
    'aber das Puzzle sucht einen noch praeziseren Weg. Probier nochmal!"\n'
    '- Verrate NIEMALS den richtigen Zug! Auch nicht als Hinweis oder Andeutung. '
    'Das Tool gibt dir NICHT die Loesung — und du sollst sie auch nicht aus dem Kontext verraten.\n'
    '- Fuer Folgezuege: Nutze fen_after_response als fen-Parameter im naechsten analyze_move Aufruf.\n'
    '- Maximal 3 Runden Hin-und-Her bei falschem Ansatz. '
    'Danach sagen dass der Ansatz nicht funktioniert und einen thematischen Hinweis geben '
    '(z.B. "Denk an das Motiv des Kapitels"), aber NICHT den Zug verraten.\n'
    '- Wenn der User den RICHTIGEN Zug findet: kurz loben.\n'
    '- Halte Antworten bei Zuegen KURZ: 1-2 Saetze maximal.'
)


# --- Rate-Limit fuer nicht-whitelisted DM-Chat-Nutzer ---
# Whitelisted User chatten unbegrenzt. Alle anderen duerfen ebenfalls chatten,
# aber gedrosselt: Sliding-Window pro Prozess (reicht als Missbrauchsschutz,
# resettet bei Neustart) — verhindert ungebremsten LLM-/Tool-Zugriff.
_RATE_LIMIT_WINDOW = 60.0   # Sekunden
_RATE_LIMIT_MAX = 5         # erlaubte Nachrichten pro Fenster
_RATE_LIMIT_MSG = (
    'Kleiner Moment — du schreibst gerade sehr schnell. '
    'Versuch es in einer Minute nochmal. 🐢'
)
_rate_hits: dict[int, deque] = defaultdict(deque)


def _is_whitelisted(user_id: int) -> bool:
    """Prueft ob der User auf der Chat-Whitelist steht (chat.json)."""
    data = atomic_read(CHAT_FILE, dict)
    return user_id in data.get('whitelist', [])


def _check_rate_limit(user_id: int, now=None) -> bool:
    """True, wenn der (nicht-whitelisted) User jetzt senden darf.

    Sliding-Window: max ``_RATE_LIMIT_MAX`` Nachrichten pro
    ``_RATE_LIMIT_WINDOW`` Sekunden. Bei Erlaubnis wird der Zeitpunkt
    protokolliert; ueber Limit -> False (kein Eintrag, Fenster gleitet weiter).
    """
    if now is None:
        now = time.monotonic()
    hits = _rate_hits[user_id]
    while hits and now - hits[0] > _RATE_LIMIT_WINDOW:
        hits.popleft()
    if len(hits) >= _RATE_LIMIT_MAX:
        return False
    hits.append(now)
    return True


def _is_tool_content(msg: dict) -> bool:
    """Prueft ob eine Nachricht tool_use oder tool_result Blocks enthaelt."""
    content = msg.get('content')
    if not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and b.get('type') in ('tool_use', 'tool_result')
               for b in content)


def _sanitize_history(msgs: list[dict]):
    """Bereinigt History-Liste in-place: entfernt verwaiste Tool-Blocks.

    Nach dem Kuerzen kann die History mit einem tool_result beginnen
    (user-Nachricht ohne vorheriges tool_use vom Assistant). Oder ein
    assistant mit tool_use steht ohne folgendes tool_result.
    Beides fuehrt zu BadRequestError bei der Claude API.
    """
    clean = []
    i = 0
    while i < len(msgs):
        msg = msgs[i]
        # Verwaistes tool_result (kein tool_use davor) → ueberspringen
        if msg['role'] == 'user' and _is_tool_content(msg):
            i += 1
            continue
        # Assistant mit tool_use → nur behalten wenn tool_result folgt
        if msg['role'] == 'assistant' and _is_tool_content(msg):
            if (i + 1 < len(msgs)
                    and msgs[i + 1]['role'] == 'user'
                    and _is_tool_content(msgs[i + 1])):
                clean.append(msgs[i])
                clean.append(msgs[i + 1])
                i += 2
                continue
            else:
                # Verwaistes tool_use → ueberspringen
                i += 1
                continue
        clean.append(msg)
        i += 1
    msgs[:] = clean
    # Sicherstellen dass History mit user beginnt
    while msgs and msgs[0]['role'] != 'user':
        msgs.pop(0)


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
        # Verwaiste tool_use/tool_result Blocks bereinigen
        _sanitize_history(msgs)
        result['messages'] = list(msgs)
        return data

    atomic_update(CHAT_FILE, _update, default=dict)
    return result.get('messages', [])


def _save_assistant_response(user_id: int, text: str):
    """Speichert die Assistant-Antwort in der History."""
    _save_history_entry(user_id, {'role': 'assistant', 'content': text})


def _save_response_blocks(user_id: int, content_blocks):
    """Speichert Assistant-Content inkl. tool_use-Blocks in der History."""
    serialized = _serialize(content_blocks)
    _save_history_entry(user_id, {'role': 'assistant', 'content': serialized})


def _save_tool_results(user_id: int, tool_results: list[dict]):
    """Speichert tool_result-Blocks als User-Nachricht in der History."""
    _save_history_entry(user_id, {'role': 'user', 'content': tool_results})


def _save_history_entry(user_id: int, entry: dict):
    """Generischer Helper zum Speichern eines History-Eintrags."""
    def _update(data):
        history = data.setdefault('history', {})
        uid_key = str(user_id)
        msgs = history.setdefault(uid_key, [])
        msgs.append(entry)
        if len(msgs) > _MAX_HISTORY:
            msgs[:] = msgs[-_MAX_HISTORY:]
        while msgs and msgs[0]['role'] != 'user':
            msgs.pop(0)
        return data

    atomic_update(CHAT_FILE, _update, default=dict)


def _serialize(content_blocks) -> list[dict]:
    """Anthropic ContentBlocks -> JSON-serialisierbare Dicts."""
    result = []
    for block in content_blocks:
        if hasattr(block, 'type'):
            if block.type == 'text':
                result.append({'type': 'text', 'text': block.text})
            elif block.type == 'tool_use':
                result.append({
                    'type': 'tool_use',
                    'id': block.id,
                    'name': block.name,
                    'input': block.input,
                })
            else:
                result.append({'type': block.type})
        elif isinstance(block, dict):
            result.append(block)
        else:
            result.append({'type': 'text', 'text': str(block)})
    return result


def _extract_text(content_blocks) -> str:
    """Text-Blocks aus Response extrahieren und zusammenfuegen."""
    parts = []
    for block in content_blocks:
        if hasattr(block, 'type') and block.type == 'text':
            parts.append(block.text)
        elif isinstance(block, dict) and block.get('type') == 'text':
            parts.append(block.get('text', ''))
    return '\n'.join(parts) if parts else ''


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


async def _chat_response(user_id: int, text: str, channel=None) -> str:
    """Sendet Nachricht an Claude API und gibt die Antwort zurueck.

    channel – DM-Channel fuer Tool-Ausfuehrung (None = keine Tools).
    """
    messages = await asyncio.to_thread(_append_and_get_history, user_id, text)
    system = _build_system_prompt(user_id)

    try:
        for _ in range(_MAX_TOOL_ROUNDS):
            api_kwargs = dict(
                model=_MODEL,
                max_tokens=1024,
                system=system,
                messages=messages,
            )
            if channel:
                api_kwargs['tools'] = TOOLS

            response = await _client.messages.create(**api_kwargs)

            await asyncio.to_thread(
                _save_response_blocks, user_id, response.content)
            messages.append({
                'role': 'assistant',
                'content': _serialize(response.content),
            })

            if response.stop_reason != 'tool_use':
                return _extract_text(response.content)

            # Tools ausfuehren
            ctx = {'user_id': user_id, 'channel': channel}
            results = []
            for block in response.content:
                if hasattr(block, 'type') and block.type == 'tool_use':
                    result_str = await execute_tool(block.name, block.input, ctx)
                    results.append({
                        'type': 'tool_result',
                        'tool_use_id': block.id,
                        'content': result_str,
                    })

            await asyncio.to_thread(
                _save_tool_results, user_id, results)
            messages.append({'role': 'user', 'content': results})

        return 'Anfrage konnte nicht vollstaendig bearbeitet werden.'

    except Exception as e:
        # Bei BadRequest (kaputte History) → History leeren und nochmal versuchen
        err_name = type(e).__name__
        if 'BadRequest' in err_name or 'InvalidRequest' in err_name:
            log.warning('Claude API BadRequest fuer User %s — History wird geleert: %s',
                        user_id, e)
            try:
                def _clear(data):
                    history = data.get('history', {})
                    history.pop(str(user_id), None)
                    return data
                await asyncio.to_thread(atomic_update, CHAT_FILE, _clear, dict)
                # Nochmal mit frischer History (nur aktuelle Nachricht)
                fresh = [{'role': 'user', 'content': text}]
                api_kwargs = dict(
                    model=_MODEL, max_tokens=1024, system=system,
                    messages=fresh,
                )
                if channel:
                    api_kwargs['tools'] = TOOLS
                response = await _client.messages.create(**api_kwargs)
                await asyncio.to_thread(
                    _save_response_blocks, user_id, response.content)
                return _extract_text(response.content)
            except Exception as retry_err:
                log.exception('Claude API Retry fehlgeschlagen fuer User %s', user_id)
        else:
            log.exception('Claude API Fehler fuer User %s: %s', user_id, err_name)
        return 'Entschuldigung, da ist etwas schiefgelaufen. Versuche es spaeter nochmal.'


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
        whitelisted = await asyncio.to_thread(_is_whitelisted, message.author.id)
        if not whitelisted and not _check_rate_limit(message.author.id):
            try:
                await message.channel.send(_RATE_LIMIT_MSG)
            except Exception:
                pass
            return

        async with message.channel.typing():
            response = await _chat_response(
                message.author.id, message.content, channel=message.channel)
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
