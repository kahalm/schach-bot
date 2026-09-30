# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Deployment-Regel (ABSOLUT PFLICHT!)

**Niemals auf Prod deployen ohne explizite Anweisung** — auch nicht im Auto-Mode, auch nicht nach einem erfolgreichen Build. Erst pushen/taggen, dann warten bis der User sagt "deploy".

## Commands

```bash
# Install dependencies (exakt aus dem Lock, wie Dockerfile und CI)
pip install --require-hashes -r requirements.lock

# Run the bot
python bot.py

# Run tests (the ONE test command — same as the CI gate in release.yml)
python tests/run_all.py          # every offline test file, each in its own process (-v = full output); test_trim.py only locally (needs gitignored books/*.pgn)
```

## Configuration

Copy `.env.example` to `.env` and fill in:
- `DISCORD_TOKEN` – Discord bot token
- `ROOKHUB_API_URL` – RookHub-API (intern, kein Token) – Quelle für Daily/Random/Blind-Puzzle; die Ergebnis-GETs (Löser, Wochenpost, Daily-Leaderboard, Hall of Fame) signiert der Bot mit `ROOKHUB_STATS_SECRET`
- `ROOKHUB_WEB_URL` – öffentliche RookHub-Frontend-URL für den anklickbaren Puzzle-Link
- `ROOKHUB_LINK_SECRET` – HMAC-Secret für die RookHub-Verknüpfung (`/link`, Begrüßungs-DM, private Puzzle-Links); MUSS == RookHubs `Discord__LinkSecret` sein, leer → Feature inaktiv
- `ROOKHUB_STATS_SECRET` – HMAC-Secret für den stats-basierten Motivations-DM (`/motivation`); liest den Trainings-/Puzzle-Fortschritt verknüpfter Spieler via `GET /api/bot/player-progress`; signiert außerdem die vier Ergebnis-GETs (`X-Bot-Timestamp` + `X-Bot-Signature` = `sha256=HMAC(secret, "<ts>.<pfad>")`), nur dann liefert RookHub Discord-ID/-Name der Löser; MUSS == RookHubs `SchachBot__StatsSecret` sein, leer → `/motivation` inaktiv und Namen statt @-Erwähnungen
- Platzhalter aus `.env.example` (`change_me…`/`your_…`) gelten bei `ROOKHUB_LINK_SECRET`, `ROOKHUB_STATS_SECRET` und `WEBHOOK_SECRET` wie leer: Feature aus + ERROR im Log beim Start (`core/secret_env.py`)
- `LICHESS_TOKEN` – nur noch für die `/test`-Diagnose / Cloud-Eval (nicht mehr fürs Posten)
- `CHANNEL_ID` – Discord channel for daily posts
- `PUZZLE_HOUR` / `PUZZLE_MINUTE` – Daily post time (UTC)
- `BOOKS_DIR` – Directory containing PGN files (default: `books/`) – für die lokalen Commands (/endless, /reminder, /ignore_kapitel, Chat-Werkzeug); deren `buch` ist der 1-basierte Index dieser alphabetischen Liste (Autocomplete zeigt die Namen), NICHT die RookHub-Buch-ID aus /kurs, die /puzzle nimmt
- `LIBRARY_ENFORCE_PD` – Gemeinfreiheits-Sperre der Bibliothek durchsetzen (`1`/`true`/`yes`/`on`). Default **aus**: das pro-Buch-Sidecar-Feld `publicDomainFrom` (ISO-Datum, ab wann gemeinfrei) wird gespeichert, sperrt aber nichts. Aktiviert → noch nicht freie Bücher werden in `/bibliothek` mit 🔒 markiert und nicht zum Download/SFTPGo freigegeben; solange eins gesperrt ist, gibt der Bot auch für freie Bücher > 8 MB keinen SFTPGo-Link aus (der Share deckt die ganze Bibliothek ab, `library._share_exposes_locked`). Muss in der Stack-Compose unter `environment:` stehen (kein `env_file`)

Runtime state lives in `config/` (gitignored, auto-created).

## Architecture

| Package / File | Role |
|----------------|------|
| `bot.py` | Main entry, events, /version, /stats, /announce, /daily, daily task |
| `puzzle/` | Package: `commands.py`, `state.py`, `selection.py`, `processing.py`, `rendering.py`, `posting.py` (inkl. `post_rookhub_puzzle`), `rookhub.py` (RookHub-Client), `daily_results.py` (Tagespuzzle-Solver-Anzeige: Poll + ✅-Reaction + Embed-Feld), `lichess.py` (nur Cloud-Eval/Diagnose), `embed.py`, `buttons.py`, `__init__.py` |
| `commands/` | Slash-Commands: `help.py` (/help, generiert aus den registrierten Befehlen; Bereich je Befehl per `extras={'help': …}`, `None` = ausgeblendet), `elo.py`, `reminder.py`, `resourcen.py`, `youtube.py`, `release_notes.py`, `test.py`, `blind.py`, `wanted.py`, `link.py` (RookHub-Verknüpfung), `motivation.py` (stats-basierter Motivations-DM, ersetzt den Wochenpost-Reminder), `wochenpost.py` (nur noch Channel-Posts), `_collection.py` |
| `core/` | Shared utilities: `paths.py`, `stats.py`, `version.py`, `log_setup.py`, `dm_log.py`, `event_log.py`, `json_store.py`, `command_log.py` (jeder Slash-Befehl → ES, Tag `command`), `discord_text.py` (RookHub-Anzeigenamen Markdown-sicher fuer Embeds), `secret_env.py` (geteilte Geheimnisse lesen, Platzhalter = leer) |
| `library.py` | Books library (/bibliothek, /tag, /autor, /reindex) |
| `books/` | PGN files + `books.json` metadata |
| `assets/` | Bot icons |
| `tests/` | `run_all.py` (Sammel-Runner = einziger Testbefehl), `test_trim.py` (Snapshot-Regression, nur lokal mit `books/*_firstkey.pgn`), `test_commands.py` (Command-Tests), weitere `test_*.py` |

