"""PGN-Verarbeitung: Trimmen, Bereinigen, Blind-Modus-Splitting."""

import io
import re
import logging

import chess
import chess.pgn

log = logging.getLogger('schach-bot')

# Vorkompilierte Regex-Muster (6.6: vermeidet re.compile bei jedem Aufruf)
_RE_TQU = re.compile(r'\[%tqu\b[^\]]*\]')
_RE_ANNOTATION = re.compile(r'\[%\w+[^\]]*\]')
_RE_EMPTY_COMMENT = re.compile(r'\{\s*\}')
_RE_MULTI_SPACE = re.compile(r'  +')
_RE_FEN_HEADER = re.compile(r'^\[FEN\s+"', re.MULTILINE)
_RE_SETUP_HEADER = re.compile(r'^\[SetUp\s+"', re.MULTILINE)
_RE_FEN_LINE = re.compile(r'(^\[FEN\s+"[^"]*"\])', re.MULTILINE)


def _solution_pgn(game: chess.pgn.Game) -> str:
    """Exportiert die Lösung als bereinigten PGN-String (ohne Header, mit Varianten+Kommentaren)."""
    exporter = chess.pgn.StringExporter(headers=False, variations=True, comments=True)
    return _strip_pgn_annotations(game.accept(exporter))


def _clean_book_name(filename: str) -> str:
    """Entfernt PGN-Suffixe aus einem Buch-Dateinamen für die Anzeige."""
    return filename.removesuffix('_firstkey.pgn').removesuffix('.pgn')


def _prelude_pgn(context: chess.pgn.Game, puzzle: chess.pgn.Game) -> str:
    """Züge aus context VOR der Puzzle-Startstellung exportieren (ohne Lösung)."""
    # Nur Brettposition vergleichen (ohne Halbzug-/Zugzähler)
    def _key(b): return b.board_fen() + (' w ' if b.turn == chess.WHITE else ' b ')
    target_board = _key(puzzle.board())
    # Puzzle-Stellung = Root der Originalpartie → kein Vorspiel
    if _key(context.board()) == target_board:
        return ''
    prelude = chess.pgn.Game()
    prelude.headers.clear()
    ctx_fen = context.board().fen()
    if ctx_fen != chess.STARTING_FEN:
        prelude.headers['SetUp'] = '1'
        prelude.headers['FEN'] = ctx_fen
    node_src = context
    node_dst = prelude
    while node_src.variations:
        child = node_src.variations[0]
        cb = child.board()
        child_key = cb.board_fen() + (' w ' if cb.turn == chess.WHITE else ' b ')
        node_dst = node_dst.add_variation(child.move)
        if child_key == target_board:
            break
        node_src = child
    exporter = chess.pgn.StringExporter(
        headers=False, variations=False, comments=False)
    result = prelude.accept(exporter).strip()
    # Leeres Vorspiel (keine Züge) ergibt nur "*" – nicht sinnvoll anzeigen.
    return '' if result == '*' else result

def _has_training_comment(game: chess.pgn.Game) -> bool:
    """Prüft ob irgendein Knoten in der Hauptlinie [%tqu] enthält."""
    node = game
    while True:
        if '[%tqu' in (node.comment or ''):
            return True
        if not node.variations:
            return False
        node = node.variations[0]

def _trim_to_training_position(game: chess.pgn.Game) -> chess.pgn.Game:
    """Spiel auf erste [%tqu]-Stellung kürzen.
    Ohne [%tqu]-Annotation → Original unverändert zurückgeben.

    Gibt ein neues Game ab der Position des [%tqu]-Knotens zurück,
    mit dessen Varianten als Lösungsbaum.
    """
    node = game
    while True:
        if '[%tqu' in (node.comment or ''):
            break
        if not node.variations:
            return game  # kein Trainingskommentar → Original
        node = node.variations[0]

    def _gather_comments(n: chess.pgn.GameNode) -> str:
        """Alle Kommentare aus einem Teilbaum sammeln (fuer Nullzug-Varianten)."""
        parts = []
        if n.starting_comment:
            parts.append(n.starting_comment)
        if n.comment:
            parts.append(n.comment)
        for v in n.variations:
            sub = _gather_comments(v)
            if sub:
                parts.append(sub)
        return ' '.join(parts)

    def _copy(src: chess.pgn.GameNode, dst: chess.pgn.GameNode,
              board: chess.Board):
        """Baum ab src nach dst kopieren; board ist die Stellung bei dst."""
        for var in src.variations:
            if var.move not in board.legal_moves:
                text = _gather_comments(var)
                if text:
                    dst.comment = ((dst.comment or '') + ' ' + text).strip()
                continue
            child = dst.add_variation(
                var.move,
                comment=var.comment,
                starting_comment=var.starting_comment,
                nags=list(var.nags),
            )
            next_board = board.copy()
            next_board.push(var.move)
            _copy(var, child, next_board)

    def _build(src_node):
        """Neues Game ab src_node's Stellung mit dessen Varianten bauen."""
        brd = src_node.board()
        g = chess.pgn.Game()
        g.setup(brd)
        for key, val in game.headers.items():
            if key not in ('FEN', 'SetUp'):
                g.headers[key] = val
        g.comment = _RE_TQU.sub('', src_node.comment or '').strip()
        _copy(src_node, g, brd)
        return g

    return _build(node)


# ---------------------------------------------------------------------------
# Blind-Modus: zeigt Stellung X Züge VOR der Trainingsposition.
# Der User muss die X Züge im Kopf spielen und dann das Puzzle lösen.
# ---------------------------------------------------------------------------

