"""Fremdtext (RookHub-Anzeigenamen) sicher in Discord-Markdown einsetzen.

RookHub-Anzeigenamen sind frei waehlbar (nur auf 50 Zeichen begrenzt) und landen in
oeffentlichen Bot-Embeds (Tagespuzzle-Solver, Bestenliste, Wochenpost). Discord rendert dort
Markdown inklusive Masked Links (``[Text](url)``), Erwaehnungen (``<@id>``) und Zeilen-Markup
(``#``, ``>``, ``-``) — ungefiltert koennte jeder im Namen des Bots einen fremden Link zeigen.

Dazu die Laengengrenzen der Discord-Embeds (:func:`clip`, :func:`fit_list`): ein zu langer
Titel oder Feldwert laesst Discord die ganze Nachricht mit HTTP 400 ablehnen.

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

# Discord-Grenzen fuer Embeds (Zeichen); darueber lehnt Discord die ganze Nachricht ab.
EMBED_TITLE_MAX = 256
EMBED_FIELD_VALUE_MAX = 1024


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


def clip(text, max_len: int) -> str:
    """Kuerzt ``text`` auf hoechstens ``max_len`` Zeichen (z. B. :data:`EMBED_TITLE_MAX`).

    Passt der Text, bleibt er byte-gleich. Sonst wird vor der Grenze an der letzten Zeilen-
    oder Wortgrenze abgeschnitten (keine halbe Erwaehnung ``<@…>``), ohne brauchbare Grenze
    hart, nie zwischen Backslash und escaptem Zeichen; dahinter steht ``…``.
    """
    text = str(text or '')
    if len(text) <= max_len:
        return text
    if max_len < 1:
        return ''
    cut = text[:max_len - 1]
    brk = max(cut.rfind('\n'), cut.rfind(' '))
    if brk >= max_len // 2:
        cut = cut[:brk]
    cut = cut.rstrip()
    if (len(cut) - len(cut.rstrip('\\'))) % 2:
        cut = cut[:-1]   # sonst escapt der verwaiste Backslash das Auslassungszeichen
    return cut + '…'


def fit_list(items, render, max_len: int = EMBED_FIELD_VALUE_MAX) -> str:
    """Rendert eine Liste so, dass das Ergebnis in ``max_len`` passt (Feldwert: 1024).

    ``render(shown)`` baut den Text aus den gezeigten Eintraegen (samt „+N weitere" fuer den
    Rest). Ist er zu lang, faellt hinten je ein Eintrag weg, bis er passt; :func:`clip`
    sichert den Rest ab. Passt alles, ist das Ergebnis genau ``render(items)``.
    """
    shown = list(items)
    text = render(shown)
    while len(text) > max_len and shown:
        shown.pop()
        text = render(shown)
    return clip(text, max_len)
