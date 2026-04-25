# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python bot.py

# Run trim-snapshot tests
python tests/test_trim.py
```

## Configuration

Copy `.env.example` to `.env` and fill in:
- `DISCORD_TOKEN` – Discord bot token
- `LICHESS_TOKEN` – Lichess API token (study:write scope)
- `CHANNEL_ID` – Discord channel for daily posts
- `POST_HOUR` / `POST_MINUTE` – Daily post time (UTC)
- `BOOKS_DIR` – Directory containing PGN files (default: `books/`)

Runtime state lives in `config/` (gitignored, auto-created).

## Architecture

| Package / File | Role |
|----------------|------|
| `bot.py` | Main entry, events, /help, /version, /stats, /announce, /daily, daily task |
| `puzzle/` | Package: `legacy.py` (implementation), `buttons.py` (Button-View), `__init__.py` (public API) |
| `commands/` | Slash-Commands: `elo.py`, `reminder.py`, `resourcen.py`, `youtube.py`, `release_notes.py`, `test.py`, `blind.py` |
| `core/` | Shared utilities: `paths.py`, `stats.py`, `version.py`, `log_setup.py`, `dm_log.py`, `event_log.py`, `json_store.py` |
| `library.py` | Books library (/bibliothek, /tag, /autor, /reindex) |
| `books/` | PGN files + `books.json` metadata |
| `assets/` | Bot icons |
| `tests/` | Trim-snapshot regression tests |

### Key patterns

- **Board rendering**: Lichess cburnett SVG pieces via `svglib`/`reportlab`, rendered onto a Pillow canvas.
- **Atomic JSON persistence** (`core/json_store.py`): Thread-safe read/write/update with per-file locks and `tempfile` → `os.replace`.
- **In-memory caches**: Ignore lists, chapter ignores, books config, puzzle lines (with Pickle disk cache). Invalidated on write or via `/reindex`.
- **Button reactions** (`puzzle/buttons.py`): `PuzzleView` with mutex-paired buttons. Clicks defer immediately, side-effects run as background tasks.

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
