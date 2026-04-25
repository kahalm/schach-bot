# ♟️ Schach-Bot für Discord

Ein Discord-Bot für tägliche Schach-Puzzles aus Chessable-PGN-Büchern.

## Features

- **Tägliches Puzzle** — wählt zufällig eine Position aus lokalen PGN-Büchern, lädt sie als interaktives Lichess-Gamebook hoch, postet einen Discord-Thread mit Bretbild und Link
- **Gamebook-Modus** — Kapitel 1: interaktives Quiz ab Trainingsposition; Kapitel 2: vollständiges Originalspiel
- `[%tqu]`-Filterung — nur Positionen mit Trainingsannotation werden als Puzzle genutzt
- Board-Rendering mit dem Lichess cburnett-Figurensatz (Pillow, kein Cairo nötig)
- Kein Puzzle wird zweimal gepostet (Fortschritt in `config/puzzle_state.json`)
- Rotating Log (`bot.log`, max 1 MB, 5 Backups)
- Alle ausgehenden DMs werden per User in `config/dm_log.json` mitgeschrieben

## Slash-Befehle

### Puzzles
| Befehl | Beschreibung |
|--------|-------------|
| `/puzzle [anzahl] [buch]` | Zufälliges Puzzle(s) per DM (1–20, optional Buchfilter) |
| `/blind [moves] [anzahl] [buch]` | Blind-Puzzle: X Halbzüge vor der Trainingsposition |
| `/endless [buch]` | Endlos-Modus: nach jeder ✅/❌ kommt sofort das nächste Puzzle |
| `/kurs` | Alle Puzzle-Bücher mit Fortschritt anzeigen |
| `/train [buch]` | Buch für sequentielles Training wählen (`/train 0` zum Stoppen) |
| `/next [anzahl]` | Nächste Linie(n) aus dem Trainingsbuch per DM senden |
| `/reminder [hours] [puzzle_count] [buch]` | Wiederkehrende Puzzle-DMs (`hours:0` zum Stoppen) |

### Bibliothek
| Befehl | Beschreibung |
|--------|-------------|
| `/bibliothek <suche>` | Schachbuch-Bibliothek durchsuchen |
| `/autor <autor>` | Alle Bücher eines Autors |
| `/tag <tag>` | Bücher nach Tag filtern |

### Sonstiges
| Befehl | Beschreibung |
|--------|-------------|
| `/resourcen [url] [beschreibung]` | Lernressourcen anzeigen oder hinzufügen |
| `/youtube [url] [beschreibung]` | YouTube-Links anzeigen oder hinzufügen |
| `/elo [wert]` | Eigene Elo angeben oder anzeigen |
| `/version` | Bot-Version und Uptime |
| `/release-notes [version] [anzahl]` | Changelog anzeigen |
| `/help` | Alle Befehle anzeigen |

### Admin-only
| Befehl | Beschreibung |
|--------|-------------|
| `/daily` | Tägliches Puzzle manuell auslösen |
| `/stats` | Nutzungsstatistiken aller User |
| `/announce <user>` | Begrüßungsnachricht per DM an einen User senden |
| `/ignore_kapitel [buch] [kapitel] [aktion]` | Kapitel aus dem Puzzle-Pool ausschließen |
| `/test` | Snapshot-Regressionstests ausführen |

## Projektstruktur

```
schach-bot/
├── bot.py                  # Einstiegspunkt, Events, /help, /version, /stats, Daily-Task
├── puzzle/
│   ├── legacy.py           # Puzzle-Logik (Trim, Render, Upload, Post, Slash-Commands)
│   ├── buttons.py          # Button-View (✅ ❌ 👍 👎 🚮)
│   └── __init__.py
├── commands/
│   ├── blind.py            # /blind
│   ├── elo.py              # /elo
│   ├── reminder.py         # /reminder
│   ├── release_notes.py    # /release-notes
│   ├── resourcen.py        # /resourcen
│   ├── test.py             # /test (Snapshot-Tests)
│   └── youtube.py          # /youtube
├── core/
│   ├── dm_log.py           # DM-Logging (config/dm_log.json)
│   ├── log_setup.py        # Rotating Log + stderr-Filter
│   ├── paths.py            # CONFIG_DIR-Konstante
│   ├── stats.py            # User-Statistiken
│   └── version.py          # VERSION, START_TIME
├── library.py              # /bibliothek, /autor, /tag
├── books/                  # PGN-Dateien + books.json (Metadaten)
├── assets/                 # Figur-Icons (cburnett)
├── tests/                  # test_trim.py, trim_snapshots.json
├── requirements.txt
├── .env.example
├── CHANGELOG.md
└── config/                 # Runtime-State (gitignored, auto-erstellt)
    ├── puzzle_state.json
    ├── reminder.json
    ├── dm_log.json
    └── ...
```

## Installation

**1. Repository klonen**
```bash
git clone https://github.com/kahalm/schach-bot.git
cd schach-bot
```

**2. Abhängigkeiten installieren**

Linux (System-Bibliotheken):
```bash
sudo apt install python3-venv libcairo2-dev pkg-config python3-dev -y
```

Python-Pakete:
```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**3. `.env` anlegen**
```env
DISCORD_TOKEN=your_discord_bot_token
CHANNEL_ID=123456789012345678
PUZZLE_HOUR=9
PUZZLE_MINUTE=0
LICHESS_TOKEN=your_lichess_token   # OAuth-Token mit study:write
```

**4. PGN-Bücher hinzufügen**

Chessable-PGN-Dateien in `books/` legen. Die Datei `books/books.json` steuert Metadaten und ob ein Buch im Daily-Pool ist (`random: true/false`).

**5. Bot starten**
```bash
python bot.py
```

## Konfiguration (`.env`)

| Variable | Pflicht | Beschreibung |
|----------|---------|-------------|
| `DISCORD_TOKEN` | Ja | Token aus dem [Discord Developer Portal](https://discord.com/developers/applications) |
| `CHANNEL_ID` | Ja | Discord-Channel für tägliche Posts |
| `PUZZLE_HOUR` | Nein | Stunde des täglichen Puzzles (UTC, Standard: 9) |
| `PUZZLE_MINUTE` | Nein | Minute des täglichen Puzzles (Standard: 0) |
| `LICHESS_TOKEN` | Ja* | OAuth-Token mit `study:write` für Puzzle-Upload |
| `BOOKS_DIR` | Nein | Ordner mit PGN-Dateien (Standard: `books`) |

*Ohne `LICHESS_TOKEN` kein interaktives Lichess-Gamebook.

## Als systemd-Service (Linux)

```ini
[Unit]
Description=Schach Discord Bot
After=network.target

[Service]
WorkingDirectory=/path/to/schach-bot
ExecStart=/path/to/schach-bot/venv/bin/python bot.py
Restart=on-failure
User=youruser

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now schach-bot
```

## Tests

```bash
python tests/test_trim.py
```

Prüft Trim-Snapshots für alle PGN-Bücher. Snapshots in `tests/trim_snapshots.json` — nie automatisch aktualisieren, immer manuell prüfen.

## Bot-Berechtigungen (Discord)

Scopes: `bot` + `applications.commands`

| Berechtigung | Wofür |
|-------------|-------|
| Send Messages | Tägliches Puzzle, Thread-Posts |
| Embed Links | Board-Embeds |
| Attach Files | Brett-Bild |
| Create Public Threads | Daily-Puzzle-Thread |
| Send Messages in Threads | Posts im Thread |
| Manage Threads | Thread-Archivierung |

> DMs: Nutzer müssen „Direktnachrichten von Servermitgliedern erlauben" aktiviert haben.
