"""Standalone-Regressionstest fuers Board-Rendering mit ECHTEN Libraries.

Ausfuehren: ``python tests/test_rendering.py``

Wird auch im Dockerfile als Build-Smoke-Test aufgerufen → ein Image ohne
funktionierendes renderPM-Backend (siehe unten) faellt schon beim Build durch,
statt spaeter still „ohne Brett" zu posten.

NICHT Teil von ``test_commands.py``: dessen ``test_helpers`` stubbt
``svglib``/``reportlab``/``requests`` per ``sys.modules`` aus (schnelle
Command-Tests ohne schwere Render-Deps) — echtes Rendering ist dort unmoeglich.
Daher laedt dieser Test ``puzzle/rendering.py`` direkt (umgeht das Package-
``__init__``, das ``discord`` zieht) und nutzt die real installierten Libs.

Hintergrund: Ein frischer Image-Build zog ungepinnt eine reportlab-Variante ohne
gebuendelten C-Rasterizer; das renderPM-Backend ``rlPyCairo`` fehlte →
``renderPM.drawToFile`` warf ``cannot import desired renderPM backend rlPyCairo``,
``safe_render_board`` verschluckte es still → Tagespuzzle ohne Brett.
"""

import importlib.util
import os
import sys

import chess

_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
# Stellung des Vorfall-Tagespuzzles (Schwarz am Zug) + Grundstellung.
_FENS = [
    '2r1k3/pp3p2/3p2p1/4b3/3pP1q1/1Q4Nr/PPPR1P1P/4K2R b K - 0 1',
    chess.STARTING_FEN,
]


def _load_rendering():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        'puzzle', 'rendering.py')
    spec = importlib.util.spec_from_file_location('rendering', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run() -> int:
    r = _load_rendering()
    failed = 0
    for fen in _FENS:
        try:
            data = r._render_board(chess.Board(fen)).getvalue()
        except Exception as e:  # noqa: BLE001 — Test soll JEDE Render-Ursache fangen
            print(f'  FAIL render {fen!r}: {type(e).__name__}: {e}')
            failed += 1
            continue
        if data[:8] != _PNG_MAGIC:
            print(f'  FAIL kein PNG {fen!r}: head={data[:8]!r}')
            failed += 1
        elif len(data) <= 1024:
            print(f'  FAIL PNG zu klein {fen!r}: {len(data)} bytes')
            failed += 1
        else:
            print(f'  OK   {len(data)} bytes  {fen}')
    return failed


if __name__ == '__main__':
    print('[rendering] echtes _render_board (renderPM-Backend)')
    rc = run()
    if rc:
        print(f'{rc} FAILED')
        sys.exit(1)
    print('Alle Render-Tests OK.')
