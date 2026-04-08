# ♟️ Chess Bot for Discord

A Discord bot with two daily chess features:

1. **Daily game** — posts a chapter from a [Lichess study](https://lichess.org/study) with board image and annotations
2. **Daily puzzle** — picks a random position from local PGN books, uploads it to Lichess as an interactive gamebook study, and posts a Discord thread with board image and link

## Features

- Daily chapter post from a Lichess study (board image + embed)
- Daily puzzle from local PGN files (Chessable / piratechess format)
  - Trims the game to the `[%tqu]` training position automatically
  - Creates a new Lichess study with two chapters:
    - **Chapter 1** — Gamebook starting at the training position (interactive quiz)
    - **Chapter 2** — Complete original game for context
  - Posts a Discord thread with the board image and a clickable Lichess link
- No chapter is posted twice (progress tracked in `state.json` / `puzzle_state.json`)
- Board images rendered with the Lichess cburnett piece set
- Rotating log file (`bot.log`, max 1 MB, 5 backups)

## Slash Commands

| Command | Description |
|---------|-------------|
| `/partie` | Post the next chapter from the Lichess study immediately |
| `/studie` | Show study info: total chapters and which comes next |
| `/puzzle` | Post a random puzzle immediately |
| `/reset` | Reset the chapter counter to 1 (admins only) |

## Requirements

- Python 3.10 or newer
- A Discord bot token ([guide](https://discord.com/developers/applications))
- A public or unlisted Lichess study for the daily game
- A Lichess OAuth token with `study:write` scope for puzzle upload

## Installation

**1. Clone the repository**
```bash
git clone https://github.com/YOURNAME/schach-bot.git
cd schach-bot
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Create configuration**
```bash
cp .env.example .env
```
Open `.env` in a text editor and fill in the values (see table below).

**4. Add PGN books** *(for the puzzle feature)*

Place one or more `.pgn` files in the `books/` folder. The bot expects Chessable/piratechess-style PGN with `[%tqu]` training annotations. Each annotated position becomes a puzzle candidate.

**5. Run the bot**
```bash
python bot.py
```

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | Yes | Token from the [Discord Developer Portal](https://discord.com/developers/applications) |
| `LICHESS_STUDY_ID` | Yes | Study ID from `lichess.org/study/`**ID** |
| `CHANNEL_ID` | Yes | Discord channel for daily posts (right-click → Copy ID) |
| `POST_HOUR` | Yes | Hour of the daily game post (UTC, 0–23) |
| `POST_MINUTE` | Yes | Minute of the daily game post (0–59) |
| `LICHESS_TOKEN` | Yes* | OAuth token with `study:write` scope — required for puzzle upload. Create at [lichess.org/account/oauth/token](https://lichess.org/account/oauth/token) |
| `BOOKS_DIR` | No | Folder with PGN files (default: `books`) |
| `PUZZLE_HOUR` | No | Hour of the daily puzzle post (UTC, default: `9`) |
| `PUZZLE_MINUTE` | No | Minute of the daily puzzle post (default: `0`) |

*Without `LICHESS_TOKEN` the puzzle falls back to a simple game import (no interactive quiz).

## Puzzle PGN Format

The bot reads `.pgn` files where training positions are marked with a `[%tqu]` comment:

```pgn
[White "Anastasia's Mate"]
[FEN "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"]

1. d4 d5 ... 26. Rb4 Qd8 {[%tqu "En","find the move","","","c2h7","",10]}
27. Qxh7+ Kxh7 28. Rh4# *
```

The bot locates the first `[%tqu]` annotation in each game, sets the FEN of that position as the gamebook starting point, and uploads all subsequent moves as the interactive solution.

## Adding the Bot to a Discord Server

1. [Discord Developer Portal](https://discord.com/developers/applications) → your app → **OAuth2 → URL Generator**
2. Scopes: `bot` + `applications.commands`
3. Bot Permissions (select all of the following):

| Permission | Required for |
|------------|-------------|
| `Send Messages` | Posting daily game and puzzle |
| `Embed Links` | Rich embeds with board image and Lichess link |
| `Attach Files` | Board image upload |
| `Create Public Threads` | Daily puzzle thread (current) |
| `Create Private Threads` | Planned: personal training threads |
| `Send Messages in Threads` | Posting inside threads |
| `Manage Threads` | Archiving / closing threads |
| `Send TTS Messages` | — |

> **Note on DMs:** Sending direct messages to users requires no extra bot permission, but users must have *"Allow direct messages from server members"* enabled in their Discord privacy settings.

4. Open the generated URL and select your server

## Roadmap

Planned extensions:

- **Public training threads** — one thread per puzzle where all server members can discuss moves and post solutions
- **Private training threads** — per-user threads visible only to the bot and that user, for personalised training feedback without spoiling the solution for others
- **Direct messages (DMs)** — send a daily puzzle or a personalised hint directly to subscribed users; users can opt in/out via slash command

## Testing the Puzzle Feature

Without starting the full bot:

```bash
python test_puzzle.py
```

This picks a random line, uploads it to Lichess, and prints the study URL and a validation summary.

## Project Structure

```
schach-bot/
├── bot.py              # All bot logic
├── test_puzzle.py      # Standalone puzzle upload test
├── requirements.txt    # Python dependencies
├── .env.example        # Configuration template
├── .env                # Your configuration (not committed)
├── books/              # PGN files for puzzles (not committed)
├── state.json          # Daily game progress (auto-created)
├── puzzle_state.json   # Puzzle progress (auto-created)
└── bot.log             # Rotating log file (auto-created)
```
