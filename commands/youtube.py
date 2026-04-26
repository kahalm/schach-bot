"""YouTube-Sammlung: Schach-YouTube-Kanäle und -Videos teilen und auflisten."""

from commands._collection import setup_collection


def setup(bot):
    setup_collection(
        bot,
        cmd_name='youtube',
        cmd_description='YouTube-Kanäle/Videos anzeigen oder hinzufügen',
        url_label='YouTube-URL (zum Hinzufügen)',
        desc_label='Kurze Beschreibung (Kanal/Video)',
        json_filename='youtube.json',
        embed_title='▶️ YouTube',
        embed_color=0xff0000,
        item_label='YouTube-Link',
        add_hint='/youtube url:… beschreibung:…',
        empty_msg='Noch keine YouTube-Links vorhanden. '
                  'Füge einen hinzu mit `/youtube url:… beschreibung:…`',
    )
