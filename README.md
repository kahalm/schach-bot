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

### Turniere & Schachrallye
| Befehl | Beschreibung |
|--------|-------------|
| `/turnier` | Kommende Turniere anzeigen |
| `/turnier_sub [tag]` | Turnier-Tag abonnieren (z.B. blitz, schnellschach, 960, jugend, senioren, klassisch) — ohne Tag: eigene Abos anzeigen |
| `/turnier_unsub <tag>` | Turnier-Tag-Abo abbestellen |
| `/schachrallye` | Kommende Schachrallye-Termine anzeigen |
| `/schachrallye_add <name> <datum>` | Rallye-Termin hinzufügen |
| `/schachrallye_del <nummer>` | Rallye-Termin löschen |
| `/schachrallye_sub [user]` | Rallye-Erinnerungen abonnieren (Ping + 7-Tage-Reminder) |
| `/schachrallye_unsub [user]` | Rallye-Erinnerungen abbestellen |

### Community
| Befehl | Beschreibung |
|--------|-------------|
| `/resourcen [url] [beschreibung]` | Lernressourcen anzeigen oder hinzufügen |
| `/youtube [url] [beschreibung]` | YouTube-Links anzeigen oder hinzufügen |
| `/wanted [feature]` | Feature-Wunsch einreichen oder Liste anzeigen |
| `/elo [wert]` | Eigene Elo angeben oder anzeigen |

### Info
| Befehl | Beschreibung |
|--------|-------------|
| `/version` | Bot-Version und Uptime |
| `/release-notes [version] [anzahl]` | Changelog anzeigen |
| `/help [bereich]` | Alle Befehle anzeigen (optional nach Bereich filtern) |

### Admin-only
| Befehl | Beschreibung |
|--------|-------------|
| `/daily` | Tägliches Puzzle manuell auslösen |
| `/turnier_parse` | Turniere von tirol.chess.at importieren |
| `/stats` | Nutzungsstatistiken aller User |
| `/announce <user>` | Begrüßungsnachricht per DM an einen User senden |
| `/greeted` | Bereits begrüßte User anzeigen |
| `/dm-log` | Ausgehende DMs anzeigen |
| `/ignore_kapitel [buch] [kapitel] [aktion]` | Kapitel aus dem Puzzle-Pool ausschließen |
| `/reindex` | Bibliothek-Index neu einlesen |
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
│   ├── schachrallye.py     # /schachrallye*, /turnier*, Turnier-Import
│   ├── test.py             # /test (Snapshot-Tests)
│   ├── wanted.py           # /wanted
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
├── tests/                  # test_trim.py, test_commands.py
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
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
| `PUZZLE_STUDY_ID` | Nein | Lichess-Studie für alle Puzzle-Kapitel (empfohlen) |
| `BOOKS_DIR` | Nein | Ordner mit PGN-Dateien (Standard: `books`) |
| `TOURNAMENT_CHANNEL_ID` | Nein | Channel für Turnier-Posts und Rallye-Erinnerungen (0 = deaktiviert) |
| `LIBRARY_INDEX` | Nein | Pfad zur `index.txt` für `/bibliothek` |

*Ohne `LICHESS_TOKEN` kein interaktives Lichess-Gamebook.

## Docker (empfohlen)

Der Bot läuft isoliert in einem Container — ideal wenn auf der VM noch andere Dienste laufen.

```bash
# .env anlegen (siehe .env.example)
cp .env.example .env
# Token, Channel-ID etc. eintragen

# Starten
docker compose up -d

# Logs verfolgen
docker compose logs -f

# Update deployen
git pull
docker compose down && docker compose up -d --build

# Stoppen
docker compose down
```

`config/` und `books/` werden als Volumes gemountet und bleiben beim Rebuild erhalten.
Ressourcen sind auf 512 MB RAM und 0.5 CPU begrenzt (anpassbar in `docker-compose.yml`).

## Als systemd-Service (Linux, ohne Docker)

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
python tests/test_trim.py       # 171 Snapshot-Tests (Trim-Regression)
python tests/test_commands.py   # 234 Command-Tests (alle Slash-Commands)
```

Snapshots in `tests/trim_snapshots.json` — nie automatisch aktualisieren, immer manuell prüfen.

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