### Key patterns

- **Board rendering**: Lichess cburnett SVG pieces via `svglib`/`reportlab`, rendered onto a Pillow canvas.
- **Atomic JSON persistence** (`core/json_store.py`): Thread-safe read/write/update with per-file locks and `tempfile` → `os.replace`.
- **In-memory caches**: Ignore lists, chapter ignores, books config, puzzle lines (with Pickle disk cache). Invalidated on write or via `/reindex`.
- **Button reactions** (`puzzle/buttons.py`): `PuzzleView` with mutex-paired buttons. Clicks defer immediately, side-effects run as background tasks.

## Test-Regeln (PFLICHT!)

1. **Nach jeder Änderung** müssen ALLE Tests erfolgreich laufen — einziger Testbefehl:
   ```bash
   python tests/run_all.py
   ```
   Er startet jede `tests/test_*.py` mit eigenem `__main__` (u. a. `test_trim.py`, `test_commands.py`
   mit allen `test_cmd_*`, `test_rendering.py`, `test_rookhub.py`, `test_discord_link.py`) in einem
   eigenen Prozess. Ausgenommen sind nur die Lichess-Netz-Tests (`NETWORK_TESTS` in `run_all.py`).
   Derselbe Befehl ist in `.github/workflows/release.yml` der Job `test`; ohne ihn wird kein
   `:dev`/`:latest`-Image gebaut. **`test_trim.py` läuft nur lokal** (`NEEDS_BOOKS` in `run_all.py`):
   Es liest die Snapshot-PGNs `books/*_firstkey.pgn`, und `books/*.pgn` ist gitignored. In einem
   sauberen Checkout, also auch im CI-Gate, fehlen sie; `run_all.py` meldet die Datei dann sichtbar
   als `SKIP` statt rot. Fehlen nur einzelne PGNs, läuft sie trotzdem und wird rot. Wer an
   `puzzle/processing.py` (Trimmen) arbeitet, muss sie also lokal mit den Büchern grün sehen.
   Neue Testdatei → eigenes `__main__` mit Exit-Code != 0 bei Fehler (oder als `test_cmd_*` in
   `test_commands.py` importieren); `tests/test_ci_gate.py` wacht darüber.
2. **Test-First**: Für jedes neue Feature ZUERST einen Test schreiben, dann die Implementierung.
3. **Bug-First-Test**: Wenn der User einen Bug meldet, ZUERST einen Test schreiben der den Fehler reproduziert (Test muss fehlschlagen), DANN den Bug fixen (Test muss bestehen). So wird sichergestellt, dass der Fehler nie wieder auftreten kann.

## Keine duplizierte Logik (PFLICHT!)

`/test` und andere Stellen, die produktive Abläufe simulieren, dürfen **keine eigene Kopie** der Logik enthalten. Stattdessen immer die existierenden Hilfsfunktionen aus dem jeweiligen Modul aufrufen (z.B. `wp._try_chat_spark()`, `wp._random_spruch()`). Wenn eine Funktion fehlt, zuerst im Originalmodul extrahieren, dann von `/test` aufrufen.

## Release-Regel (PFLICHT bei jedem Commit!)

Vor jedem `git commit` MÜSSEN diese beiden Dateien mitgeändert werden:

1. **`core/version.py`** – `VERSION` bumpen (bugfix bei Fix, minor bei Feature, major bei Breaking Change)
2. **`CHANGELOG.md`** – Neue Sektion `## [x.y.z] - YYYY-MM-DD` mit Added/Changed/Fixed (Keep-a-Changelog)

Beide Dateien gehören in denselben Commit – nie nachträglich! Kein Commit ohne Version-Bump + Changelog-Eintrag.

## Dependencies

| Package | Purpose |
|---------|---------|
| `discord.py` | Discord bot framework + slash commands |
| `python-chess` | PGN parsing and board representation |
| `Pillow` | Board image rendering |
| `requests` | Lichess API calls |
| `python-dotenv` | `.env` loading |
| `svglib` / `reportlab` | SVG → PNG conversion for chess pieces |

`requirements.txt` listet nur die direkten Abhängigkeiten (Untergrenzen) und ist die Eingabe für
`requirements.lock` (alle Pakete exakt gepinnt, mit Hashes). Dockerfile und CI installieren
ausschließlich den Lock mit `--require-hashes`; ein neues PyPI-Release kommt so nur per bewusstem
Commit ins Image. Lock neu erzeugen (pip-tools, Python 3.13):
`pip-compile --generate-hashes --allow-unsafe --strip-extras -o requirements.lock requirements.txt`
(einzelnes Paket anheben: zusätzlich `--upgrade-package <name>`), danach `python tests/run_all.py`.
`pip-audit` läuft in `release.yml` (Job `audit`) nur als Warnung. `tests/test_ci_gate.py` wacht über
Lock, Actions-SHAs und das mehrstufige Dockerfile (Laufzeit-Stage ohne Compiler/`-dev`-Pakete).
