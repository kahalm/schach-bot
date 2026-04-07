# ♟️ Chess Bot for Discord

A Discord bot that daily posts a game from a [Lichess study](https://lichess.org/study) — including a board image and annotations.

## Features

- Automatically posts one chapter from a Lichess study every day
- Fetch a game on demand via slash command
- Board image of the final position is generated automatically using the Lichess cburnett piece set
- Comments and annotations from the study are included
- Chapter progress is saved so no chapter is posted twice

## Slash Commands

| Command | Description |
|---------|-------------|
| `/partie` | Post the next chapter immediately |
| `/studie` | Show study info: total chapters and which comes next |
| `/reset` | Reset the counter to chapter 1 (admins only) |

## Requirements

- Python 3.10 or newer
- A Discord bot token ([guide](https://discord.com/developers/applications))
- A public or private Lichess study

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
Open `.env` in a text editor and fill in the values:

```env
DISCORD_TOKEN=your_discord_bot_token
LICHESS_STUDY_ID=ndPgby4a
CHANNEL_ID=123456789012345678
POST_HOUR=8
POST_MINUTE=0
```

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Token from the [Discord Developer Portal](https://discord.com/developers/applications) |
| `LICHESS_STUDY_ID` | The ID from the Lichess URL: `lichess.org/study/`**ndPgby4a** |
| `CHANNEL_ID` | Discord channel ID (right-click channel → Copy ID) |
| `POST_HOUR` | Hour of the daily post (UTC, 0–23) |
| `POST_MINUTE` | Minute of the daily post (0–59) |

**4. Run the bot**
```bash
python bot.py
```

## Adding the Bot to a Discord Server

1. [Discord Developer Portal](https://discord.com/developers/applications) → your app → **OAuth2 → URL Generator**
2. Scopes: `bot` + `applications.commands`
3. Bot Permissions: `Send Messages`, `Embed Links`, `Attach Files`
4. Open the generated link in your browser and select a server

## Setting Up a Lichess Study

Each **chapter** in the study corresponds to one game. The bot works through chapters in order and loops back to the beginning once all have been posted.

Find the study ID in the URL:
```
https://lichess.org/study/ndPgby4a
                          ^^^^^^^^
                          Study ID
```

## Project Structure

```
schach-bot/
├── bot.py            # Main file
├── requirements.txt  # Python dependencies
├── .env.example      # Configuration template
├── .env              # Your configuration (not committed)
└── state.json        # Chapter progress (auto-created)
```
