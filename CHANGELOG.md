# Changelog

Alle nennenswerten Änderungen am Schach-Bot. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionierung nach
[SemVer](https://semver.org/lang/de/) (`major.minor.bugfix`).

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
