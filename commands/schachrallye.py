"""Schachrallye + Turnier-Verwaltung: Termine von tirol.chess.at importieren.

Alle Termine landen in einer einzigen turnier.json mit Tags.
Tag 'schachrallye' kennzeichnet Rallye-Termine (mit Reminder + Subscriber).

/schachrallye       — Rallye-Termine anzeigen
/schachrallye_add   — Manuell Rallye-Termin anlegen (Admin)
/schachrallye_del   — Rallye-Termin loeschen (Admin)
/schachrallye_sub   — Fuer Rallye-Erinnerungen subscriben
/schachrallye_unsub — Rallye-Erinnerungen abbestellen
/turnier_parse — Termine von tirol.chess.at importieren (Admin)
/turnier            — Alle zukuenftigen Turniere anzeigen
/turnier_sub <tag>  — Fuer Tag subscriben (Ping bei neuen Turnieren)
/turnier_unsub <tag>— Tag-Abo abbestellen

Dieses Modul ist nur die Registrierung (``setup``). Aufteilung:
``rallye.py`` / ``turnier.py`` (je Befehl eine Funktion), ``termine.py`` (reine Terminlogik),
``turnier_store.py`` (turnier.json), ``turnier_loops.py`` (Import, Posts, Reminder, Loops).
"""

from commands import rallye, turnier, turnier_loops


def setup(bot, tournament_channel_id: int = 0):
    turnier_loops.configure(bot, tournament_channel_id)
    tree = bot.tree

    # turnier_buttons mit Bot-Referenz konfigurieren
    from commands.turnier_buttons import configure as _configure_buttons
    _configure_buttons(bot, tournament_channel_id)

    def _register(name, description, area, callback):
        tree.command(name=name, description=description, extras={'help': area})(callback)

    # --- /schachrallye* -------------------------------------------------------
    _register('schachrallye', 'Alle zukuenftigen Schachrallye-Termine anzeigen',
              'community', rallye.cmd_schachrallye)
    _register('schachrallye_add', 'Neuen Schachrallye-Termin anlegen (Admin)',
              'admin', rallye.cmd_schachrallye_add)
    _register('schachrallye_del', 'Schachrallye-Termin loeschen (Admin)',
              'admin', rallye.cmd_schachrallye_del)
    _register('schachrallye_sub', 'Fuer Schachrallye-Erinnerungen subscriben',
              'community', rallye.cmd_schachrallye_sub)
    _register('schachrallye_unsub', 'Schachrallye-Erinnerungen abbestellen',
              'community', rallye.cmd_schachrallye_unsub)

    # --- /turnier* ------------------------------------------------------------
    _register('turnier_sub', 'Fuer einen Turnier-Tag subscriben (Ping bei neuen Turnieren)',
              'community', turnier.cmd_turnier_sub)
    _register('turnier_unsub', 'Turnier-Tag-Abo abbestellen',
              'community', turnier.cmd_turnier_unsub)
    _register('turnier_parse', 'Termine von tirol.chess.at importieren (Admin)',
              'admin', turnier.cmd_turnier_parse)
    _register('turnier', 'Alle zukuenftigen Turniere anzeigen (von tirol.chess.at)',
              'community', turnier.cmd_turnier)
    _register('turnier_review', 'Als Turnier-Reviewer subscriben/unsubscriben (Admin)',
              'admin', turnier.cmd_turnier_review)
    _register('turnier_pending', 'Ausstehende Turniere anzeigen (Admin)',
              'admin', turnier.cmd_turnier_pending)

    # --- Reminder-Loop (6 h) + Auto-Parse-Loop (taeglich 18:00 UTC) ----------
    turnier_loops.install_loops(bot)
