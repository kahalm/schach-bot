# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python bot.py

# Run tests
python tests/test_trim.py       # Trim-snapshot regression tests
python tests/test_commands.py    # Slash-command tests (all 27 commands)
```

## Configuration

Copy `.env.example` to `.env` and fill in:
- `DISCORD_TOKEN` – Discord bot token
- `LICHESS_TOKEN` – Lichess API token (study:write scope)
- `CHANNEL_ID` – Discord channel for daily posts
- `PUZZLE_HOUR` / `PUZZLE_MINUTE` – Daily post time (UTC)
- `BOOKS_DIR` – Directory containing PGN files (default: `books/`)

Runtime state lives in `config/` (gitignored, auto-created).

## Architecture

| Package / File | Role |
|----------------|------|
| `bot.py` | Main entry, events, /help, /version, /stats, /announce, /daily, daily task |
| `puzzle/` | Package: `commands.py`, `state.py`, `selection.py`, `processing.py`, `rendering.py`, `posting.py`, `lichess.py`, `embed.py`, `buttons.py`, `__init__.py` |
| `commands/` | Slash-Commands: `elo.py`, `reminder.py`, `resourcen.py`, `youtube.py`, `release_notes.py`, `test.py`, `blind.py`, `wanted.py`, `_collection.py` |
| `core/` | Shared utilities: `paths.py`, `stats.py`, `version.py`, `log_setup.py`, `dm_log.py`, `event_log.py`, `json_store.py` |
| `library.py` | Books library (/bibliothek, /tag, /autor, /reindex) |
| `books/` | PGN files + `books.json` metadata |
| `assets/` | Bot icons |
| `tests/` | `test_trim.py` (Snapshot-Regression), `test_commands.py` (Command-Tests) |

### Key patterns

- **Board rendering**: Lichess cburnett SVG pieces via `svglib`/`reportlab`, rendered onto a Pillow canvas.
- **Atomic JSON persistence** (`core/json_store.py`): Thread-safe read/write/update with per-file locks and `tempfile` → `os.replace`.
- **In-memory caches**: Ignore lists, chapter ignores, books config, puzzle lines (with Pickle disk cache). Invalidated on write or via `/reindex`.
- **Button reactions** (`puzzle/buttons.py`): `PuzzleView` with mutex-paired buttons. Clicks defer immediately, side-effects run as background tasks.

## Test-Regeln (PFLICHT!)

1. **Nach jeder Änderung** müssen ALLE Tests erfolgreich laufen:
   ```bash
   python tests/test_trim.py      # 171 Snapshot-Tests
   python tests/test_commands.py   # 131 Command-Tests
   ```
2. **Test-First**: Für jedes neue Feature ZUERST einen Test schreiben, dann die Implementierung.
3. **Bug-First-Test**: Wenn der User einen Bug meldet, ZUERST einen Test schreiben der den Fehler reproduziert (Test muss fehlschlagen), DANN den Bug fixen (Test muss bestehen). So wird sichergestellt, dass der Fehler nie wieder auftreten kann.

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
