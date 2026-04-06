# ♟️ Schach-Bot für Discord

Ein Discord-Bot der täglich eine Partie aus einer [Lichess-Studie](https://lichess.org/study) postet – inklusive Brett-Bild und Kommentaren.

## Features

- Täglich automatisch ein Kapitel aus einer Lichess-Studie posten
- Partie auf Anfrage per Slash-Command abrufen
- Brett-Bild der Endstellung wird automatisch generiert
- Kommentare und Annotationen aus der Studie werden übernommen
- Kapitel-Zähler wird gespeichert, kein Kapitel wird doppelt gepostet

## Slash-Commands

| Command | Beschreibung |
|---------|-------------|
| `/partie` | Nächstes Kapitel sofort posten |
| `/studie` | Info: Kapitelanzahl und welches als nächstes kommt |
| `/reset` | Zähler zurücksetzen auf Kapitel 1 (nur Admins) |

## Voraussetzungen

- Python 3.10 oder neuer
- Ein Discord Bot Token ([Anleitung](https://discord.com/developers/applications))
- Eine öffentliche oder private Lichess-Studie

## Installation

**1. Repository klonen**
```bash
git clone https://github.com/DEINNAME/schach-bot.git
cd schach-bot
```

**2. Abhängigkeiten installieren**
```bash
pip install -r requirements.txt
```

**3. Konfiguration anlegen**
```bash
cp .env.example .env
```
Dann `.env` mit einem Texteditor öffnen und ausfüllen:

```env
DISCORD_TOKEN=dein_discord_bot_token
LICHESS_STUDY_ID=ndPgby4a
CHANNEL_ID=123456789012345678
POST_HOUR=8
POST_MINUTE=0
```

| Variable | Beschreibung |
|----------|-------------|
| `DISCORD_TOKEN` | Token vom [Discord Developer Portal](https://discord.com/developers/applications) |
| `LICHESS_STUDY_ID` | Die ID aus der Lichess-URL: `lichess.org/study/`**ndPgby4a** |
| `CHANNEL_ID` | Discord Channel-ID (Rechtsklick auf Channel → ID kopieren) |
| `POST_HOUR` | Stunde des täglichen Posts (UTC, 0–23) |
| `POST_MINUTE` | Minute des täglichen Posts (0–59) |

**4. Bot starten**
```bash
python bot.py
```

## Bot zu Discord Server hinzufügen

1. [Discord Developer Portal](https://discord.com/developers/applications) → deine App → **OAuth2 → URL Generator**
2. Scopes: `bot` + `applications.commands`
3. Bot Permissions: `Send Messages`, `Embed Links`, `Attach Files`
4. Generierten Link im Browser öffnen und Server auswählen

## Lichess-Studie einrichten

Jedes **Kapitel** der Studie entspricht einer Partie. Der Bot geht die Kapitel der Reihe nach durch und startet von vorne wenn alle gepostet wurden.

Die Studie-ID findest du in der URL:
```
https://lichess.org/study/ndPgby4a
                          ^^^^^^^^
                          Study-ID
```

## Projektstruktur

```
schach-bot/
├── bot.py            # Hauptdatei
├── requirements.txt  # Python-Abhängigkeiten
├── .env.example      # Konfigurationsvorlage
├── .env              # Deine Konfiguration (wird nicht ins Repo hochgeladen)
└── state.json        # Kapitel-Fortschritt (wird automatisch erstellt)
```
