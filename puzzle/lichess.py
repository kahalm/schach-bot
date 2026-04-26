"""Lichess-API: Upload, Rate-Limiting, Study-Management."""

import io
import logging
import os
import time as _time_mod
from datetime import date as _date, datetime as _datetime, timezone as _tz

import chess
import chess.pgn
import requests

from core.json_store import atomic_read, atomic_write
from puzzle.processing import _clean_pgn_for_lichess
from puzzle.state import LICHESS_COOLDOWN_FILE, PUZZLE_STUDY_ID

log = logging.getLogger('schach-bot')

# --- Konstanten ---
_LICHESS_STUDY_NAME_MAX = 100
_LICHESS_CHAPTER_NAME_MAX = 70
LICHESS_API_TIMEOUT = 15
LICHESS_TOKEN = os.getenv('LICHESS_TOKEN', '')

_LICHESS_COOLDOWN_SECS = 3600  # 1 Stunde


def _auth_headers() -> dict[str, str]:
    """Gibt Auth-Header fuer Lichess-API zurueck (leer wenn kein Token)."""
    return {'Authorization': f'Bearer {LICHESS_TOKEN}'} if LICHESS_TOKEN else {}


def _extract_study_id(url: str) -> str | None:
    """Extrahiert die Studien-ID aus einer Lichess-URL."""
    if not url:
        return None
    parts = url.rstrip('/').split('/')
    if 'study' in parts:
        sidx = parts.index('study')
        sid = parts[sidx + 1] if sidx + 1 < len(parts) else ''
        return sid or None
    return None


def _export_pgn_for_lichess(game: chess.pgn.Game, headers=True,
                             variations=True, comments=True) -> str:
    """Exportiert ein Game als PGN und bereinigt es für Lichess."""
    exp = chess.pgn.StringExporter(
        headers=headers, variations=variations, comments=comments)
    return _clean_pgn_for_lichess(game.accept(exp))


class LichessRateLimitError(Exception):
    pass


def _lichess_cooldown_until() -> float:
    """Liest den gespeicherten Cooldown-Zeitstempel (Unix-Zeit). 0 = kein Cooldown."""
    try:
        data = atomic_read(LICHESS_COOLDOWN_FILE)
        return float(data.get('until', 0))
    except (ValueError, TypeError, AttributeError):
        return 0.0


def _lichess_rate_limited() -> bool:
    """True wenn Lichess gerade im Rate-Limit-Cooldown ist."""
    return _time_mod.time() < _lichess_cooldown_until()


def _lichess_set_cooldown(retry_after: int | None = None):
    """Setzt den Cooldown-Zeitstempel und schreibt ihn auf Disk."""
    secs  = retry_after if retry_after and retry_after > 0 else _LICHESS_COOLDOWN_SECS
    until = _time_mod.time() + secs
    atomic_write(LICHESS_COOLDOWN_FILE, {'until': until})
    log.warning('Lichess 429 – Cooldown bis %s UTC gesetzt (%ds).',
                _datetime.fromtimestamp(until, tz=_tz.utc).strftime('%H:%M'), secs)


def _lichess_request(method: str, url: str, **kwargs):
    """Lichess-API-Request. Bei 429 wird ein persistenter Cooldown gesetzt."""
    resp = requests.request(method, url, **kwargs)
    if resp.status_code == 429:
        try:
            retry_after = int(resp.headers.get('Retry-After', 0))
        except (ValueError, TypeError):
            retry_after = 0
        _lichess_set_cooldown(retry_after or None)
        raise LichessRateLimitError()
    return resp


