# Changelog

Alle nennenswerten Änderungen am Schach-Bot. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionierung nach
[SemVer](https://semver.org/lang/de/) (`major.minor.bugfix`).

## [1.8.4] - 2026-04-13
### Fixed
- Discord-Bild war bei Puzzles mit `[%tqu]` im Root-Kommentar (z.B.
  The Chess Coach Companion `021.004`) einen Zug zu früh: das Brett
  zeigte die Stellung VOR dem Setup-Zug, das Embed sagte „Schwarz am
  Zug", und der User musste den im PGN markierten Setup-Zug selbst
  nachvollziehen. `_trim_to_training_position()` interpretiert das
  Root-`[%tqu]` jetzt analog zum Kindknoten-Fall: erste Variante ist
  der bekannte Setup-Zug, Trainingsstellung beginnt danach. Damit
  zeigen Discord-Bild und Lichess-Studie konsistent die Stellung, in
  der der User wirklich raten muss. Zusammen mit der `[SetUp "1"]`-
  Korrektur aus 1.8.2 sind beide Seiten jetzt wieder synchron.

## [1.8.3] - 2026-04-13
### Fixed
- `/puzzle id:` toleriert jetzt ein vorangestelltes `ID:` (Copy-Paste
  aus dem Embed-Footer „ID: foo.pgn:003.004"). Vorher schlug die Suche
  in dem Fall mit „⚠️ Puzzle nicht gefunden" fehl.

## [1.8.2] - 2026-04-13
### Fixed
- Lichess spielte bei Puzzles mit FEN „Black to move" (z.B. The Chess
  Coach Companion `021.004`) den ersten Zug automatisch ab und zeigte
  dem User die Stellung NACH dem Zug – während Discord die Stellung
  korrekt davor zeigte. Ursache: Quell-PGN enthält nur `[FEN "..."]`,
  aber kein `[SetUp "1"]`. Per PGN-Spec ist `SetUp` zwingend, sonst
  ignoriert/„repariert" Lichess die Stellung. Fix: `_clean_pgn_for_lichess()`
  ergänzt `[SetUp "1"]` automatisch direkt vor jedem `[FEN ...]`-Header,
  wenn es noch nicht da ist.

## [1.8.1] - 2026-04-13
### Fixed
- Discord-503 (transienter `DiscordServerError`) auf einem optionalen
  Followup (Lösung-Spoiler, „Ganze Partie", Lichess-Link) markierte das
  ganze Puzzle als gescheitert, obwohl Brett + Embed schon erfolgreich
  angekommen waren. Bei `/puzzle 5` kam der User dann mit „⚠️ Nur 4/5"
  raus, obwohl alle 5 Bretter sichtbar waren. Fix:
  - Neuer Helper `_resilient_send()` mit Retry (1s/2s/4s Backoff) für
    Discord-5xx.
  - `posted_ok` wird jetzt direkt nach dem erfolgreichen Embed-Send
    hochgezählt, nicht erst am Ende der Iteration.
  - Optionale Sends laufen über `_send_optional()` (Retry + Logging,
    aber kein Re-Raise) und können das Erfolgsergebnis nicht mehr kippen.
- Gleiche Härtung für `post_blind_puzzle()`.

## [1.8.0] - 2026-04-13
### Added
- `puzzle.load_all_lines()` cached jetzt zweistufig: in-memory + Pickle
  in `config/puzzle_lines.pkl`. Cache-Key ist Fingerprint aller PGN-
  Dateien + `books.json` (mtime + size); externe Edits triggern
  automatisch Re-Parse beim nächsten Aufruf.
- Performance: PGN-Re-Parse ~3.8 s → Pickle-Load ~0.4 s (~9× schneller),
  weitere Aufrufe in derselben Bot-Session ms-schnell aus dem
  Memory-Cache. Filterung (illegale Stellungen, leere FENs etc.) findet
  nur noch beim Re-Parse statt.
- `clear_lines_cache()` helper für manuelle Invalidierung.

### Changed
- `/reindex` (Admin) baut nun beides neu auf:
  Bibliotheks-Katalog **und** Puzzle-Pickle-Cache. Bibliotheks-Teil
  wird übersprungen, wenn `LIBRARY_INDEX` nicht in `.env` gesetzt ist
  (vorher kompletter Abbruch).

## [1.7.3] - 2026-04-13
### Fixed
- `/puzzle anzahl:N` brach bei einem einzigen kaputten Puzzle die ganze
  Schleife ab; der User sah nur die bis dahin geposteten (oft 1) plus
  ephemer ein "❌ Fehler"-Followup, das leicht übersehen wurde. Jetzt
  läuft jede Iteration in eigenem `try/except`, fehlgeschlagene Puzzles
  werden mit `log.exception` protokolliert, der Rest wird trotzdem
  gepostet. Folge-Message zeigt die echte Anzahl gesendeter Puzzles
  (z.B. „⚠️ Nur 4/5 Puzzle(s) konnten gesendet werden …").
- `post_puzzle()` gibt jetzt die Anzahl tatsächlich geposteter Puzzles
  zurück, der Stats-Counter wird entsprechend nur um die geposteten
  inkrementiert (vorher: optimistisch um die geplante Anzahl).

## [1.7.2] - 2026-04-13
### Fixed
- `load_all_lines()` filtert Linien mit grob illegaler Startstellung raus
  (fehlender weißer/schwarzer König, Bauern auf der Grundreihe, Nicht-am-
  Zug-Seite im Schach, leeres Brett, >2 Schach-Geber). Trifft praktisch
  nur PGNs mit kaputtem FEN-Header. 81 solcher Linien aus dem aktuellen
  Pool entfernt (61× weißer König fehlt, 6× schwarzer König fehlt, 14×
  beide). Kosmetische Defekte wie inkonsistente Rochaderechte oder
  En-passant-Square bleiben toleriert.

## [1.7.1] - 2026-04-13
### Added
- Pro-Ordner-Filter via `ignore.json`: ein JSON-Array von fnmatch-Patterns
  (`["*"]`, `["*.pgn"]`, `["A01.pgn", "A02.pgn"]`, …). Liegt im jeweiligen
  Ordner unterhalb des Library-Roots und gilt rekursiv für alle Dateien in
  diesem Ordner und allen Unterordnern. Greift bei `/bibliothek`, `/tag`,
  `/autor`. Vorteil: wenn der Ordner verschoben wird, wandert die
  ignore.json mit – Filter bleibt wirksam. `library.json` bleibt
  unverändert (View-Layer auf den in-memory-Cache); aktiv nach Bot-Restart
  oder `/reindex`.
- Erste ignore.json angelegt für `AAAnew/Encyclopedia of Chess Openings/`
  → blendet 505 ECO-Einträge (A01–E99) aus dem Trefferpool aus.

## [1.7.0] - 2026-04-13
### Added
- 6 neue Puzzle-Bücher in `books/`:
  - **The Chess Coach Companion Intermediate Syllabus** (587 Linien, Fortgeschritten ★★★★★)
  - **The Fundamentals 3 Chess Evolution** (542, Fortgeschritten ★★★★★★★, Yusupov)
  - **World Champion Calculation Training – Part 1** (342, Meister ★★★★★★)
  - **The Art of Exchanging Pieces** (125, Fortgeschritten ★★★★)
  - **Basic Endgames** (194, Anfänger ★★★★★)
  - **The Fundamentals 1 Build Up Your Chess** (548, Anfänger ★★★★★★★, Yusupov)
- Damit Pool insgesamt: **5949 Linien** (vorher 2630).
- Blind-Modus zusätzlich aktiviert für die Bücher mit ≥5% blind-fähigen
  Puzzles (Chess Coach Companion, Basic Endgames, Art of Exchanging
  Pieces, Fundamentals 1).

## [1.6.0] - 2026-04-13
### Added
- Per-Buch-Flag `random: true|false` in `books/books.json` (analog zu
  `blind`). Nur Bücher mit `random: true` (Default `true`) sind im Pool
  für `/puzzle` (ohne `buch:`-Parameter) und für den täglichen Daily-Post.
  Wird ein Buch explizit per `buch:N` gewählt, gilt das Flag nicht – der
  User bekommt ein Puzzle aus genau diesem Buch.
- `/kurs` zeigt 🎲 für Bücher, die im Zufalls-/Daily-Pool sind.
- Helper `puzzle.get_random_books()` analog zu `get_blind_books()`.

## [1.5.3] - 2026-04-13
### Fixed
- Nach 3–5 schnellen Klicks hängte der nächste Klick ~30 s. Ursache:
  `interaction.response.edit_message` lief in den Discord-Rate-Limit-Bucket
  fürs Editieren der Puzzle-Nachricht. Jetzt wird der Klick mit `defer()`
  bestätigt (eigener, viel großzügigerer Bucket), die Counter-Labels werden
  per `edit_original_response` im Background-Task nachgezogen. Folge:
  Klicks bleiben flüssig, das visuelle Counter-Update kann bei Bursts
  hinterherhinken, blockt aber nichts.

## [1.5.2] - 2026-04-13
### Fixed
- Button-Klicks blockierten den Event-Loop für teils Minuten, weil das
  sync Pillow-Rendering (`_render_board`) und sync File-I/O (Logging,
  Stats) den asyncio-Loop festhielten. Folge: ein Klick antwortete schnell,
  der nächste hing fest hinter dem Rendering-Task des Vorgängers.
  Fix in zwei Stufen:
  1. `_handle_click` bestätigt die Interaktion sofort via `edit_message`
     und schiebt alle Side-Effects (Logging, Stats, 🚮-DM, Endless-Next)
     in einen Background-Task (`asyncio.create_task`).
  2. Sync Blocking-Calls laufen jetzt in `asyncio.to_thread` —
     `_render_board` an allen 5 Aufrufstellen sowie `event_log.log_reaction`
     und `stats.inc` im Side-Effect-Task.

## [1.5.1] - 2026-04-13
### Fixed
- Button-Klicks blockierten teils sehr lange (Discord-Spinner), besonders
  wenn die mutex-Gegenstimme automatisch entfernt wurde. Jetzt wird zuerst
  die Interaktion bestätigt (3-Sekunden-Limit eingehalten), Logging und
  Stats laufen erst danach.

## [1.5.0] - 2026-04-13
### Changed
- Reaktions-Buttons sind jetzt **wechselseitig exklusiv pro User**:
  ✅ ↔ ❌ und 👍 ↔ 👎. Klick auf einen schaltet den eigenen Vorgänger
  automatisch ab (und protokolliert dies sauber im Reaction-Log).
- Alle 5 Buttons (✅ ❌ 👍 👎 🚮) liegen jetzt in einer Reihe.

### Removed
- ☠️-Button (ganzes Kapitel ignorieren) entfernt. Admins können Kapitel
  weiterhin per `/ignore_kapitel` ignorieren.

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
