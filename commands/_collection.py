"""Generische URL-Collection: wiederverwendbare Add/List-Logik fuer resourcen.py und youtube.py."""

import os
from datetime import date

import discord

from core.json_store import atomic_read, atomic_update

_MAX_ENTRIES = 100


def _json_path(filename: str) -> str:
    """Berechnet den JSON-Pfad zur Laufzeit (damit Test-Patches auf CONFIG_DIR wirken)."""
    from core.paths import CONFIG_DIR
    return os.path.join(CONFIG_DIR, filename)


def setup_collection(bot, *,
                     cmd_name: str,
                     cmd_description: str,
                     url_label: str,
                     desc_label: str,
                     json_filename: str,
                     embed_title: str,
                     embed_color: int,
                     item_label: str,
                     add_hint: str,
                     empty_msg: str = ''):
    """Registriert einen URL-Collection-Command mit Add/List-Logik."""
    tree = bot.tree

    @tree.command(name=cmd_name, description=cmd_description)
    @discord.app_commands.describe(url=url_label, beschreibung=desc_label)
    async def _cmd(interaction: discord.Interaction,
                   url: str = None,
                   beschreibung: str = None):
        json_file = _json_path(json_filename)

        if url:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                await interaction.response.send_message(
                    '⚠️ Bitte eine gueltige URL angeben (http:// oder https://).',
                    ephemeral=True)
                return
            if not beschreibung:
                await interaction.response.send_message(
                    '⚠️ Bitte auch eine `beschreibung` angeben.',
                    ephemeral=True)
                return

            new_entry = {
                'url': url[:500],
                'beschreibung': beschreibung[:500],
                'user': interaction.user.display_name,
                'datum': str(date.today()),
            }
            result = {}

            def _add(entries):
                if len(entries) >= _MAX_ENTRIES:
                    result['full'] = True
                    return entries
                if any(e['url'] == new_entry['url'] for e in entries):
                    result['duplicate'] = True
                    return entries
                entries.append(new_entry)
                return entries

            atomic_update(json_file, _add, default=list)
            if result.get('full'):
                await interaction.response.send_message(
                    f'⚠️ Maximum von {_MAX_ENTRIES} Eintraegen erreicht.',
                    ephemeral=True)
                return
            if result.get('duplicate'):
                await interaction.response.send_message(
                    '⚠️ Diese URL existiert bereits.',
                    ephemeral=True)
                return
            await interaction.response.send_message(
                f'✅ {item_label} gespeichert: **{beschreibung}**\n{url}')
            return

        entries = atomic_read(json_file, default=list)
        if not entries:
            msg = empty_msg or (
                f'Noch keine Eintraege vorhanden. '
                f'Fuege einen hinzu mit `{add_hint}`')
            await interaction.response.send_message(msg, ephemeral=True)
            return

        # Discord-Limits: 25 Felder pro Embed UND max. 6000 Zeichen kombiniert
        # ueber ALLE Embeds einer Nachricht. Lange Sammlungen (Feld bis ~770
        # Zeichen) sprengen das 6000er-Budget lange vor den 25 Feldern → wir
        # chunken nach Zeichen-Budget und senden jeden Embed als eigene
        # Nachricht (erste via response, Rest via followup).
        _MAX_FIELDS = 25
        _CHAR_BUDGET = 5800  # Puffer unterm 6000er-Limit (Titel etc.)
        embeds = []
        em = None
        em_size = 0
        for j, e in enumerate(entries, 1):
            name = f'{j}. {e["beschreibung"]}'
            if len(name) > 256:
                name = name[:253] + '...'
            value = f'{e["url"]}\n_von {e["user"]} am {e["datum"]}_'
            field_size = len(name) + len(value)
            if em is None or len(em.fields) >= _MAX_FIELDS or em_size + field_size > _CHAR_BUDGET:
                em = discord.Embed(
                    title=embed_title if not embeds else None,
                    color=embed_color,
                )
                em_size = len(embed_title) if not embeds else 0
                embeds.append(em)
            em.add_field(name=name, value=value, inline=False)
            em_size += field_size

        await interaction.response.send_message(embed=embeds[0])
        for em in embeds[1:]:
            await interaction.followup.send(embed=em)
