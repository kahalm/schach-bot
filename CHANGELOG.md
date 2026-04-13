# Changelog

Alle nennenswerten Änderungen am Schach-Bot. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionierung nach
[SemVer](https://semver.org/lang/de/) (`major.minor.bugfix`).

## [1.4.0] - 2026-04-13
### Changed
- Reaktionen ersetzt durch **Buttons**. Jedes Puzzle bekommt eine Reihe
  ✅ ❌ 👍 👎 plus 🚮 ☠️. Counter starten bei 0 (kein Bot-Vorklick mehr) und
  zählen pro User einmalig hoch — zweiter Klick desselben Users entfernt
  seine Stimme wieder (Toggle).
- ☠️ ist Admin-only (Klick eines Nicht-Admins → ephemerer Hinweis, keine Aktion).
- Gleiche Side-Effects wie zuvor: 🚮 ignoriert das Puzzle und postet im
  Thread ein Ersatz-Puzzle, ☠️ ignoriert das ganze Kapitel, ✅/❌ triggern
  im Endless-Modus das nächste Puzzle.
- Reaktions-Counter sind in-memory; nach Restart starten sie wieder bei 0,
  die vollständige Historie bleibt im Reaction-Log erhalten.

### Removed
- `on_raw_reaction_add` / `on_raw_reaction_remove` Handler in `bot.py`
- Lokales `_is_admin` in `bot.py` (wandert in `puzzle/buttons.py`)

## [1.3.0] - 2026-04-13
### Added
- Append-only Reaktions-Log `config/reaction_log.jsonl`. Jede ✅/❌/👍/👎/🚮/☠️
  (Add und Remove) wird mit Zeitstempel, User, `line_id`, Modus
  (`normal`/`blind`), Emoji, ±1-Delta und der aktuellen Elo des Users protokolliert.
- `puzzle.get_puzzle_mode(msg_id)` — verfügt jetzt über die Info, ob eine
  Reaktion auf ein normales oder ein Blind-Puzzle erfolgt.
- `core/event_log.py` mit `log_reaction()` und `read_all()` für Auswertungen.

## [1.2.1] - 2026-04-13
### Changed
- `/blind`: `moves` ist jetzt optional (Default 4 Halbzüge).

## [1.2.0] - 2026-04-13
### Added
- `/blind moves:X anzahl:Y buch:Z` — Blind-Modus. Zeigt die Stellung X Halbzüge
  vor der eigentlichen Trainingsposition. Der User muss die X Züge im Kopf
  spielen und dann das Puzzle lösen.
- Per-Buch-Flag `blind: true|false` in `books/books.json`. Nur Bücher mit
  `blind: true` werden für `/blind` ausgewählt.
- `/kurs` zeigt 🙈 für Blind-Mode-fähige Bücher.
- Stat-Counter `blind_puzzles` pro User.

### Changed
- `books.json` um `blind`-Feld erweitert; "100 Tactical Patterns" und
  "The Checkmate Patterns Manual" sind als Default freigegeben (haben echte
  Vorlauf-Züge), die anderen beiden Bücher (FEN-only) sind deaktiviert.

## [1.1.0] - 2026-04-13
### Added
- `/release-notes` zeigt die letzten Einträge aus diesem Changelog (optional `version:`).

### Changed
- Refactor: Code in Pakete `core/`, `commands/` und `puzzle/` aufgeteilt
  (3 bisectable Schritte, öffentliche API bleibt unverändert).
- Konvention: Bei jeder Änderung wird `core/version.py` angepasst und ein
  Eintrag in dieser Datei ergänzt.

## [1.0.0] - 2026-04-12
### Added
- `VERSION`-Konstante (`major.minor.bugfix`) und `/version` mit letzter Restartzeit.
- `/elo` — eigene Schach-Elo angeben (mit Historie).
- `/ignore_kapitel` und ☠️-Reaktion: Admins können ganze Kapitel ignorieren.
- `/reminder` — wiederkehrende Puzzle-DMs in einstellbarem Intervall.
- `/resourcen` und `/youtube` — Lernlinks bzw. Kanäle/Videos sammeln und anzeigen.
- Puzzle-ID im Embed-Footer; `/puzzle id:` für gezielten Aufruf.
- 🚮-Reaktion wird in den Statistiken mitgezählt.

### Changed
- Runtime-State (`*.json`) liegt unter `config/`, Bot-Icons unter `assets/`,
  Test-Skripte unter `tests/`.
- `CONFIG_DIR` zentral in `paths.py` (jetzt `core/paths.py`).
- `/help` versteckt Admin-Befehle (`/announce`, `/reindex`).

### Fixed
- Discord-Timestamps in Reminder/Stats nutzen `datetime.now(timezone.utc)`
  (zuvor falsche Anzeige "vor einer Stunde" wegen naiver UTC-Zeit).
- Leere PGN-Zeilen und Zeilen mit `1. -- *` werden beim Laden übersprungen.
- Korrekte Anzeige der Zugfarbe im Puzzle-Embed.
