# Schach-Bot fuer Discord

Discord-Bot fuer Schachtraining: taegliche Puzzles aus PGN-Buechern, Lichess-Integration, Turnierverwaltung, Wochenposts und KI-Chat.

Gebaut mit Python, `discord.py` und `python-chess`.

## Inhaltsverzeichnis

- [Installation](#installation)
- [Konfiguration](#konfiguration)
- [Docker](#docker)
- [Architektur](#architektur)
- [Commands](#commands)
- [Puzzle-System](#puzzle-system)
- [Turnier & Rallye](#turnier--rallye)
- [Wochenpost](#wochenpost)
- [KI-Chat](#ki-chat)
- [Bibliothek](#bibliothek)
- [Tests](#tests)
- [Release-Workflow](#release-workflow)
- [Bot-Berechtigungen](#bot-berechtigungen)

---

## Installation

```bash
git clone https://github.com/kahalm/schach-bot.git
cd schach-bot
```

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

`.env` anlegen und Bot starten:
```bash
cp .env.example .env
# Token, Channel-ID etc. eintragen
python bot.py
```

### Abhaengigkeiten

| Paket | Zweck |
|-------|-------|
| `discord.py` >=2.3 | Bot-Framework + Slash-Commands |
| `python-chess` >=1.10 | PGN-Parsing, Board-Repraesentation |
| `Pillow` >=10.0 | Board-Rendering (PNG) |
| `svglib` / `reportlab` | SVG-Figuren (cburnett) → PNG |
| `requests` >=2.31 | Lichess-API |
| `python-dotenv` >=1.0 | `.env`-Laden |
| `anthropic` >=0.40 | Claude-API (KI-Chat) |
| `tzdata` >=2024.1 | Zeitzonen (Europe/Vienna) |

---

## Konfiguration

Alle Einstellungen in `.env` (siehe `.env.example`):

| Variable | Pflicht | Beschreibung |
|----------|---------|-------------|
| `DISCORD_TOKEN` | ja | Bot-Token aus dem [Developer Portal](https://discord.com/developers/applications) |
| `CHANNEL_ID` | ja | Channel-ID fuer den taeglichen Puzzle-Post |
| `PUZZLE_HOUR` / `PUZZLE_MINUTE` | nein | Post-Uhrzeit in UTC (Standard: 9:00) |
| `BOOKS_DIR` | nein | PGN-Verzeichnis (Standard: `books/`) |
| `GUILD_ID` | nein | Server-ID fuer DM-Admin-Berechtigungen (0 = aus) |
| `LICHESS_TOKEN` | nein | OAuth-Token (Scope: `study:write`) fuer Studien-Upload |
| `PUZZLE_STUDY_ID` | nein | Feste Studie fuer alle Puzzles (empfohlen mit Token) |
| `TOURNAMENT_CHANNEL_ID` | nein | Channel fuer Turnier-Posts (0 = aus) |
| `WOCHENPOST_CHANNEL_ID` | nein | Channel fuer Wochenposts (0 = aus) |
| `LIBRARY_INDEX` | nein | Pfad zur `index.txt` der Buchbibliothek |
| `CLAUDE_API_KEY` | nein | API-Key fuer KI-Chat (ohne = Chat deaktiviert) |
| `SFTPGO_BASE_URL` | nein | SFTPGo-URL fuer Dateien >8 MB |
| `SFTPGO_SHARE_ID` | nein | SFTPGo-Share-ID |
| `SFTPGO_SHARE_PASSWORD` | nein | SFTPGo-Share-Passwort |

Laufzeitdaten werden automatisch in `config/` gespeichert (gitignored).

---

## Docker

### docker-compose.yml

```yaml
services:
  schach-bot:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./config:/app/config
      - ./books:/app/books
    mem_limit: 512m
    cpus: 0.5
```

```bash
# Starten
docker compose up -d

# Logs verfolgen
docker compose logs -f

# Update deployen
git pull && docker compose down && docker compose up -d --build

# Stoppen
docker compose down
```

`config/` und `books/` werden als Volumes gemountet und bleiben beim Rebuild erhalten.

### Images (CI/CD)

| Tag | Wann |
|-----|------|
| `:dev` | Jeder Push auf `main` |
| `:x.y.z`, `:x.y`, `:latest` | Git-Tag `vx.y.z` |

Das Dev-Image traegt den Git-SHA — sichtbar via `/version` (z.B. `v2.22.1 (abc1234)`).

### Healthcheck

Der Container prueft alle 60 Sekunden `config/health.json`. Wenn der Timestamp aelter als 120 Sekunden ist, gilt der Container als unhealthy.

### Als systemd-Service (ohne Docker)

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

---

## Architektur

```
schach-bot/
├── bot.py                      # Main Entry, Events, Admin-Commands, Daily-Task
├── puzzle/
│   ├── commands.py            # /puzzle, /kurs, /train, /next, /endless
│   ├── selection.py           # Laden, Caching, Auswahl
│   ├── processing.py          # PGN-Trimming, Loesungs-Extraktion
│   ├── rendering.py           # Board → PNG (SVG-Figuren + Pillow)
│   ├── embed.py               # Discord-Embed-Aufbau
│   ├── posting.py             # Senden + Lichess-Upload
│   ├── buttons.py             # PuzzleView (Reaktions-Buttons)
│   ├── lichess.py             # Lichess-API + Rate-Limiting
│   └── state.py               # Persistenter Zustand (Ignore, Training)
├── commands/
│   ├── blind.py               # /blind
│   ├── chat.py                # KI-Chat (/chat_whitelist, DM-Listener)
│   ├── elo.py                 # /elo
│   ├── reminder.py            # /reminder + Loop
│   ├── schachrallye.py        # /schachrallye*, /turnier*, Turnier-Import
│   ├── wochenpost.py          # /wochenpost* + Loop
│   ├── wochenpost_buttons.py  # WochenpostView
│   ├── turnier_buttons.py     # TurnierReviewView
│   ├── wanted.py              # /wanted*
│   ├── resourcen.py           # /resourcen
│   ├── youtube.py             # /youtube
│   ├── release_notes.py       # /release-notes
│   ├── test.py                # /test (Diagnose)
│   └── _collection.py         # URL-Collection-Helfer
├── library.py                 # /bibliothek, /tag, /autor, /reindex
├── core/
│   ├── json_store.py          # Atomare JSON-Persistenz (Thread-safe)
│   ├── paths.py               # CONFIG_DIR
│   ├── version.py             # VERSION, GIT_SHA, START_TIME
│   ├── stats.py               # User-Statistiken
│   ├── permissions.py         # Admin/Moderator-Check
│   ├── log_setup.py           # Rotating Log + EmptyFen-Filter
│   ├── dm_log.py              # DM-Protokollierung
│   ├── event_log.py           # Reaktions-JSONL-Log
│   ├── button_tracker.py      # Click-Zaehler (LRU)
│   └── datetime_utils.py      # Datums-Helfer
├── books/                      # PGN-Dateien + books.json
├── assets/                     # Icons, SVG-Figuren, Sprueche
├── tests/                      # test_trim.py, test_commands.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── CHANGELOG.md
└── config/                     # Runtime-State (gitignored, auto-erstellt)
```

### Zentrale Muster

- **Atomare Persistenz**: `json_store.py` bietet `atomic_read/write/update` mit per-file Locks und `tempfile` → `os.replace`. Alle Config-Dateien nutzen diesen Mechanismus.
- **In-Memory-Caches**: Puzzle-Lines (Pickle), Ignore-Listen, Books-Config. Invalidierung bei Schreibzugriff oder `/reindex`.
- **Button-Mutex**: Buttons kommen in exklusiven Paaren (richtig/falsch, gut/schlecht). Klicks werden sofort deferred, Seiteneffekte laufen als Background-Tasks.
- **Zeitzonen**: Immer `datetime.now(timezone.utc)`, nie `datetime.utcnow()`. Wochenpost-Erinnerungen nutzen `Europe/Vienna`.

---

## Commands

### Puzzle

| Command | Beschreibung | Zugriff |
|---------|-------------|---------|
| `/puzzle [anzahl] [buch] [id] [user]` | 1–20 Puzzles posten | alle (user: Admin) |
| `/kurs [buch]` | Buecher + Kapiteldetails auflisten | alle |
| `/train [buch]` | Sequenzielles Training starten/stoppen | alle |
| `/next [anzahl]` | Naechste Puzzle(s) aus Training | alle |
| `/endless [buch]` | Endlosmodus (auto-next nach Reaktion) | alle |
| `/blind [moves] [anzahl] [buch]` | Blind-Puzzle: N Halbzuege mental loesen | alle |
| `/ignore_kapitel [buch] [kapitel]` | Ganzes Kapitel ignorieren | Admin |

### Turnier & Rallye

| Command | Beschreibung | Zugriff |
|---------|-------------|---------|
| `/turnier [tag]` | Kommende Turniere auflisten | alle |
| `/turnier_sub [tag]` | Turnier-Benachrichtigung abonnieren | alle |
| `/turnier_unsub [tag]` | Abo kuendigen | alle |
| `/turnier_parse` | Turniere von tirol.chess.at importieren | Admin |
| `/turnier_review` | Review-Benachrichtigungen an/aus | Admin |
| `/turnier_pending` | Noch nicht freigegebene Turniere | Admin |
| `/schachrallye` | Rallye-Termine auflisten | alle |
| `/schachrallye_add [datum] [ort]` | Rallye-Termin hinzufuegen | Admin |
| `/schachrallye_del [id]` | Rallye-Termin loeschen | Admin |
| `/schachrallye_sub` | Rallye-Erinnerungen abonnieren | alle |
| `/schachrallye_unsub` | Abo kuendigen | alle |

### Wochenpost

| Command | Beschreibung | Zugriff |
|---------|-------------|---------|
| `/wochenpost` | Geplante + gepostete Wochenposts | Admin |
| `/wochenpost_add [datum] [text] [url] [pdf]` | Neuen Wochenpost anlegen | Admin |
| `/wochenpost_del [id]` | Wochenpost loeschen | Admin |
| `/wochenpost_sub [zeit]` | Taegl. Erinnerung abonnieren (MEZ/MESZ) | alle |
| `/wochenpost_unsub` | Abo kuendigen | alle |

### Community

| Command | Beschreibung | Zugriff |
|---------|-------------|---------|
| `/elo [wert]` | ELO-Wertung setzen / anzeigen | alle |
| `/resourcen [url] [beschreibung]` | Online-Ressourcen teilen / auflisten | alle |
| `/youtube [url] [beschreibung]` | YouTube-Links teilen / auflisten | alle |
| `/wanted [beschreibung]` | Feature-Wunsch einreichen / auflisten | alle |
| `/wanted_list` | Alle Wuensche (sortiert nach Stimmen) | alle |
| `/wanted_vote [id]` | Fuer Wunsch abstimmen (Toggle) | alle |
| `/wanted_delete [id]` | Wunsch loeschen | Admin |

### Bibliothek

| Command | Beschreibung | Zugriff |
|---------|-------------|---------|
| `/bibliothek [suche]` | Buch-Suche (Titel/Autor/Tag) | alle |
| `/tag [tag]` | Nach Tag filtern | alle |
| `/autor [autor]` | Nach Autor filtern | alle |
| `/reindex` | Katalog + Puzzle-Cache neu aufbauen | Admin |

### KI-Chat

| Command | Beschreibung | Zugriff |
|---------|-------------|---------|
| `/chat_whitelist [user] [aktion]` | Chat-Zugang verwalten | Admin |
| `/chat_clear` | Eigene Chat-Historie loeschen | alle |

### Info & Admin

| Command | Beschreibung | Zugriff |
|---------|-------------|---------|
| `/help [bereich]` | Hilfe anzeigen | alle |
| `/version` | Version + Git-SHA + Uptime | alle |
| `/release-notes [version] [anzahl]` | Changelog anzeigen | alle |
| `/reminder [hours] [puzzle_count] [buch]` | Puzzle-Erinnerung konfigurieren | alle |
| `/stats` | User-Statistiken | Admin |
| `/announce [user]` | Willkommensnachricht senden | Admin |
| `/greeted` | Begruesste User auflisten | Admin |
| `/daily` | Taeglichen Post manuell ausloesen | Admin |
| `/log [zeilen]` | Bot-Log anzeigen | Admin |
| `/dm-log [user]` | Ausgehende DMs anzeigen | Admin |
| `/test [modus]` | Diagnosetests ausfuehren | Admin |

---

## Puzzle-System

### Ablauf

1. **Auswahl** (`selection.py`): PGN-Dateien aus `books/` werden geparst und als Pickle gecacht. Taeglich wird ein zufaelliges Puzzle aus dem aktiven Pool gezogen (Buecher mit `random: true` in `books.json`).

2. **Verarbeitung** (`processing.py`): Das PGN wird getrimmt — Training-Comment (`[%tqu]`) extrahiert, Varianten bereinigt, Nullzug-Variationen aufgeloest.

3. **Rendering** (`rendering.py`): Board wird als PNG gerendert — Lichess cburnett-SVG-Figuren via `svglib`/`reportlab` auf ein Pillow-Canvas.

4. **Posting** (`posting.py`): Embed + Bild werden als DM oder Channel-Post gesendet. Optional Lichess-Upload mit klickbarem Studien-Link (interaktives Gamebook mit 2 Kapiteln: Quiz + vollstaendige Partie).

### Buttons

| Button | Funktion |
|--------|----------|
| ✅ | Richtig geloest |
| ❌ | Falsch geloest |
| 👍 | Gutes Puzzle |
| 👎 | Schlechtes Puzzle |
| 🚮 | Puzzle ignorieren (jeder User) |
| ☠️ | Ganzes Kapitel ignorieren (Admin) |

Buttons sind als Mutex-Paare implementiert: ✅↔❌ und 👍↔👎 schliessen sich gegenseitig aus. Alle Reaktionen werden in `config/reaction_log.jsonl` protokolliert (inkl. ELO des Users).

### Buecher-Config (books/books.json)

```json
{
  "100-Tactical-Patterns.pgn": {
    "difficulty": "Fortgeschritten",
    "rating": 6,
    "blind": true,
    "random": true
  }
}
```

- `difficulty`: Anzeige-Label (Anfaenger, Fortgeschritten, Meister)
- `rating`: 1–10 Schwierigkeitsgrad
- `blind`: Fuer `/blind`-Modus geeignet
- `random`: Im taeglichen Pool (`true`) oder deaktiviert (`false`)

### Modi

| Modus | Command | Beschreibung |
|-------|---------|-------------|
| Einzelpuzzle | `/puzzle` | 1–20 zufaellige Puzzles per DM |
| Training | `/train` + `/next` | Sequenziell durch ein Buch, Fortschritt gespeichert |
| Endlos | `/endless` | Nach jeder Reaktion kommt das naechste (5 Min Timeout) |
| Blind | `/blind` | N Halbzuege mental loesen, dann erst das Brett sehen |
| Reminder | `/reminder` | Wiederkehrende Puzzle-DMs (1–168h Intervall) |
| Taeglich | automatisch | Ein Puzzle pro Tag im konfigurierten Channel |

---

## Turnier & Rallye

### Turniere

- **Quelle**: `tirol.chess.at/termine/` (stuendlicher HTML-Scrape)
- **Tags**: schnellschach, blitz, 960, klassisch, jugend, senioren
- **Review-System**: Neue Turniere werden erst nach Admin-Freigabe gepostet (Approve/Reject-Buttons per DM an Reviewer)
- **Abos**: User koennen Tags abonnieren und werden per DM benachrichtigt
- **Aufbewahrung**: Vergangene Events werden nach 90 Tagen geloescht

### Rallye

- Separate Terminverwaltung (manuell via `/schachrallye_add`)
- Taegl. Erinnerungen um 14:00 UTC an Abonnenten
- 7-Tage-Vorwarnung vor Terminen

---

## Wochenpost

Woechentliche Aufgaben/Themen, gepostet als Thread in einem konfigurierten Channel.

- **Posting**: Taeglich 18:00 UTC, wenn ein Eintrag fuer das Datum existiert
- **Formate**: Text, URL, PDF-Anhang, oder Kombination
- **Abonnenten**: Taegl. DM-Erinnerung mit Schach-Spruch (aus `assets/sprueche.json`) + optionalem Claude-Kommentar
- **Resolution-Tracking**: User markieren sich per Button als fertig
- **Eskalation**: Claude-Erinnerungen werden sarkastischer je oefter man erinnert wird:
  - Stufe 1 (0–2x): Augenzwinkern
  - Stufe 2 (3–6x): Frech
  - Stufe 3 (7–11x): Drill-Sergeant
  - Stufe 4 (12+x): Theatralisches Chaos

---

## KI-Chat

Powered by Claude (`claude-sonnet-4-6`), aktiviert durch `CLAUDE_API_KEY` in `.env`.

- **Zugang**: Per `/chat_whitelist` oder global freigeschaltet
- **Interaktion**: User schreiben dem Bot per DM, Claude antwortet
- **Puzzle-Kontext**: Wenn der User gerade ein Puzzle bekommen hat, kennt Claude das Brett (FEN, Zug, Schwierigkeit, Loesung)
- **Historie**: Max 20 Nachrichten (10 Austausche), loeschbar via `/chat_clear`
- **Persoenlichkeit**: Strenger aber humorvoller Schach-Trainer, antwortet auf Deutsch

---

## Bibliothek

Durchsuchbare Schachbuch-Sammlung basierend auf einer `index.txt`-Datei (Pfad via `LIBRARY_INDEX`).

- **Suche**: Volltextsuche ueber Titel, Autor, Tags
- **Download**: Dateien <8 MB direkt via Discord, groessere via SFTPGo-Share
- **Ignore-Patterns**: `ignore.json` pro Ordner (fnmatch-Syntax)
- **Cache**: `library.json` wird automatisch generiert, `/reindex` zum Neuaufbau

---

## Tests

```bash
python tests/test_trim.py       # 171 Snapshot-Regressionstests
python tests/test_commands.py   # 631 Command-Tests
```

### Regeln

1. **Pflicht**: Nach jeder Aenderung muessen ALLE Tests gruen sein.
2. **Test-First**: Fuer jedes neue Feature zuerst einen Test schreiben.
3. **Bug-First-Test**: Bei Bugs zuerst einen fehlschlagenden Test schreiben, dann fixen.
4. **Snapshots**: `tests/trim_snapshots.json` nie automatisch anpassen — immer manuell pruefen.

### Diagnose (/test)

Der `/test`-Command bietet 7 Modi fuer Live-Diagnose im Discord:

| Modus | Prueft |
|-------|--------|
| `status` | Latenz, Guilds, Uptime, Task-Loops |
| `files` | JSON-Integritaet aller Config-Dateien |
| `pgn` | PGN-Parsing + books.json-Validierung |
| `lichess` | Token-Gueltigkeit + API-Erreichbarkeit |
| `rendering` | Board-Rendering (Vorschaubild) |
| `assets` | SVG-Figuren, Sprueche, Bot-Icons |
| `snapshots` | Snapshot-Regressionstests |

---

## Release-Workflow

### Vor jedem Commit

1. Version in `core/version.py` bumpen (bugfix/minor/major nach SemVer)
2. Eintrag in `CHANGELOG.md` im Keep-a-Changelog-Format
3. Beide Dateien im selben Commit — nie nachtraeglich

### Deployment

```bash
# Dev-Image (automatisch bei Push auf main)
git push origin main

# Release-Image
git tag v2.22.1
git push origin main --tags
# → baut :2.22.1, :2.22, :latest und :dev
```

### CI/CD

GitHub Actions (`.github/workflows/release.yml`):
- **Trigger**: Push auf `main` oder Git-Tag `v*`
- **Registry**: `ghcr.io`
- **Dev-Image**: Enthaelt den Git-SHA (sichtbar via `/version`)

---

## Laufzeit-Dateien (config/)

Alle Dateien werden automatisch erstellt und via `json_store.py` atomar geschrieben.

| Datei | Inhalt |
|-------|--------|
| `health.json` | Healthcheck-Timestamp + Latenz |
| `puzzle_state.json` | Training-Fortschritt, Endlos-Sessions |
| `puzzle_ignore.json` | Ignorierte Puzzle-IDs |
| `chapter_ignore.json` | Ignorierte Kapitel |
| `puzzle_lines.pkl` | Puzzle-Cache (Pickle) |
| `elo.json` | ELO-Historie pro User |
| `reminder.json` | Puzzle-Erinnerungen |
| `user_stats.json` | User-Statistiken |
| `user_studies.json` | Lichess-Studien pro User |
| `chat.json` | KI-Chat Whitelist + Historie |
| `resourcen.json` | Geteilte Ressourcen |
| `youtube.json` | Geteilte YouTube-Links |
| `wanted.json` | Feature-Wuensche + Votes |
| `turnier.json` | Turniere, Abos, Reviewer |
| `wochenpost.json` | Wochenpost-Eintraege |
| `wochenpost_sub.json` | Wochenpost-Abonnenten |
| `dm_state.json` | Begruessungs-Status |
| `dm_log.json` | DM-Protokoll (30 Tage Retention) |
| `reaction_log.jsonl` | Reaktions-Log (append-only, max 50k Zeilen) |
| `wochenpost_log.jsonl` | Wochenpost-Log (append-only) |
| `lichess_cooldown.json` | Lichess Rate-Limit-Timer |

---

## Bot-Berechtigungen

Scopes: `bot` + `applications.commands`

| Berechtigung | Wofuer |
|-------------|--------|
| Send Messages | Taegliches Puzzle, Thread-Posts |
| Embed Links | Board-Embeds |
| Attach Files | Brett-Bild (PNG) |
| Create Public Threads | Daily-Puzzle-Thread |
| Send Messages in Threads | Posts im Thread |
| Manage Threads | Thread-Archivierung |

DMs: Nutzer muessen "Direktnachrichten von Servermitgliedern erlauben" aktiviert haben.
