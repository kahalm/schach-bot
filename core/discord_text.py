"""Fremdtext (RookHub-Anzeigenamen) sicher in Discord-Markdown einsetzen.

RookHub-Anzeigenamen sind frei waehlbar (nur auf 50 Zeichen begrenzt) und landen in
oeffentlichen Bot-Embeds (Tagespuzzle-Solver, Bestenliste, Wochenpost). Discord rendert dort
Markdown inklusive Masked Links (``[Text](url)``), Erwaehnungen (``<@id>``) und Zeilen-Markup
(``#``, ``>``, ``-``) — ungefiltert koennte jeder im Namen des Bots einen fremden Link zeigen.

Bewusst nur stdlib: die Formatter in :mod:`puzzle.daily_results` und
:mod:`puzzle.daily_leaderboard` kommen ohne discord-Import aus und sollen das bleiben.
"""

import re

# Zeichen, mit denen Discord-Markdown Formatierung (* _ ~ | `), Zeilen-Markup (> # -),
# Masked Links ([ ]), Erwaehnungen/Emojis/Zeitstempel (<) oder Autolinks (: in https://)
# beginnt, plus der Backslash selbst (sonst hebt ein Namens-Backslash unser Escaping auf).
# Discord blendet einen Backslash vor ASCII-Satzzeichen aus → optisch unveraendert.
_MD_CHARS = frozenset('\\*_~|`>#-[]<:')
# Steuerzeichen, Zeilentrenner und Bidi-Steuerzeichen: ein Name darf keine eigene Zeile
# anfangen (Header/Zitat/Fake-Eintrag) und die Leserichtung der Zeile nicht umdrehen.
_CTRL_RE = re.compile('[\x00-\x1f\x7f\x85  ‪-‮⁦-⁩]+')

NAME_MAX_LEN = 50


def escape_display_name(name, max_len: int = NAME_MAX_LEN) -> str:
    """Macht einen fremden Anzeigenamen zu reinem Text fuer Discord-Markdown.

    Steuerzeichen/Zeilenumbrueche → Leerzeichen, Markdown-Zeichen mit Backslash escapet.
    Die Laenge wird NACH dem Escapen auf ``max_len`` gedeckelt (plus ``…``), damit ein
    Sonderzeichen-Name das Embed-Feld (1024 Zeichen) nicht staerker fuellt als ein normaler.
    Normale Namen (Buchstaben, Ziffern, Leerzeichen) bleiben byte-gleich. Leer → ``''``.
    """
    text = _CTRL_RE.sub(' ', str(name or '')).strip()
    out, used = [], 0
    for ch in text:
        piece = '\\' + ch if ch in _MD_CHARS else ch
        if used + len(piece) > max_len:
            out.append('…')
            break
        out.append(piece)
        used += len(piece)
    return ''.join(out)
