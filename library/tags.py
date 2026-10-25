"""Bibliothek: Tag-Wörterbücher (Eröffnung, Thema, Format, Sprache) und ``_auto_tag``."""

import re

# ---------------------------------------------------------------------------
# Tag-Wörterbücher
# ---------------------------------------------------------------------------

def _compile_tags(d: dict[str, list[str]]) -> dict[str, list[re.Pattern]]:
    return {tag: [re.compile(p) for p in pats] for tag, pats in d.items()}


_OPENING_TAGS: dict[str, list[str]] = {
    'Sizilianisch':   [r'\bsicilian\b', r'\bsizilian\b'],
    'Französisch':    [r'\bfrench\b', r'\bfranz[oö]sisch\b'],
    'Königsindisch':  [r"\bking'?s?\s+indian\b", r'\bk[oö]nigsindisch\b'],
    'Caro-Kann':      [r'\bcaro[\s-]?kann\b'],
    'Spanisch':       [r'\bruy\s+lopez\b', r'\bspanish\b', r'\bspanisch\b'],
    'Damengambit':    [r"\bqueen'?s?\s+gambit\b", r'\bdamengambit\b'],
    'Nimzoindisch':   [r'\bnimzo[\s-]?indian\b'],
    'Holländisch':    [r'\bdutch\b', r'\bholl[aä]ndisch\b'],
    'Pirc':           [r'\bpirc\b'],
    'Skandinavisch':  [r'\bscandinavian\b', r'\bskandinavisch\b'],
    'Slawisch':       [r'\bslav\b', r'\bslaw\b'],
    'Grünfeld':       [r'\bgr[uü]nfeld\b'],
    'Benoni':         [r'\bbenoni\b'],
    'Englisch':       [r'\benglish\s+opening\b', r'\benglisch\b'],
    'Italienisch':    [r'\bitalian\b', r'\bitalienisch\b'],
    'Katalanisch':    [r'\bcatalan\b', r'\bkatalanisch\b'],
    'Philidor':       [r'\bphilidor\b'],
    'Aljechin':       [r"\balekhine'?s?\s+defen[cs]e\b", r'\balechin\b'],
    'Petrov':         [r'\bpetrov\b', r'\bpetroff\b', r'\brussian\s+game\b'],
    'Grob':           [r'\bgrob\b'],
    'Königsgambit':   [r"\bking'?s?\s+gambit\b", r'\bk[oö]nigsgambit\b'],
}

_TOPIC_TAGS: dict[str, list[str]] = {
    'Taktik':       [r'\btactic', r'\btaktik', r'\bcombination'],
    'Endspiel':     [r'\bendgame\b', r'\bendspiel\b', r'\bending\b'],
    'Strategie':    [r'\bstrateg', r'\bpositional\b'],
    'Mittelspiel':  [r'\bmiddlegame\b', r'\bmittelspiel\b'],
    'Eröffnung':    [r'\bopening\b', r'\ber[oö]ffnung\b'],
    'Mattsetzen':   [r'\bcheckmate\b', r'\bmatt\b', r'\bmate\b'],
    'Aufgaben':     [r'\bpuzzle\b', r'\bproblem\b', r'\br[aä]tsel\b'],
    'Angriff':      [r'\battack\b', r'\bangriff\b'],
    'Verteidigung': [r'\bdefen[cs]e\b', r'\bverteidigung\b', r'\bdefensive\b'],
}

_FORMAT_TAGS: dict[str, list[str]] = {
    'eBook': ['pdf', 'epub', 'djvu', 'azw', 'azw3', 'mobi'],
    'PGN':   ['pgn'],
    'Video': ['mp4', 'avi', 'mkv', 'wmv'],
    'Audio': ['mp3', 'm4b', 'm4a', 'wma', 'flac'],
}

_LANGUAGE_TAGS: dict[str, list[str]] = {
    'Deutsch':    [r'\(german\)', r'\bdeutsch\b'],
    'Russisch':   [r'\(russian\)', r'\brussisch\b'],
    'Französisch (Sprache)': [r'\(french\)', r'\bfrançais\b'],
    'Spanisch (Sprache)':    [r'\(spanish\)', r'\bespañol\b'],
}

_OPENING_RE = _compile_tags(_OPENING_TAGS)
_TOPIC_RE = _compile_tags(_TOPIC_TAGS)
_LANGUAGE_RE = _compile_tags(_LANGUAGE_TAGS)


def _auto_tag(title: str, author: str, file_ext: str) -> list[str]:
    """Generiert Tags aus Titel und Dateityp."""
    tags: list[str] = []
    text = f'{title} {author}'.lower()
    for tag, patterns in _OPENING_RE.items():
        if any(p.search(text) for p in patterns):
            tags.append(tag)
    for tag, patterns in _TOPIC_RE.items():
        if any(p.search(text) for p in patterns):
            tags.append(tag)
    for tag, exts in _FORMAT_TAGS.items():
        if file_ext in exts:
            tags.append(tag)
            break
    for tag, patterns in _LANGUAGE_RE.items():
        if any(p.search(text) for p in patterns):
            tags.append(tag)
    return tags
