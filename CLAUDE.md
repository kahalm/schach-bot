# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python bot.py
```

No test suite or linter is configured.

## Configuration

Copy `.env.example` to `.env` and fill in:
- `DISCORD_TOKEN` – Discord bot token
- `LICHESS_STUDY_ID` – ID from `lichess.org/study/<ID>`
- `CHANNEL_ID` – Discord channel for daily posts
- `POST_HOUR` / `POST_MINUTE` – Daily post time (UTC)

`state.json` is auto-created at runtime to track `chapter_index`.

## Architecture

Everything lives in a single file `bot.py`. Key sections:

- **State** (`load_state`/`save_state`): Persists `chapter_index` to `state.json`. The index wraps around when all chapters are exhausted.
- **Lichess API** (`fetch_all_chapters`, `parse_games`): Fetches all chapters of a study as a combined PGN via `https://lichess.org/api/study/{id}.pgn`, then parses them with `python-chess`.
- **Board rendering** (`board_image`): Pillow renderer using Unicode chess symbols (♔–♟) from the Windows `seguisym.ttf` (Segoe UI Symbol) font. Pieces are rendered with a halo/outline in the contrasting color for readability. Board includes coordinate labels (a–h, 1–8). No system Cairo or external SVG libs required.
- **Discord embed** (`build_embed`): Reads PGN headers (`ChapterName`, `StudyName`, `ChapterURL`, `Annotator`, `Result`) and the root comment for the embed fields.
- **Bot + slash commands**: Uses `discord.py` app commands (`/partie`, `/studie`, `/reset`). Commands are synced globally on `on_ready`. `/reset` is admin-only via `default_permissions`.
- **Daily task**: `@tasks.loop(time=...)` fires once per day at `POST_HOUR:POST_MINUTE` UTC.

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
