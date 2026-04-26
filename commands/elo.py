"""ELO-Modul: User können ihre eigene Schach-Elo angeben (mit Historie)."""

import logging
import os
from datetime import datetime, timezone

import discord

from core.paths import CONFIG_DIR
from core.json_store import atomic_read, atomic_update

log = logging.getLogger('schach-bot')

ELO_FILE = os.path.join(CONFIG_DIR, 'elo.json')


def get_current(user_id: int) -> int | None:
    """Letzte ELO eines Users (oder None)."""
    history = atomic_read(ELO_FILE, default=dict).get(str(user_id), [])
    return history[-1]['elo'] if history else None


def get_history(user_id: int) -> list[dict]:
    """Vollständige ELO-Historie eines Users."""
    return atomic_read(ELO_FILE, default=dict).get(str(user_id), [])


def add(user_id: int, elo: int):
    """Neuen ELO-Eintrag mit aktuellem Zeitstempel hinzufügen."""
    uid = str(user_id)

    def _append_elo(data):
        if uid not in data:
            data[uid] = []
        data[uid].append({
            'elo': elo,
            'ts': datetime.now(timezone.utc).isoformat(),
        })
        return data

    atomic_update(ELO_FILE, _append_elo, default=dict)


def setup(bot):
    tree = bot.tree

    @tree.command(name='elo', description='Eigene Schach-Elo angeben oder anzeigen')
    @discord.app_commands.describe(
        wert='Deine aktuelle Elo (100–3500). Ohne Wert: aktuelle Elo + Historie anzeigen.',
    )
    async def cmd_elo(interaction: discord.Interaction, wert: int = None):
        uid = interaction.user.id

        # Ohne Wert → Status + Historie
        if wert is None:
            history = get_history(uid)
            if not history:
                await interaction.response.send_message(
                    'Du hast noch keine Elo angegeben. '
                    'Nutze `/elo wert:1500` um sie zu setzen.',
                    ephemeral=True,
                )
                return

            current = history[-1]['elo']
            lines = [f'**Aktuelle Elo:** {current}']
            if len(history) > 1:
                lines.append('')
                lines.append('**Historie:**')
                for entry in history[-10:]:
                    try:
                        ts = datetime.fromisoformat(entry['ts'])
                        lines.append(f"• {entry['elo']} — <t:{int(ts.timestamp())}:d>")
                    except (ValueError, KeyError):
                        lines.append(f"• {entry.get('elo', '?')}")
                if len(history) > 10:
                    lines.insert(2, f'_(zeige letzte 10 von {len(history)} Einträgen)_')
            await interaction.response.send_message('\n'.join(lines), ephemeral=True)
            return

        # Validierung
        if not 100 <= wert <= 3500:
            await interaction.response.send_message(
                'Elo muss zwischen 100 und 3500 liegen.', ephemeral=True
            )
            return

        add(uid, wert)
        log.info('Elo gesetzt: User %s → %d', uid, wert)
        await interaction.response.send_message(
            f'Elo gespeichert: **{wert}** ✅', ephemeral=True
        )
