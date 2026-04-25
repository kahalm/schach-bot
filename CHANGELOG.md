# Changelog

Alle nennenswerten Änderungen am Schach-Bot. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionierung nach
[SemVer](https://semver.org/lang/de/) (`major.minor.bugfix`).

## [1.12.4] - 2026-04-25
### Changed
- `/stats` ist jetzt Admin-only.
- `/help` zeigt Admin-Befehle (`/stats`, `/daily`, `/announce`,
  `/ignore_kapitel`) nur wenn der anfragende User Admin ist.

## [1.12.3] - 2026-04-19
### Fixed
- Terminal-Log-Level von WARNING auf ERROR angehoben — nur noch echte
  Fehler im Terminal, Warnungen gehen nur ins Log-File.

## [1.12.2] - 2026-04-19
### Fixed
- 🚮-Ersatzpuzzle im Daily-Thread funktioniert jetzt — `post_puzzle`
  erkennt bestehende Threads und erstellt keinen Sub-Thread mehr.

## [1.12.1] - 2026-04-19
### Added
- `/daily` Slash-Command (Admin-only) löst manuell ein tägliches Puzzle
  im konfigurierten Channel aus.

## [1.12.0] - 2026-04-19
### Fixed
- Reminder nach Bot-Offline reicht nur noch 1 Puzzle nach statt alle
  verpassten Runden einzeln abzufeuern. User bekommt eine Erklärung
  wie viele Reminder verpasst wurden.

## [1.11.3] - 2026-04-19
### Changed
- Release-Regel in `CLAUDE.md` verankert (Version-Bump + Changelog bei jedem Commit).

## [1.11.2] - 2026-04-19
### Changed
- Daily-/Random-Pool auf 5 Bücher reduziert (Basic Endgames, Fundamentals 1–3,
  Ultimate Chess Puzzle Book, World Champion Calculation deaktiviert).

## [1.11.1] - 2026-04-14
### Fixed
- Lichess-Gamebook-Kapitel ohne Kommentare exportieren — Chessable-Annotationen
  störten den Gamebook-Modus.

## [1.11.0] - 2026-04-14
### Changed
- Lines ohne `[%tqu]`-Annotation werden in allen Puzzle-Modi übersprungen
  (Daily, `/puzzle`, `/endless`). Nur `/next` zeigt sie als offenes Kapitel an.
- `/puzzle id:` gibt eine Warnung aus wenn die ID auf eine Line ohne
  Trainingskommentar zeigt.
- `/next` rendert non-`[%tqu]`-Lines als "📖 Kapitel" mit offenen Zügen
  statt als Spoiler-Puzzle (keine Buttons, keine Reactions).
- `/test` zeigt ✅/❌ Emoji vor jedem Snapshot-Eintrag.
- Alle 12 PGN-Bücher aus frischem Chessable-Export aktualisiert.
  Trim-Snapshots an neue Solutions/Preludes angepasst; 5 Intro-Kapitel
  ohne `[%tqu]` aus Snapshots entfernt.

## [1.10.15] - 2026-04-14
### Fixed
- `_prelude_pgn` crashte mit `san() expect move to be legal` wenn das
  Original-Game von einer FEN-Position statt der Standardstellung startet.
  Prelude übernimmt jetzt die Startstellung vom Context-Game.

## [1.10.14] - 2026-04-14
### Changed
- `/train` zeigt Kursnummer in Klammern hinter dem Buchnamen an.

## [1.10.13] - 2026-04-14
### Fixed
- Alle 12 PGN-Bücher durch frischen Chessable-Export ersetzt. Mehrere
  Bücher hatten `[%tqu]`-Annotationen um einen Halbzug verschoben.

## [1.10.12] - 2026-04-14
### Removed
- Advance-Override-System komplett entfernt (`config/advance_overrides.json`,
  `trim_and_advance`, `_advance_past_answer`). Einzelne Puzzle-Fixes per
  Override-Datei sind nicht gewünscht — Korrekturen müssen musterbasiert sein.

## [1.10.11] - 2026-04-14
### Added
- `/test puzzle:1` zeigt Board-Bild, Seite am Zug und Lösung (Spoiler) pro Snapshot.
- `/test lichess:1` generiert Lichess-Studienlink pro Snapshot.

## [1.10.10] - 2026-04-14
### Added
- `/test kurs:`-Parameter zum Filtern der Snapshot-Tests nach Buch.
- `/test` splittet Ergebnisse auf mehrere Embeds bei >25 Snapshots
  (Discord-Limit 25 Felder pro Embed).

### Fixed
- Advance-Override-System für `_trim_to_training_position`: Puzzles, bei denen
  der Trim die Stellung VOR dem Setup-Zug liefert, werden per manueller
  Override-Datei (`config/advance_overrides.json`) einen Zug weiter vorgerückt.
  Betrifft 007.061 (h3→Nd4) und 035.119 (Nc3→Qh4+).

## [1.10.9] - 2026-04-14
### Added
- Snapshot-Tests für alle 12 Bücher (je 3 Testfälle: Anfang, Mitte, Ende).
  Insgesamt 37 Snapshots, sortiert nach Buchname.

## [1.10.8] - 2026-04-14
### Added
- 3 Snapshot-Tests aus *1001 Chess Exercises For Club Players*
  (003.003 Anfang, 009.091 Mitte, 013.152 Ende).

## [1.10.7] - 2026-04-14
### Fixed
- Auto-Advance in `_trim_to_training_position` komplett entfernt. Die
  Heuristik war nicht zuverlässig (funktionierte für 007.061 aber brach
  011.032). Trim gibt jetzt immer die exakte [%tqu]-Position zurück.

### Added
- Neuer Snapshot-Test für Puzzle 011.032 (Budapester Gambit, Dd5-Falle).

## [1.10.6] - 2026-04-14
### Fixed
- Trim-Advance nur noch bei Nicht-Root-`[%tqu]`-Knoten. Bei Root-`[%tqu]`
  (z.B. 014.010) ist die erste Variante der gesuchte Zug selbst, nicht
  ein Setup-Zug. Behebt falsche Stellung (Kh1 statt Kg1, Weiß statt
  Schwarz am Zug).

## [1.10.5] - 2026-04-14
### Added
- `/test`-Dropdown zeigt bei Puzzle-Vorschau einen Lichess-Studien-Link
  zur direkten Prüfung im Gamebook-Modus.

## [1.10.4] - 2026-04-14
### Fixed
- Lichess-Gamebook-Orientierung wird jetzt automatisch gesetzt: bei
  Schwarz am Zug `orientation=black`, damit der erste Zug als Aufgabe
  gestellt wird statt auto-gespielt.

## [1.10.3] - 2026-04-14
### Fixed
- `_trim_to_training_position` rückt jetzt auch bei Nicht-Root-`[%tqu]`-Knoten
  über den Antwort-Zug hinaus vor, wenn danach Varianten folgen. Behebt falsche
  Trainingsstellung bei Puzzles wie 007.061 (zeigte Weiß am Zug statt Schwarz).
- Lichess-Gamebook bekommt jetzt dieselbe Post-Advance-Stellung wie Discord
  (Schwarz am Zug, Schwarz-Perspektive statt Weiß-Perspektive).
- `_prelude_pgn` enthält jetzt den letzten Zug vor der Puzzle-Stellung
  (z.B. 9. h3 fehlte vorher im Vorspiel).
- Reminder-Fehler (illegaler Zug bei PGN-Parsing) nur noch im Log, nicht
  mehr im Terminal.

## [1.10.1] - 2026-04-14
### Added
- `/test` Slash-Command (Admin-only): fuehrt Trim-Snapshot-Regressionstests
  live im Discord aus und zeigt Ergebnisse als Embed (gruen/rot).

## [1.10.0] - 2026-04-14
### Added
- Zwei neue Bücher in der Bibliothek:
  - *The Fundamentals 2 Boost Your Chess* (Fortgeschritten, Rating 7)
  - *1001 Chess Exercises For Club Players* (Fortgeschritten, Rating 6)

## [1.9.9] - 2026-04-13
### Changed
- `/kurs buch:N` markiert ignorierte Kapitel mit ~~Durchstreichung~~ und
  🚫 im Feldnamen sowie *(ignoriert)* im Wert.

## [1.9.8] - 2026-04-13
### Changed
- `/kurs buch:N` zeigt im Fortschrittsbalken nicht mehr die globalen
  „geposteten" Puzzles, sondern die vom aufrufenden User persönlich
  bewerteten (✅ oder ❌, netto >0 laut `reaction_log.jsonl`). Header
  geändert zu „N/M von dir bewertet (✅/❌)".

## [1.9.7] - 2026-04-13
### Changed
- `/blind moves:` hat keine Obergrenze mehr. Hat ein Spiel weniger
  Vorlauf-Züge als angegeben, werden automatisch so viele wie möglich
  verwendet statt das Puzzle zu überspringen.

## [1.9.6] - 2026-04-13
### Added
- Blind-Puzzles haben jetzt eine eigene ID-Notation im Embed-Footer:
  `ID: datei.pgn:021.004:blind:4` (Suffix `:blind:<moves>`).
- `/puzzle id: datei.pgn:021.004:blind:4` erkennt das Suffix und sendet
  das Puzzle direkt im Blind-Modus mit der angegebenen Züge-Anzahl.
  Kombination mit `user:` funktioniert ebenfalls.
- `/blind user:@Name` — `user:`-Parameter auch für `/blind` (v1.9.5.1).

## [1.9.5] - 2026-04-13
### Added
- `/kurs buch:N` zeigt Detailansicht eines Buches: Schwierigkeit,
  Sterne, Flags (🎲/🙈), Fortschrittsbalken pro Kapitel (`████░░░░
  4/17`) mit Kapitelname aus dem PGN-`Black`-Header. Discord-Limit
  von 25 Feldern wird respektiert.

## [1.9.4] - 2026-04-13
### Changed
- Lösungs-Spoiler filtert jetzt grafische PGN-Annotationen heraus:
  `[%cal ...]` (farbige Pfeile) und `[%csl ...]` (eingefärbte Felder)
  sowie andere `[%cmd ...]`-Blöcke werden entfernt; reine Textkommentare
  bleiben erhalten. Implementiert via neuem `_strip_pgn_annotations()`.

## [1.9.3] - 2026-04-13
### Changed
- Lösungs-Spoiler enthält jetzt auch die PGN-Kommentare (Erklärungen
  zu den Zügen). Vorher war `comments=False`; alle Lösungs-Exporter
  (normal, blind, /train, endless) auf `comments=True` umgestellt.

## [1.9.2] - 2026-04-13
### Fixed
- „Ganze Partie" wurde auch gesendet, wenn der Kontext keine Züge vor
  der Puzzle-Stellung enthält (Rückgabe `*`). `_prelude_pgn()` gibt
  jetzt leeren String zurück, wenn kein echtes Vorspiel existiert.

## [1.9.1] - 2026-04-13
### Added
- Wenn `/puzzle user:@Name` verwendet wird, erscheint in der DM des
  Empfängers vor dem Rätsel: „**<Absender>** schickt dir ein Rätsel 🧩".

## [1.9.0] - 2026-04-13
### Added
- `/puzzle user:@Name` — Puzzle an einen anderen User schicken. Der
  optionale `user:`-Parameter akzeptiert ein Discord-Member. DM,
  Lichess-Studie und Stats werden dann dem Empfänger zugeordnet.
  Ohne `user:` bleibt alles wie bisher (an sich selbst). Bestätigung
  nennt den Empfänger, z.B. „✅ 2 Puzzle(s) wurde(n) an @Max per DM
  gesendet."

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
