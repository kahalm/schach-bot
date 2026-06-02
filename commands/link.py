"""/link — persönlicher RookHub-Verknüpfungslink.

Schickt dem User per DM einen Link `{ROOKHUB_WEB_URL}/profile?dl=<token>`, über den
sein (eingeloggtes) RookHub-Konto automatisch mit seinem Discord-Account verknüpft wird.
Der Token ist signiert (HMAC, ``ROOKHUB_LINK_SECRET``) und nur in privaten Kanälen sicher
— daher per DM bzw. ephemerem Fallback, nie öffentlich.
"""

import logging
import os

import discord

from core import discord_link

log = logging.getLogger('schach-bot')


def setup(bot):
    tree = bot.tree

    @tree.command(name='link', description='RookHub-Konto mit deinem Discord-Account verknüpfen')
    async def cmd_link(interaction: discord.Interaction):
        web_url = os.getenv('ROOKHUB_WEB_URL', '').rstrip('/')
        if not web_url or not discord_link.is_enabled():
            await interaction.response.send_message(
                'Die RookHub-Verknüpfung ist auf diesem Server nicht konfiguriert.',
                ephemeral=True)
            return

        url = discord_link.append_dl(f'{web_url}/profile', interaction.user.id,
                                     interaction.user.name)
        text = (
            '🔗 **RookHub verknüpfen**\n'
            'Öffne diesen persönlichen Link (während du auf RookHub eingeloggt bist), '
            'um dein Discord-Konto automatisch mit deinem RookHub-Profil zu verbinden:\n'
            f'{url}\n\n'
            '_Noch kein RookHub-Konto? Registriere dich über den Link – die Verknüpfung '
            'passiert dann nach der Registrierung automatisch._'
        )

        # Link privat per DM; ephemerer Fallback, falls DMs deaktiviert sind.
        try:
            dm = await interaction.user.create_dm()
            await dm.send(text)
            await interaction.response.send_message(
                '📬 Ich habe dir den Verknüpfungslink per DM geschickt.', ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(text, ephemeral=True)
        except Exception as e:
            log.warning('/link DM fehlgeschlagen für %s: %s', interaction.user.id, e)
            await interaction.response.send_message(text, ephemeral=True)