def upload_to_lichess(game: chess.pgn.Game,
                      context_game: chess.pgn.Game | None = None,
                      reuse_study_id: str | None = None,
                      _depth: int = 0) -> str | None:
    """Neue Lichess-Studie anlegen, PGN importieren und Kapitel-URL zurückgeben."""
    if _lichess_rate_limited():
        remaining = int(_lichess_cooldown_until() - _time_mod.time())
        log.info('Lichess-Upload übersprungen (Cooldown noch %ds).', remaining)
        return None
    try:
        pgn_text = _export_pgn_for_lichess(game, comments=False)
    except Exception as e:
        log.error('PGN-Export fehlgeschlagen: %s', e)
        return None

    h = dict(game.headers)
    line_name  = h.get('White', h.get('Event', 'Puzzle'))
    event_name = h.get('Event', 'Puzzle')
    orientation = 'black' if game.board().turn == chess.BLACK else 'white'
    today      = _date.today().strftime('%d.%m.%Y')
    study_name = f'{event_name} – {today}'
    if len(study_name) > _LICHESS_STUDY_NAME_MAX:
        study_name = study_name[:_LICHESS_STUDY_NAME_MAX - 3] + '...'

    context_pgn = None
    context_name = None
    if context_game is not None:
        try:
            context_pgn = _export_pgn_for_lichess(context_game)
            ch = dict(context_game.headers)
            ctx_title = ch.get('White', ch.get('Event', 'Partie'))
            if len(ctx_title) > _LICHESS_CHAPTER_NAME_MAX:
                ctx_title = ctx_title[:_LICHESS_CHAPTER_NAME_MAX - 3] + '...'
            context_name = f'Partie: {ctx_title}'
        except Exception as e:
            log.warning('Kontext-PGN-Export fehlgeschlagen: %s', e)
            context_pgn = None

    auth = _auth_headers()

    if LICHESS_TOKEN:
        try:
            if reuse_study_id or PUZZLE_STUDY_ID:
                study_id = reuse_study_id or PUZZLE_STUDY_ID
                default_chapter_id = ''
            else:
                r = _lichess_request(
                    'POST', 'https://lichess.org/api/study',
                    data={
                        'name':       study_name,
                        'visibility': 'unlisted',
                        'computer':   'everyone',
                        'explorer':   'everyone',
                        'cloneable':  'everyone',
                        'shareable':  'everyone',
                        'chat':       'everyone',
                    },
                    headers=auth,
                    timeout=LICHESS_API_TIMEOUT,
                )
                r.raise_for_status()
                study_id = r.json().get('id', '')
                pgn_resp = _lichess_request(
                    'GET', f'https://lichess.org/api/study/{study_id}.pgn',
                    headers=auth,
                    timeout=LICHESS_API_TIMEOUT,
                )
                default_game = chess.pgn.read_game(io.StringIO(pgn_resp.text))
                if default_game:
                    chapter_url_hdr = default_game.headers.get('ChapterURL', '')
                    default_chapter_id = chapter_url_hdr.rstrip('/').split('/')[-1]
                    log.info('Leeres Auto-Kapitel: %s', default_chapter_id)
                else:
                    default_chapter_id = ''

            if study_id:
                r2 = _lichess_request(
                    'POST', f'https://lichess.org/api/study/{study_id}/import-pgn',
                    data={'pgn': pgn_text, 'name': line_name, 'mode': 'gamebook',
                          'orientation': orientation},
                    headers=auth,
                    timeout=LICHESS_API_TIMEOUT,
                )
                r2.raise_for_status()
                chapters = r2.json().get('chapters', [])
                chapter_id = chapters[-1].get('id', '') if chapters else ''
                log.info('Gamebook-Kapitel importiert: %s (chapter_id=%s)', line_name, chapter_id)

                if not chapter_id and reuse_study_id and _depth < 1:
                    log.info('Studie %s voll – lege neue an.', reuse_study_id)
                    return upload_to_lichess(game, context_game=context_game,
                                            reuse_study_id=None, _depth=_depth + 1)

                if context_pgn:
                    r3 = _lichess_request(
                        'POST', f'https://lichess.org/api/study/{study_id}/import-pgn',
                        data={'pgn': context_pgn, 'name': context_name, 'mode': 'normal'},
                        headers=auth,
                        timeout=LICHESS_API_TIMEOUT,
                    )
                    if r3.status_code == 200:
                        log.info('Kontext-Kapitel importiert: %s', context_name)
                    else:
                        log.warning('Kontext-Kapitel Import HTTP %s', r3.status_code)

                if default_chapter_id:
                    rd = _lichess_request(
                        'DELETE', f'https://lichess.org/api/study/{study_id}/{default_chapter_id}',
                        headers=auth,
                        timeout=LICHESS_API_TIMEOUT,
                    )
                    log.info('Auto-Kapitel geloescht: HTTP %s', rd.status_code)

                if chapter_id:
                    return f'https://lichess.org/study/{study_id}/{chapter_id}'
                return f'https://lichess.org/study/{study_id}'
        except LichessRateLimitError:
            return None
        except Exception as e:
            log.error('Lichess-Study-Upload fehlgeschlagen: %s', e)

    # Fallback: oeffentlicher Import (kein Study, kein Gamebook-Modus)
    log.warning('Fallback auf oeffentlichen /api/import (kein Token oder Study-Fehler).')
    if _lichess_rate_limited():
        return None
    try:
        resp = _lichess_request(
            'POST', 'https://lichess.org/api/import',
            data={'pgn': pgn_text},
            headers=auth,
            timeout=LICHESS_API_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get('url')
    except Exception as e:
        log.error('Lichess-Upload fehlgeschlagen: %s', e)
        return None


def upload_many_to_lichess(
    puzzles: list[tuple[chess.pgn.Game, chess.pgn.Game | None]],
    reuse_study_id: str | None = None,
) -> list[str]:
    """Mehrere Puzzles als Gamebook-Kapitel in eine gemeinsame Lichess-Studie laden."""
    if _lichess_rate_limited():
        remaining = int(_lichess_cooldown_until() - _time_mod.time())
        log.info('Lichess-Multi-Upload übersprungen (Cooldown noch %ds).', remaining)
        return []
    if not puzzles:
        return []
    if len(puzzles) == 1:
        u = upload_to_lichess(puzzles[0][0], context_game=puzzles[0][1], reuse_study_id=reuse_study_id)
        return [u] if u else []
    if not LICHESS_TOKEN:
        u = upload_to_lichess(puzzles[0][0], context_game=puzzles[0][1], reuse_study_id=reuse_study_id)
        return [u] if u else []

    auth = _auth_headers()

    try:
        if reuse_study_id:
            study_id = reuse_study_id
            default_chapter_id = ''
        else:
            today      = _date.today().strftime('%d.%m.%Y')
            study_name = f'Puzzles – {today}'
            r = _lichess_request(
                'POST', 'https://lichess.org/api/study',
                data={'name': study_name, 'visibility': 'unlisted', 'computer': 'everyone',
                      'explorer': 'everyone', 'cloneable': 'everyone',
                      'shareable': 'everyone', 'chat': 'everyone'},
                headers=auth, timeout=LICHESS_API_TIMEOUT,
            )
            r.raise_for_status()
            study_id = r.json().get('id', '')
            if not study_id:
                return []

            pgn_resp = _lichess_request(
                'GET', f'https://lichess.org/api/study/{study_id}.pgn',
                headers=auth, timeout=LICHESS_API_TIMEOUT,
            )
            default_chapter_id = ''
            if pgn_resp.status_code == 200:
                dg = chess.pgn.read_game(io.StringIO(pgn_resp.text))
                if dg:
                    default_chapter_id = dg.headers.get('ChapterURL', '').rstrip('/').split('/')[-1]

        chapter_urls: list[str] = []
        for idx, (game, context) in enumerate(puzzles):
            try:
                pgn  = _export_pgn_for_lichess(game)
                h    = dict(game.headers)
                name = h.get('White', h.get('Event', 'Puzzle'))[:_LICHESS_CHAPTER_NAME_MAX]
                ori  = 'black' if game.board().turn == chess.BLACK else 'white'
                r_ch = _lichess_request(
                    'POST', f'https://lichess.org/api/study/{study_id}/import-pgn',
                    data={'pgn': pgn, 'name': name, 'mode': 'gamebook',
                          'orientation': ori},
                    headers=auth, timeout=LICHESS_API_TIMEOUT,
                )
                r_ch.raise_for_status()
                chs = r_ch.json().get('chapters', [])
                ch_id = chs[-1].get('id', '') if chs else ''
                log.info('Gamebook-Kapitel importiert: %s (chapter_id=%s)', name, ch_id)

                if not ch_id and reuse_study_id:
                    remaining = puzzles[idx:]
                    log.info('Studie %s voll – lege neue an fuer %d verbleibende Kapitel.',
                             reuse_study_id, len(remaining))
                    return chapter_urls + upload_many_to_lichess(remaining, reuse_study_id=None)

                if ch_id:
                    chapter_urls.append(f'https://lichess.org/study/{study_id}/{ch_id}')
                else:
                    chapter_urls.append(f'https://lichess.org/study/{study_id}')

                if context is not None:
                    ctx_pgn = _export_pgn_for_lichess(context)
                    ch      = dict(context.headers)
                    ctx_name = f'Partie: {ch.get("White", "Partie")[:64]}'
                    _lichess_request(
                        'POST', f'https://lichess.org/api/study/{study_id}/import-pgn',
                        data={'pgn': ctx_pgn, 'name': ctx_name, 'mode': 'normal'},
                        headers=auth, timeout=LICHESS_API_TIMEOUT,
                    )
                    log.info('Kontext-Kapitel importiert: %s', ctx_name)
            except LichessRateLimitError:
                raise
            except Exception as e:
                log.warning('Kapitel-Import übersprungen: %s', e)
                chapter_urls.append('')
            _time_mod.sleep(1)

        if default_chapter_id:
            _lichess_request(
                'DELETE', f'https://lichess.org/api/study/{study_id}/{default_chapter_id}',
                headers=auth, timeout=LICHESS_API_TIMEOUT,
            )

        return chapter_urls
    except LichessRateLimitError:
        return []
    except Exception as e:
        log.error('Multi-Upload fehlgeschlagen: %s', e)
        return []
