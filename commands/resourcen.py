"""Ressourcen-Sammlung: Online-Lernressourcen teilen und auflisten."""

from commands._collection import setup_collection


def setup(bot):
    setup_collection(
        bot,
        cmd_name='resourcen',
        cmd_description='Online-Lernressourcen anzeigen oder hinzufügen',
        url_label='URL der Ressource (zum Hinzufügen)',
        desc_label='Kurze Beschreibung der Ressource',
        json_filename='resourcen.json',
        embed_title='🔗 Ressourcen',
        embed_color=0x3498db,
        item_label='Ressource',
        add_hint='/resourcen url:… beschreibung:…',
        empty_msg='Noch keine Ressourcen vorhanden. '
                  'Füge eine hinzu mit `/resourcen url:… beschreibung:…`',
    )