def _split_for_blind(original_game: chess.pgn.Game, x_moves: int):
    """Findet erstes [%tqu]-Node, gibt (blind_board, blind_san_list, puzzle_game) zurück.

    blind_board – Stellung X Halbzüge VOR der Trainingsposition (chess.Board)
    blind_san_list – Liste der X Züge in SAN, die zur Trainingsposition führen
    puzzle_game – chess.pgn.Game ab Trainingsposition (wie _trim_to_training_position)

    Gibt None zurück wenn die Linie kein [%tqu] hat oder weniger als x_moves
    Halbzüge davor enthält.
    """
    if x_moves < 1:
        return None
    nodes: list[chess.pgn.GameNode] = []
    node = original_game
    while True:
        nodes.append(node)
        if '[%tqu' in (node.comment or ''):
            break
        if not node.variations:
            return None  # kein Trainingskommentar
        node = node.variations[0]

    plies_before = len(nodes) - 1  # Root hat keinen .move
    # Wenn nicht genug Vorlauf-Züge vorhanden, so viele wie möglich nehmen.
    x_moves = min(x_moves, plies_before)
    if x_moves < 1:
        return None

    blind_root = nodes[-1 - x_moves]
    blind_board = blind_root.board()

    blind_san: list[str] = []
    b = blind_board.copy()
    for nxt in nodes[-x_moves:]:
        if nxt.move is None:
            return None
        try:
            blind_san.append(b.san(nxt.move))
        except Exception:
            return None
        b.push(nxt.move)

    puzzle_game = _trim_to_training_position(original_game)
    return blind_board, blind_san, puzzle_game


def _format_blind_moves(start_board: chess.Board, san_list: list[str]) -> str:
    """Formatiert SAN-Liste als '15. Nf3 Nc6 16. Bb5' (mit korrekter Zugnummer)."""
    parts: list[str] = []
    move_num = start_board.fullmove_number
    is_white = start_board.turn == chess.WHITE
    for i, san in enumerate(san_list):
        if is_white:
            parts.append(f'{move_num}.')
            parts.append(san)
        else:
            if i == 0:
                parts.append(f'{move_num}...')
            parts.append(san)
            move_num += 1
        is_white = not is_white
    return ' '.join(parts)


def _flatten_null_move_variations(pgn_text: str) -> str:
    """Varianten mit Nullzuegen (--) in Kommentarbloecke umwandeln.

    python-chess kann Folgezuege nach ``--`` nicht validieren und verwirft
    sie samt Kommentaren.  Diese Funktion extrahiert den Kommentartext aus
    solchen Varianten und haengt ihn als ``{...}``-Block an die Hauptlinie,
    bevor python-chess den PGN-String parst.
    """
    result: list[str] = []
    i = 0
    n = len(pgn_text)
    while i < n:
        ch = pgn_text[i]
        if ch == '{':
            # Kommentarblock komplett uebernehmen
            end = pgn_text.find('}', i + 1)
            if end < 0:
                end = n - 1
            result.append(pgn_text[i:end + 1])
            i = end + 1
        elif ch == '(':
            # Variante finden: passende Klammer suchen
            j = i + 1
            depth = 1
            while j < n and depth > 0:
                c = pgn_text[j]
                if c == '{':
                    close = pgn_text.find('}', j + 1)
                    j = (close + 1) if close >= 0 else (n)
                elif c == '(':
                    depth += 1
                    j += 1
                elif c == ')':
                    depth -= 1
                    j += 1
                else:
                    j += 1
            var_content = pgn_text[i + 1:j - 1]
            # Pruefen ob -- ausserhalb von Kommentaren vorkommt
            without_comments = re.sub(r'\{[^}]*\}', '', var_content)
            if '--' in without_comments:
                # Alle Kommentartexte extrahieren und zusammenfuegen
                comments = re.findall(r'\{([^}]*)\}', var_content)
                merged = ' '.join(c.strip() for c in comments if c.strip())
                if merged:
                    result.append('{' + merged + '}')
            else:
                # Normale Variante: rekursiv vorverarbeiten
                inner = _flatten_null_move_variations(var_content)
                result.append('(' + inner + ')')
            i = j
        else:
            result.append(ch)
            i += 1
    return ''.join(result)


def _strip_pgn_annotations(text: str) -> str:
    """Entfernt grafische PGN-Annotationen aus einem exportierten PGN-String.

    Betroffen sind alle ``[%cmd ...]``-Blöcke, z.B.:
    - ``[%cal Gf4g5,...]``  — farbige Pfeile (colored arrows)
    - ``[%csl Ga2]``        — eingefärbte Felder (colored squares)
    - ``[%tqu ...]``        — ChessBase-Trainings-Quiz-Annotation

    Nach dem Entfernen werden leere Kommentarblöcke ``{  }`` und
    überflüssige Leerzeichen bereinigt.
    """
    text = _RE_ANNOTATION.sub('', text)
    text = _RE_EMPTY_COMMENT.sub('', text)
    text = _RE_MULTI_SPACE.sub(' ', text)
    return text.strip()


def _clean_pgn_for_lichess(pgn_text: str) -> str:
    """ChessBase-spezifische Annotationen entfernen, die Lichess nicht versteht.

    Stellt außerdem sicher, dass jedes PGN mit ``[FEN ...]`` auch ein
    ``[SetUp "1"]`` mitführt – PGN-Spec verlangt das, und Lichess
    interpretiert sonst die Startfarbe falsch (auto-played Black-Move,
    obwohl FEN „Black to move\" sagt).
    """
    pgn_text = _RE_TQU.sub('', pgn_text)
    pgn_text = _RE_EMPTY_COMMENT.sub('', pgn_text)
    if _RE_FEN_HEADER.search(pgn_text) and not _RE_SETUP_HEADER.search(pgn_text):
        pgn_text = _RE_FEN_LINE.sub(r'[SetUp "1"]\n\1', pgn_text, count=1)
    return pgn_text
