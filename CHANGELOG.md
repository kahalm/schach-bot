# Changelog

Alle nennenswerten Änderungen am Schach-Bot. Format angelehnt an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionierung nach
[SemVer](https://semver.org/lang/de/) (`major.minor.bugfix`).

## [2.26.0] - 2026-04-28
### Changed
- `/turnier_pending` zeigt pro pending Event ein eigenes Embed mit Freigeben/Ablehnen-Buttons (statt einer einfachen Liste ohne Aktionen)
- Gemeinsame Embed-Bau-Logik in `_build_pending_embed()` extrahiert (Review-DMs + `/turnier_pending` nutzen denselben Code)

## [2.25.1] - 2026-04-28
### Added
- Erfolgreiche Wochenpost-Reminder-DMs werden jetzt im Log erfasst (`Wochenpost-Reminder an User X gesendet.`)

## [2.25.0] - 2026-04-28
### Changed
- Neue Turniere werden IMMER als `approved: false` angelegt und muessen per Review-DM freigegeben werden — kein automatisches Posten mehr, weder bei `/turnier_parse` noch beim taeglichen Auto-Parse

## [2.24.0] - 2026-04-28
### Fixed
- Rallye-Reminder pingte niemanden — Mentions standen im Embed-Description statt als `content` (Discord ignoriert Mentions in Embeds)
- `_write_health()` crashte bei `float('inf')` Latenz (vor erstem Heartbeat-ACK) mit `OverflowError` — verhinderte Start von `puzzle_task` und `_health_loop`
- Task-Loops (`_wochenpost_loop`, `_wochenpost_sub_loop`, `_rallye_reminder`) hatten kein top-level try/except — eine Exception killte den Loop permanent und lautlos
- `_reminder_loop` crashte wenn `reminder.json` valides JSON aber kein Dict enthielt (z.B. `[]`) — isinstance-Guard ergaenzt
- `dm_log.log_incoming()` blockierte den Event-Loop (synchroner `atomic_update` ohne `to_thread`)
- `upload_to_lichess` kuerzte Chapter-Name nicht auf 70 Zeichen — Lichess-API konnte rejecten (im Multi-Upload war es korrekt)
- Inkonsistenter PGN-Export: Single-Upload nutzte `comments=False`, Multi-Upload `comments=True` — Gamebook-Inhalte waren unterschiedlich
- `/puzzle id:X:blind:N` trackte keine `blind_puzzles`-Statistik — `stats.inc()` fehlte
- `pick_random_lines` blockierte den Event-Loop (synchroner PGN-Parse + JSON-I/O) — auf `asyncio.to_thread` umgestellt
- Buch-Nummerierung divergierte zwischen `/kurs` (aus geparsten Lines) und `/train`/`/puzzle buch:N` (aus Dateisystem) — `/kurs` nutzt jetzt `_list_pgn_files()`
- `/schachrallye_add` Bestaetigung war nicht ephemeral (oeffentlich sichtbar)
- `turnier_buttons.py` Reject-Pfad schrieb bei fehlender turnier.json ein leeres `{}` statt der Default-Struktur
- `/test modus:lichess` zeigte Cooldown permanent als aktiv (pruefte Datei-Existenz statt `_lichess_rate_limited()`)
- Context-Chapter-Name konnte 78 Zeichen werden (Prefix "Partie: " + 70 Zeichen) — Limit korrekt berechnet
- `_SuppressEmptyFen.write()` gab `None` statt `int` zurueck — verletzte `TextIO`-Protokoll

## [2.23.0] - 2026-04-28
### Fixed
- `_post_approved_event` aus `setup()`-Closure auf Modul-Ebene verschoben — Import aus `turnier_buttons.py` schlug fehl, Approve-Flow war komplett kaputt
- Shallow Copy von `_DEFAULT` durch `_fresh_default()` ersetzt — verschachtelte Listen/Dicts wurden zwischen allen Aufrufen geteilt (Shared-State-Bug)
- `TurnierReviewView` wird jetzt pro Reviewer-DM neu erstellt — Discord.py bindet eine View an eine Nachricht, eine geteilte Instanz fuer mehrere DMs funktioniert nicht
- `/wochenpost_sub user:@someone` ohne `zeit`-Parameter crashte mit `AttributeError: 'NoneType' object has no attribute 'strip'` — fehlende None-Pruefung ergaenzt

## [2.22.1] - 2026-04-28
### Added
- `/version` zeigt jetzt den Git-SHA des laufenden Builds an (`v2.22.1 (abc1234)`) — erleichtert die Identifikation von Dev-Images
- Dockerfile uebergibt `GIT_SHA` als Build-Arg/ENV, CI-Pipeline setzt ihn automatisch

## [2.22.0] - 2026-04-28
### Added
- CI-Pipeline baut bei jedem Push auf `main` ein Dev-Image (`ghcr.io/…:dev`) fuer Nutzer die immer aktuell sein wollen
- Release-Images bei Git-Tags wie bisher (`x.y.z`, `x.y`, `latest`)

## [2.21.1] - 2026-04-28
### Fixed
- `/wochenpost_sub` Admin-Ansicht zeigt jetzt Server-Nicknames statt globale Displaynamen (nutzt `guild.get_member()` statt `fetch_user()`)

## [2.21.0] - 2026-04-28
### Added
- `GUILD_ID` in `.env`: Server-ID fuer DM-Berechtigungen — Admins/Moderatoren koennen jetzt auch per DM Admin-Commands ausfuehren
- `core/permissions.set_guild_id()` zum Setzen der Heim-Server-ID
- `_display_name_cached()` bevorzugt bei fehlender Guild den Heim-Server fuer Namensaufloesung

## [2.20.2] - 2026-04-28
### Added
- Eingehende DMs werden im DM-Log mitgeschrieben (`[IN]`-Prefix zur Unterscheidung von ausgehenden Nachrichten)

## [2.20.1] - 2026-04-28
### Added
- `/wochenpost_sub` ohne Parameter zeigt jetzt den Status an: normaler User sieht eigenen Abo-Status (aktiv/inaktiv + Uhrzeit), Admins sehen alle aktiven Abos

## [2.20.0] - 2026-04-27
### Added
- Puzzle-Kontext fuer KI-Chat: Claude kennt jetzt das zuletzt gestellte Puzzle (Buch, Kapitel, FEN, Loesung, Schwierigkeit) und kann sinnvoll darauf eingehen
- System-Prompt wird dynamisch um Puzzle-Metadaten erweitert (per-User mit Channel-Fallback)
- Bei Blind-Puzzles wird die Loesung bewusst nicht mitgegeben

## [2.19.1] - 2026-04-27
### Changed
- KI-Chat vorerst fuer alle User freigeschaltet (Whitelist-Check deaktiviert)

## [2.19.0] - 2026-04-27
### Added
- Chat-Spark Eskalation: Sarkasmus steigert sich mit jeder Wochenpost-Erinnerung (4 Stufen: Augenzwinkern → frech → Drill-Sergeant → gnadenlos theatralisch)

## [2.18.2] - 2026-04-27
### Changed
- Wochenpost-DM-Logik in `_build_reminder_text()` extrahiert — /test und der produktive Loop nutzen jetzt dieselbe Funktion, keine Duplikation mehr

## [2.18.1] - 2026-04-27
### Fixed
- /test Wochenpost-Reminder nutzt jetzt auch Chat-Spark fuer whitelisted User (war eigener Code-Pfad ohne Claude-Integration)

## [2.18.0] - 2026-04-27
### Added
- Sarkastischer Chat-Spark bei Wochenpost-Reminders: whitelisted Chat-User erhalten eine von Claude generierte, sarkastisch-motivierende Nachricht statt nur einen Spruch
- Fallback auf normalen Spruch wenn User nicht whitelisted, kein API-Client, oder bei Fehler

## [2.17.1] - 2026-04-27
### Fixed
- KI-Chat Model-ID korrigiert: `claude-sonnet-4-20250514` (retired) → `claude-sonnet-4-6`

## [2.17.0] - 2026-04-27
### Added
- KI-Schachtrainer per DM: whitelisted User koennen dem Bot per DM schreiben und erhalten Antworten von einem strengen, lustigen Schachtrainer (Claude API)
- `/chat_whitelist [user] [aktion]` — Admin: User zur Chat-Whitelist hinzufuegen/entfernen/auflisten
- `/chat_clear` — Eigene KI-Chat-Historie loeschen (jeder User)
- `commands/chat.py` — Neues Modul mit DM-Listener (`bot.listen('on_message')`), Claude API Integration, History-Management
- Feature ist optional: ohne `CLAUDE_API_KEY` in `.env` aendert sich nichts am Verhalten
- Chat-History begrenzt auf 20 Nachrichten pro User (10 Austausche)
- `anthropic>=0.40.0` als neue Dependency

## [2.16.0] - 2026-04-27
### Added
- Turnier-Review-System: neue Turniere muessen von Reviewern freigegeben werden, bevor sie im Channel gepostet werden
- `/turnier_review` — Als Turnier-Reviewer subscriben/unsubscriben (Admin, Toggle)
- `/turnier_pending` — Alle ausstehenden (pending) Turniere anzeigen (Admin)
- `commands/turnier_buttons.py` — Persistente View mit Freigeben/Ablehnen-Buttons fuer Review-DMs
- Review-DMs an alle Reviewer bei neuen Turnieren mit Approve/Reject-Buttons
- Fallback: ohne Reviewer werden Turniere wie bisher direkt gepostet (auto-approve)
- Abwaertskompatibilitaet: existierende Events ohne `approved`-Feld gelten als freigegeben

### Changed
- `/turnier` zeigt nur noch freigegebene Events an (pending werden gefiltert)
- `/turnier_parse` zeigt "(pending)" im Status wenn Reviewer vorhanden sind
- Rallye-Reminder ignoriert pending Events
- `turnier.json` Datenmodell erweitert: `reviewers[]` (Root-Level) und `approved` (pro Event)

## [2.15.1] - 2026-04-27
### Added
- `/test` sendet nach jedem Modus automatisch Test-Reminder per DM, falls der auslösende Admin für `wochenpost_sub` oder `turnier_sub` subscribed ist (Wochenpost-Erinnerung + Turnier-Erinnerung mit nächsten Terminen)

## [2.15.0] - 2026-04-27
### Added
- `/test modus:` Parameter mit 7 Diagnose-Modi: `status` (Bot-Vitals, Latenz, Uptime, Task-Loops), `files` (JSON-Integritaet), `pgn` (PGN-Parsing + books.json-Abgleich), `lichess` (Token + API-Check), `rendering` (Board-Bild mit Vorschau), `assets` (SVG-Pieces, Sprueche, Icons), `snapshots` (bisheriger Default)
- `CheckResult` NamedTuple und `_build_result_embed()` fuer einheitliche Diagnose-Embeds
- `bot._task_loops` Dict: alle Task-Loops (puzzle_task, health_loop, reminder, wochenpost, wochenpost_sub, rallye_reminder, auto_parse) zentral registriert fuer `/test modus:status`
- 30 neue Tests in `test_cmd_admin.py` fuer alle /test-Modi

## [2.14.1] - 2026-04-27
### Fixed
- `/log` Interaction Timeout: defer() vor dem File-Read verhindert "Unknown interaction" nach 3s

## [2.14.0] - 2026-04-27
### Added
- `safe_render_board()` async Helper ersetzt 4x dupliziertes try/except Board-Rendering
- Dedizierter ThreadPoolExecutor fuer Lichess-Uploads (verhindert Default-Pool-Saturation)

### Changed
- Endless-Modus: `_sending`-Guard verhindert Doppel-Sends bei schnellen Klicks
- `_read_log_tail` nutzt `deque` statt `readlines()` (speicherschonend)
- `rotate_log` schreibt atomar via tempfile + `os.replace`
- HTTP-Session in `rendering.py` mit Pooling-Limit (2 Connections)
- User-Agent Header bei `_fetch_termine` (tirol.chess.at)
- DM-Log schreibt nach dem Send (fire-and-forget), blockiert nicht mehr die DM-Zustellung
- `_paginate_lines` respektiert Discord-Limit von 10 Embeds pro Nachricht
- Regex-Patterns in `library.py` `_auto_tag` vorkompiliert
- `greeted`-Lookup als Set (O(1) statt O(n))
- Log-Level fuer User-Studie-Lookups von info auf debug reduziert
- `_puzzle_msg_ids` Thread-Safety-Constraint dokumentiert

## [2.13.1] - 2026-04-27
### Changed
- Wochenpost-Erinnerungs-DM: Spruch steht jetzt oben, darunter "Mache deine Übungen!" statt "Wochenpost-Erinnerung"

## [2.13.0] - 2026-04-27
### Added
- Lokale SVG-Schachfiguren in `assets/pieces/` — kein Netzwerk-Download mehr noetig (Fallback auf lichess.org bleibt)
- Gemeinsame `ClickTracker`-Klasse in `core/button_tracker.py` fuer Puzzle- und Wochenpost-Buttons
- Gemeinsame Datumsfunktionen in `core/datetime_utils.py` (`parse_datum`, `parse_utc`)
- PDF-Groessenlimit (25 MB) beim Wochenpost-Download
- User-Feedback bei unbehandelten Command-Fehlern (ephemeral)
- Tests fuer `build_puzzle_embed`, `dm_log`-Internals, `_SuppressEmptyFen`

### Changed
- Berechtigungspruefung einheitlich ueber `is_privileged()` (Admin oder Moderator)
- `_display_name` in `bot.py` als sync-Helper, Duplikate entfernt
- Embed-Mentions in `/schachrallye` als `content` statt im Embed (Discord pingt jetzt korrekt)
- Button-Eviction: aelteste Nachricht wird zuerst entfernt (FIFO)
- `_find_chapter_prefix` und `_list_chapters` laufen jetzt in `asyncio.to_thread`
- TOCTOU-Race-Condition im Elo-Cache von `event_log.py` behoben

### Removed
- `_is_admin`-Aliases in `wochenpost.py` und `schachrallye.py` (ersetzt durch `is_privileged`)

## [2.12.1] - 2026-04-27
### Changed
- `/wochenpost_sub zeit:` akzeptiert jetzt auch Minuten: `17`, `17:30`, `1730`, `17 30`
- Bestehende Abos ohne Minuten-Feld bleiben abwaertskompatibel (default: 0)

## [2.12.0] - 2026-04-27
### Added
- Wochenpost-Erinnerungs-DMs enthalten jetzt einen zufälligen Spruch (500 Stück in `assets/sprueche.json` — Großmeister-Zitate, lustige und motivierende Sprüche)

## [2.11.0] - 2026-04-27
### Added
- `/log [zeilen]` — Letzte N Zeilen aus `bot.log` direkt in Discord anzeigen (Admin-only, ephemeral); bei >1900 Zeichen als Datei-Attachment

## [2.10.1] - 2026-04-27
### Changed
- `/wochenpost_sub` zeigt "MEZ/MESZ" statt "Wiener Zeit" an

## [2.10.0] - 2026-04-27
### Changed
- `/wochenpost_add` akzeptiert jetzt beliebige Daten, nicht nur Freitage
- Wochenpost-Loop postet taeglich statt nur freitags
- `_next_free_friday` → `_next_free_day`: ohne Datum wird der naechste freie Tag gewaehlt

## [2.9.2] - 2026-04-27
### Fixed
- `/test` im Docker-Container: `trim_snapshots.json` war durch `.dockerignore` ausgeschlossen

## [2.9.1] - 2026-04-26
### Changed
- `/wochenpost_sub` `zeit`-Parameter nutzt jetzt Wiener Zeit (Europe/Vienna) statt UTC

## [2.9.0] - 2026-04-26
### Added
- `/wochenpost_sub [zeit] [user]` — Taeglich DM-Erinnerung an den aktuellen Wochenpost (Uhrzeit UTC 0-23, Standard: 17); Admins/Mods koennen andere User subscriben
- `/wochenpost_unsub [user]` — Wochenpost-Erinnerungen abbestellen; Admins/Mods koennen andere User unsubscriben
- Automatischer Reminder-Loop (alle 30 Min): sendet DMs an Abonnenten bis sie den Post als erledigt markieren
- Resolution-Tracking: geschafft/nicht geschafft-Klicks auf Wochenpost-Buttons stoppen die Erinnerungen
- `msg_id` und `thread_id` werden beim Posten eines Wochenposts gespeichert (fuer Button-Zuordnung und Thread-Links in DMs)

## [2.8.0] - 2026-04-26
### Added
- `/wochenpost_add` neuer `json`-Parameter fuer Batch-Anlage mehrerer Wochenposts auf einmal
- JSON-Array mit `datum` (Pflicht), `text` und `url` (optional) pro Eintrag
- Validierung aller Eintraege vor Speicherung (Datum-Format, Freitag, URL); bei Fehlern wird keiner angelegt
- Limit: max 52 Eintraege pro Batch (1 Jahr Freitage)

## [2.7.1] - 2026-04-26
### Changed
- `tests/test_commands.py` (3.318 Zeilen) aufgeteilt in 8 Dateien: `test_helpers.py` (Shared Infrastructure), 6 Domain-Dateien (`test_cmd_puzzle.py`, `test_cmd_community.py`, `test_cmd_events.py`, `test_cmd_library.py`, `test_cmd_admin.py`, `test_cmd_info.py`) und minimaler Runner
- `python tests/test_commands.py` funktioniert weiterhin identisch (395 checks, gleiche Reihenfolge)

## [2.7.0] - 2026-04-26
### Added
- Docker HEALTHCHECK: Bot schreibt alle 60s `config/health.json` (Version, Latency, Guilds, Timestamp)
- `healthcheck.py` Script prueft ob Timestamp < 120s alt ist (Exit 0/1)
- Dockerfile HEALTHCHECK Directive fuer automatische Container-Ueberwachung

## [2.6.0] - 2026-04-26
### Added
- Rolle "Moderator" hat jetzt dieselben Rechte wie Admin bei allen Bot-Commands
- Zentrale Berechtigungspruefung in `core/permissions.py` (`is_privileged`)

### Changed
- Fehlermeldung bei fehlenden Rechten zeigt "Admins/Moderatoren" statt nur "Admins"

## [2.5.3] - 2026-04-26
### Fixed
- `json_store`: `PermissionError`/`OSError` wird jetzt in `atomic_read` und `atomic_update` abgefangen (verhindert Crash bei gesperrten Dateien)
- `json_store`: Temp-Dateien erhalten `chmod 644` vor `os.replace` (behebt restriktive Permissions durch `mkstemp` im Docker-Container)

## [2.5.2] - 2026-04-26
### Fixed
- `/dm-log`, `/stats`, `/greeted`: User-Namen nur noch aus Cache statt per API-Call (behebt Dauerschleife durch Discord-Rate-Limiting bei vielen Usern)

## [2.5.1] - 2026-04-26
### Fixed
- Wochenpost-Buttons werden jetzt direkt mit der Nachricht gesendet statt per nachtraeglichem Edit (behebt fehlende Buttons)

## [2.5.0] - 2026-04-26
### Added
- Wochenpost-Buttons: 4 Reaktions-Buttons unter jedem Wochenpost (geschafft/nicht geschafft + gut/schlecht)
- Mutex-Paare wie beim Puzzle: nur eins pro Paar, Toggle bei erneutem Klick
- JSONL-Logging aller Button-Klicks in `config/wochenpost_log.jsonl` fuer spaetere Auswertung pro User
- Persistente Views: Buttons funktionieren auch nach Bot-Neustart

## [2.4.5] - 2026-04-26
### Added
- Wochenpost Startup-Catchup: verpasste Posts der letzten 7 Tage werden beim Bot-Start automatisch nachgeholt
- Aeltere verpasste Posts (>7 Tage) werden ignoriert

## [2.4.4] - 2026-04-26
### Added
- Warnung bei allen 3 Wochenpost-Commands wenn `WOCHENPOST_CHANNEL_ID` nicht gesetzt ist

## [2.4.3] - 2026-04-26
### Added
- `/wochenpost_add` mit vergangenem Datum postet sofort in den Channel (Thread + Embed)
- Zukunfts-Daten werden wie bisher fuer den Freitags-Loop vorgemerkt

## [2.4.2] - 2026-04-26
### Changed
- `/wochenpost_add` braucht keinen Titel mehr — Datum wird automatisch als Titel verwendet (dd.mm.yyyy)

## [2.4.1] - 2026-04-26
### Changed
- `/wochenpost_add` Datum ist jetzt optional — ohne Angabe wird automatisch der naechste freie Freitag gewaehlt
- Mehrere Posts hintereinander ohne Datum belegen aufeinander folgende Freitage (1.5, 8.5, 15.5 usw.)

## [2.4.0] - 2026-04-26
### Added
- Wochenpost-Feature: woechentliche Link/PDF-Posts als Thread (Freitag 18:00 UTC)
- `/wochenpost` — Alle geplanten und vergangenen Wochenposts anzeigen (Admin)
- `/wochenpost_add` — Neuen Wochenpost anlegen mit Datum, Titel, Text, URL, PDF (Admin)
- `/wochenpost_del` — Wochenpost loeschen (Admin)
- Scheduled Loop: postet automatisch freitags 18:00 UTC in konfigurierten Channel als Thread
- PDF-Attachments werden beim Add gespeichert und beim Posten als Datei angehaengt
- ENV-Variable `WOCHENPOST_CHANNEL_ID` fuer den Ziel-Channel
- Tests: Wochenpost add/del/list, Loop-Logik, Admin-Enforcement, Validierung

## [2.3.0] - 2026-04-26
### Fixed
- `pick_random_lines` resettet jetzt nur den eigenen Pool statt alle Buecher (#20)
- `/kurs` Exception-Handler loggt jetzt den Fehler (`log.exception`)
- `/puzzle anzahl:100` gibt klare Fehlermeldung statt stiller Fehlschlaege (Limit 1-20)
- `/endless` defer vor Session-Start (kein verwaister State bei Netzwerkfehler)
- `_is_admin` Docstring korrigiert (False in DMs, nicht True)

### Added
- Duplikat-URL-Erkennung in `/resourcen` und `/youtube`
- Turnier-Auto-Prune: Events aelter als 90 Tage werden automatisch entfernt
- `/wanted` Liste zeigt dynamisch aufgeloeste Usernamen statt statischer Snapshots
- Tests: puzzle/buttons.py Click-Logik (Mutex, Toggle, Eviction, Counter)
- Tests: `_format_blind_moves` (Weiss/Schwarz-Start, Zugnummern)
- Tests: Collection Max-Entries-Limit und Input-Truncation
- Tests: Duplikat-URL-Ablehnung
- Tests: Turnier-Prune-Logik
- Tests: Posted-Reset-per-Pool-Logik
- Tests: `/puzzle anzahl` Validierung

### Removed
- Dead Import `CONFIG_DIR` in `puzzle/selection.py`
- Dead Imports `chess`/`chess.pgn` in `puzzle/commands.py`

## [2.2.0] - 2026-04-26
### Security
- Pickle-Cache (`puzzle_lines.pkl`) komplett entfernt — keine unsichere Deserialization mehr
- Runtime Admin-Checks auf allen Admin-Commands (schuetzt gegen Server-Integrations-Override)
- `/blind user:` erfordert jetzt Admin-Rechte (verhindert DM-Spam an andere User)
- Exception-Details werden nicht mehr an User geleakt (nur noch generische Fehlermeldung)
- User-Input in `/wanted`, `/resourcen`, `/youtube` auf 500 Zeichen begrenzt
- Dockerfile: Bot laeuft als non-root User (`botuser`)
- Cooldowns (10s) auf `/puzzle`, `/blind`, `/endless`
- SFTPGo-Passwort in Spoiler-Tags versteckt
- Books-Pfad wird nicht mehr in Fehlermeldungen an User angezeigt
- Reaction-Log wird automatisch taeglich rotiert
- Cooldown-Error-Handler zeigt freundliche Wartezeit-Meldung

## [2.1.0] - 2026-04-26
### Fixed
- Reminder-Loop crashte bei korruptem `hours: 0` in JSON (ZeroDivisionError fuer alle User)
- DM-Log: redundanter asyncio.Lock entfernt, der alle DM-Sends serialisierte
- Event-Log `rotate_log`: Read+Write jetzt komplett im Lock (keine verlorenen Eintraege mehr)
- Turnier-Import Dedup jetzt nach (Datum, Name) statt nur Datum (zwei Turniere am selben Tag moeglich)
- `_parse_utc` robust gegen Z-Suffix und naive Timestamps in Reminder-Daten
- Doppelter `_parse_stored`-Aufruf in Schachrallye/Turnier-Listen eliminiert

### Changed
- `library.py` nutzt jetzt `atomic_write` statt direktem File-Write (crash-sicher)
- `event_log.read_all` nutzt `deque(maxlen=...)` statt komplettes File in Memory
- PGN-Parser bricht nach 50 aufeinanderfolgenden Parse-Fehlern pro Datei ab (kein Endlos-Loop)
- Piece-Download nutzt `requests.Session` fuer TCP-Connection-Reuse

## [2.0.6] - 2026-04-26
### Fixed
- `_display_name()` findet Server-Nicks auch aus DM-Kontext (iteriert ueber alle Bot-Guilds statt nur interaction.guild)

## [2.0.5] - 2026-04-26
### Changed
- `/dm-log` ohne Parameter zeigt kompakte Uebersicht (eine Zeile pro User) statt alle DM-Inhalte
- PGN-Dateien aus Git-History entfernt und in `.gitignore` aufgenommen

## [2.0.4] - 2026-04-26
### Changed
- Admin-Commands `/greeted`, `/dm-log`, `/stats` zeigen Server-Nickname statt globalem Display-Name
- Neuer Helper `_display_name()` nutzt `guild.get_member`/`guild.fetch_member` fuer Server-Nicks

## [2.0.3] - 2026-04-26
### Fixed
- Dockerfile: libcairo2-dev statt libcairo2 (Dev-Header fuer pycairo Build)

## [2.0.2] - 2026-04-26
### Fixed
- Dockerfile: build-essential und pkg-config fuer svglib/reportlab Kompilierung

## [2.0.1] - 2026-04-26
### Added
- `/turnier_sub`, `/turnier_unsub` Commands mit Tag-basiertem Ping bei neuen Turnieren
- `/turnier_sub` ohne Parameter zeigt eigene Abos
- Automatischer Turnier-Import taeglich um 18:00 UTC
- Tags: jugend, senioren, klassisch (auto-erkannt beim Import)
- Willkommensnachricht um neue Features erweitert
- 234 Command-Tests

### Changed
- `RALLYE_CHANNEL_ID` → `TOURNAMENT_CHANNEL_ID` (Fallback auf alten Namen)
- `/schachrallye_sub` erwaehnt jetzt Ping + 7-Tage-Reminder
- Channel-Posts fuer alle neuen Turniere (nicht nur Nicht-Rallye)

### Fixed
- HTML-Parser: fehlende Leerzeichen bei `<br>`-Tags
- Turniernamen-Bereinigung (Start-Uhrzeiten, Chess-Results-Suffix)
- URL-Validierung fuer Embed-Links (Discord 400 Bad Request)

## [2.0.0] - 2026-04-26
### Added
- Dockerfile, docker-compose.yml und .dockerignore fuer Container-Deployment
- README um Docker-Sektion, alle aktuellen Commands und Konfigurationsvariablen erweitert

## [1.45.8] - 2026-04-26
### Changed
- `RALLYE_CHANNEL_ID` in `.env` umbenannt zu `TOURNAMENT_CHANNEL_ID` (Fallback auf alten Namen fuer bestehende Configs)

## [1.45.7] - 2026-04-26
### Changed
- Willkommensnachricht um `/turnier`, `/turnier_sub`, `/schachrallye` und `/wanted` erweitert

## [1.45.6] - 2026-04-26
### Added
- Automatischer Turnier-Import taeglich um 18:00 UTC (neue Turniere werden im Channel gepostet mit Subscriber-Mentions)

## [1.45.5] - 2026-04-26
### Added
- `/turnier_sub` ohne Parameter zeigt die eigenen abonnierten Tags an

## [1.45.4] - 2026-04-26
### Added
- Neuer Tag beim Turnier-Import: `klassisch` (matcht "Open" im Turniernamen)

## [1.45.3] - 2026-04-26
### Added
- Neue Tags beim Turnier-Import: `jugend` (Jugend*, U08-U18) und `senioren` (Senior*)

## [1.45.2] - 2026-04-26
### Fixed
- Turnier-Channel-Post: ungueltige URLs (z.B. `http://Rallye Jenbach: ...`) werden nicht mehr als Embed-URL gesetzt (Discord 400 Bad Request)
- `/turnier` Listenansicht: ungueltige Links werden nicht mehr als Markdown-Link gerendert
- HTML-Parser: `<br>`-Tags erzeugen jetzt ein Leerzeichen (verhindert Verkettungen wie "ZirlZirl")
- Name-Cleanup beim Import: "Start: HH Uhr", "HH:MM Uhr Turnierbeginn" und "auf Chess-Results" werden automatisch entfernt

## [1.45.1] - 2026-04-26
### Fixed
- Neue Rallye-Turniere werden jetzt auch im Channel gepostet (vorher nur Nicht-Rallye-Events)

## [1.45.0] - 2026-04-26
### Added
- `/turnier_sub <tag>` — Fuer Turnier-Tags subscriben (z.B. schnellschach, blitz, 960, schachrallye); bei neuen Turnieren mit passendem Tag wird man im Channel gepingt
- `/turnier_unsub <tag>` — Turnier-Tag-Abo abbestellen
- Channel-Posts bei neuen Turnieren enthalten jetzt Mentions fuer alle passenden Tag-Subscriber

### Changed
- `/schachrallye_sub` Bestaetigungs-Nachricht und DM erwaehnen jetzt beide Features (Ping bei neuen Turnieren + 7-Tage-Erinnerung)

## [1.44.3] - 2026-04-26
### Changed
- `/schachrallye_parse` umbenannt zu `/turnier_parse` (passt besser, da beide Kategorien importiert werden)

## [1.44.2] - 2026-04-26
### Changed
- Neue Turniere werden einzeln im Channel gepostet (je ein Embed pro Turnier statt eine Sammel-Nachricht)
- Turnier-Embed: Name als klickbarer Titel (Link), Datum + Ort + Tags in der Beschreibung

## [1.44.1] - 2026-04-26
### Added
- Neue Tags beim Turnier-Import: `schnellschach`, `blitz`, `960` (automatisch aus Turniernamen erkannt)

## [1.44.0] - 2026-04-26
### Changed
- Rallye- und Turnier-Daten in einer einzigen `turnier.json` zusammengefuehrt (statt getrennte `schachrallye.json` + `turniere.json`)
- Events haben jetzt ein `tags`-Feld — erster Tag: `schachrallye` (weitere koennen folgen)
- Subscribers sind jetzt tag-basiert: `subscribers.schachrallye` statt flache Liste
- `/turnier` Display komplett ueberarbeitet: einzeilig, kompakt, gut scannbar (`Datum` **Name** · Ort)
- Lange Ort-Beschreibungen werden automatisch gekuerzt
- HTML-Parser: Space vor `<a>`-Text verhindert "NameAusschreibung"-Verkettung
- "Ausschreibung"/"Anmeldung"-Artefakte werden aus Turniernamen entfernt

### Fixed
- `/schachrallye_parse` Followup nutzt jetzt Embed statt Content (Discord 2000-Zeichen-Limit, 400 Bad Request)
- Embed-Beschreibung bei Channel-Post und Followup auf 4096 Zeichen begrenzt

### Added
- Test: DM-Fehler bei Subscribe wird korrekt als Warning geloggt (kein Crash)
- Test: Tags-System und einheitliche JSON-Struktur geprueft
- CLAUDE.md: Bug-First-Test-Regel (bei gemeldeten Bugs erst Test, dann Fix)

## [1.43.1] - 2026-04-26
### Added
- Links aus tirol.chess.at werden beim Import erfasst und in `/turnier` als klickbare Markdown-Links angezeigt
- Neue Turniere werden beim Parse automatisch im Rallye-Channel gepostet

### Changed
- OeM U08/U10 und U12/U14 werden beim Import automatisch gefiltert (neben Training)

## [1.43.0] - 2026-04-26
### Added
- `/turnier` — Alle zukuenftigen Turniere anzeigen (aus tirol.chess.at/termine/)
- `/schachrallye_parse` importiert jetzt auch Turniere in `config/turniere.json`
- Datumsbereich-Parsing fuer mehrtaegige Turniere (z.B. `20.-24.05.2026`)
- Eintraege mit "training" im Titel werden beim Import automatisch gefiltert

## [1.42.2] - 2026-04-26
### Added
- DM-Benachrichtigung bei Schachrallye-Subscribe: User erhaelt Info ueber Termine, Unsub-Moeglichkeit und 7-Tage-Erinnerung

## [1.42.1] - 2026-04-26
### Added
- `/schachrallye_parse` — Rallye-Termine automatisch von tirol.chess.at/termine/ importieren (Admin)
  - HTML-Parser filtert Eintraege mit "Rallye" im Titel
  - Duplikat-Erkennung ueber Datum, kein doppeltes Importieren

## [1.42.0] - 2026-04-26
### Added
- `/schachrallye` — Alle zukuenftigen Schachrallye-Termine anzeigen
- `/schachrallye_add` — Neuen Termin anlegen (Admin, Datum als TT.MM.JJJJ)
- `/schachrallye_del` — Termin loeschen (Admin)
- `/schachrallye_sub` — Fuer Rallye-Erinnerungen subscriben (mit optionalem User-Param fuer Admins)
- `/schachrallye_unsub` — Rallye-Erinnerungen abbestellen
- Automatische Erinnerung 7 Tage vor jedem Termin im konfigurierten Channel (RALLYE_CHANNEL_ID)

## [1.41.6] - 2026-04-26
### Added
- `/dm-log` Admin-Command: DM-Log ephemeral im Discord anzeigen (alle User oder gefiltert nach User)

## [1.41.5] - 2026-04-26
### Added
- `tests/test_stats.py`: 12 Unit-Tests fuer `core/stats.py` — inc, get, get_all, negatives Delta, Multi-User

## [1.41.4] - 2026-04-26
### Added
- `tests/test_event_log.py`: 18 Unit-Tests fuer `core/event_log.py` — log_reaction, read_all, Limit, Rotation, Elo-Cache mit TTL

## [1.41.3] - 2026-04-26
### Added
- `tests/test_buttons.py`: 22 Unit-Tests fuer `puzzle/buttons.py` — _apply_click, _count, Mutex-Paare, Multi-User, LRU-Eviction, PuzzleView

## [1.41.2] - 2026-04-26
### Added
- `tests/test_selection.py`: 27 Unit-Tests fuer `puzzle/selection.py` — PGN-Listing, Linien-Cache, Chapter-Helpers, Random/Blind-Books, find_line_by_id, pick_sequential

## [1.41.1] - 2026-04-26
### Added
- `tests/test_state.py`: 36 Unit-Tests fuer `puzzle/state.py` — Msg-Registry, Ignore, Chapter-Ignore, Endless, Persistence

## [1.41.0] - 2026-04-26
### Added
- `tests/test_json_store.py`: 22 Unit-Tests fuer `core/json_store.py` — lock_for, atomic_read/write/update, Thread-Safety

## [1.40.6] - 2026-04-26
### Fixed
- /greeted + /stats: Embed-Paginierung bei >4096 Zeichen statt stiller Truncation (8.1/8.2)
- /kurs: Buch-Liste auf 25 Felder begrenzt mit Footer-Hinweis (8.3)

## [1.40.5] - 2026-04-26
### Changed
- `bot.py`: `json_store`-Imports auf Top-Level verschoben — 3x In-Function-Import entfernt (5.1)
- `lichess.py`: `_auth_headers()` Helper extrahiert — Auth-Header-Konstruktion an einer Stelle (5.2)
- `test.py`: `self.values` Bounds-Check vor Zugriff auf `[0]` (5.3)
- `library.py`: Jahr-Tie-Breaking deterministisch — hoechstes Jahr gewinnt bei Gleichstand (5.4)

## [1.40.4] - 2026-04-26
### Fixed
- Elo-Cache Zugriff unter `_log_lock` — Race-Condition bei parallelen Reactions behoben (3.1)
- Pickle-Cache in `selection.py` unter File-Lock via `_lock_for` (3.2)
- `find_line_by_id` Laengenlimit (200 Zeichen) gegen DoS-artige Suchen (4.2)
- URL-Validierung in `_collection.py` mit `urlparse` statt nur Prefix-Check (4.3)

## [1.40.3] - 2026-04-26
### Fixed
- TOCTOU in Greeting: nur `atomic_update` mit `nonlocal`-Flag — doppelte Begruessung unmoeglich (1.3)
- `log.exception('puzzle_task')` ohne redundantes `%s` (1.6)
- `asyncio.gather` mit `return_exceptions=True` in /greeted und /stats (2.4)
- `_get_piece()` mit Retry bei Netzwerk-Fehler (2.5)
- `svg2rlg` None-Check — kaputter SVG gibt klare Fehlermeldung (2.6)
- `_load_library()` loggt Warning bei korrupter JSON statt stiller Rueckgabe (2.7)
- Sidecar-Author: `str()` Typeguard gegen int/None in `join()` (2.8)
- `fromisoformat` in /elo mit try-except gegen korrupte Timestamps (2.9)

## [1.40.2] - 2026-04-26
### Fixed
- `CHANNEL_ID`, `PUZZLE_HOUR`, `PUZZLE_MINUTE`: try-except um int-Konvertierung — klare Fehlermeldung statt ValueError-Crash (2.1/2.2)
- `tree.sync()` mit Retry+Backoff (4 Versuche, 0/5/15/30s) — Bot startet auch bei Netzwerk-Problemen mit Commands (2.3)

## [1.40.1] - 2026-04-26
### Fixed
- `find_line_by_id`: Suffix-Match nur an `:`-Grenze — `"3"` matcht nicht mehr `"book:13"` (1.1)
- `upload_many_to_lichess`: `enumerate()` statt `list.index()` — korrekte Kapitel-Zuordnung bei Duplikaten (1.2)

## [1.40.0] - 2026-04-26
### Changed
- CLAUDE.md: Architektur-Tabelle aktualisiert (puzzle/ Module, wanted.py, _collection.py)
- CLAUDE.md: `POST_HOUR`/`POST_MINUTE` → `PUZZLE_HOUR`/`PUZZLE_MINUTE` (matcht .env.example)
- `log_setup.py`: Idempotent-Guard gegen doppeltes Handler-Wrapping
- Unused `import io` aus `processing.py` entfernt

## [1.39.0] - 2026-04-26
### Added
- Tests fuer `_parse_index_entry` (6 Checks), `_auto_tag` (7 Checks),
  `build_library_catalog` (6 Checks) in `test_commands.py`
- Admin-Enforcement-Tests: `/puzzle user:@X` non-admin, `/blind` Validierung
  (anzahl/buch), `/reminder buch:-1`
### Changed
- `_patch_file_constant` schlaegt jetzt laut fehl statt Fehler zu verschlucken

## [1.38.0] - 2026-04-26
### Changed
- **Performance**: Regex in `processing.py` auf Modul-Ebene vorkompiliert (6.6)
- **Performance**: Font-Cache in `rendering.py` — kein Dateisystem-Scan pro Render (6.7)
- **Performance**: `_is_chapter_ignored` O(1) Set-Lookup statt O(n) Iteration (6.9)
- **Performance**: Elo-Wert in `event_log.py` 60s gecached (6.4)
- **Performance**: `read_all()` begrenzt auf 50.000 Eintraege + `rotate_log()` (6.2/6.3)

## [1.37.0] - 2026-04-26
### Fixed
- `_find_game()` (test.py): Endlosschleife bei Parse-Fehlern verhindert (max 50 Fehler)
- `_load_snapshots()` (test.py): Klare Fehlermeldungen bei fehlender/korrupter Datei
- `/blind`: Validierung fuer `moves` (1–50), `anzahl` (1–20) und `buch` (nicht negativ)
- `/reminder`: `buch`-Parameter darf nicht negativ sein
- `_collection.py`: Discord-25-Felder-Limit bei >25 Eintraegen (Multi-Embed)
- `dm_log.install()`: Idempotent-Guard verhindert rekursive Monkey-Patch-Kette
- `post_blind_puzzle`: Thread-Channel-Check (kein `create_thread` auf bestehenden Thread)

## [1.36.0] - 2026-04-26
### Changed
- **Duplikation**: `resourcen.py` und `youtube.py` nutzen jetzt generisches
  `commands/_collection.py` — ~95% Code-Duplikation eliminiert
- **Duplikation**: `PUZZLE_HOUR`/`PUZZLE_MINUTE`/`CHANNEL_ID` aus `puzzle/commands.py`
  entfernt (nur noch in `bot.py` definiert, waren im Puzzle-Paket unbenutzt)
- **Duplikation**: `LICHESS_API_TIMEOUT` in `rendering.py` durch eigene
  `_PIECE_DOWNLOAD_TIMEOUT`-Konstante ersetzt (klarer Kontext)
- Unused `import os` aus `puzzle/commands.py` entfernt

## [1.35.0] - 2026-04-25
### Fixed
- `on_member_join` traegt User jetzt in greeted-Liste ein (kein Doppel-Willkommen mehr)
- Reminder-next wird nur noch bei erfolgreichem Send vorgerueckt (User verpasst
  Reminder nicht mehr still bei Fehler); Fehler-Loglevel auf WARNING erhoeht
- `/puzzle id:X` trackt jetzt Stats und speichert User-Study-ID zurueck
- Lichess-Fallback auf `/api/import` wird jetzt explizit geloggt
- `lichess.py`: `fromtimestamp()` nutzt jetzt UTC statt Lokalzeit
- `puzzle_task`: `log.exception` statt `log.error` (Traceback wird jetzt erhalten)

## [1.34.0] - 2026-04-25
### Fixed
- **Blocking I/O**: `on_message` DM-Handling nutzt jetzt `asyncio.to_thread`
  fuer JSON-Dateizugriffe (blockiert nicht mehr den Event-Loop bei jeder DM)
- **Blocking I/O**: `/kurs` — `load_all_lines()`, `load_puzzle_state()` und
  `read_all()` laufen jetzt in Threads
- **Blocking I/O**: `/train` und `/next` — schwere File-I/O-Aufrufe
  (`load_all_lines`, `pick_sequential_lines`) in Threads ausgelagert
- **Blocking I/O**: `/greeted` und `/stats` — JSON-Reads in Threads

## [1.33.0] - 2026-04-25
### Fixed
- **Race Conditions**: `_set_user_study_id`, `_set_user_training`, `_clear_user_training`
  nutzen jetzt `atomic_update` statt separatem `_load`/`_save` (kein Datenverlust mehr)
- **Race Conditions**: `/wanted` (vote, add, delete), `/resourcen`, `/youtube`, `/reminder`
  nutzen jetzt `atomic_update` statt `atomic_read`+`atomic_write`
- **Race Conditions**: Reminder-Loop aktualisiert `next`-Felder atomar (parallele
  `/reminder`-Aenderungen gehen nicht mehr verloren)
- **Datenintegritaet**: `json_store._lock_for()` normalisiert Pfade mit `os.path.abspath()`
  (verschiedene Pfadformen fuer dieselbe Datei teilen jetzt denselben Lock)
- **Datenintegritaet**: `event_log.log_reaction()` nutzt jetzt einen Lock fuer
  thread-sichere JSONL-Appends

## [1.32.0] - 2026-04-25
### Fixed
- **Sicherheit**: Path-Traversal-Schutz in `_local_path()` (library.py) —
  manipulierte index.txt kann keine Dateien ausserhalb des Library-Ordners mehr lesen
- **Sicherheit**: `/puzzle user:@X` erfordert jetzt Admin-Rechte wenn der Zieluser
  nicht der Aufrufer selbst ist
- **Sicherheit**: URL-Validierung in `/resourcen` und `/youtube` (nur http/https)
- **Sicherheit**: Eintrags-Limit (100) fuer `/resourcen`, `/youtube` und `/wanted`
- **Sicherheit**: `/daily` Fehler-Nachricht zeigt keine internen Details mehr

## [1.31.0] - 2026-04-25
### Added
- Neues `/wanted`-Feature: Feature-Wünsche einreichen, abstimmen und verwalten
  (`/wanted`, `/wanted_list`, `/wanted_vote`, `/wanted_delete`)
- CLAUDE.md: Test-Regeln-Sektion und Command-Test-Referenzen ergänzt

## [1.30.0] - 2026-04-25
### Changed
- Refactor Phase 6, Schritt 9: Alle Caller auf direkte Sub-Modul-Imports umgestellt,
  `puzzle/legacy.py` entfernt. `puzzle/__init__.py` re-exportiert jetzt direkt aus
  den 8 Sub-Modulen (state, processing, rendering, selection, lichess, embed, posting,
  commands). Phase 6 abgeschlossen.

## [1.29.0] - 2026-04-25
### Changed
- Refactor Phase 6, Schritt 8: Slash-Commands in `puzzle/commands.py` extrahiert
  (`_cmd_puzzle`, `_cmd_buecher`, `_cmd_train`, `_cmd_next`, `_cmd_endless`,
  `_cmd_ignore_kapitel`, `setup`). `legacy.py` ist jetzt ein reiner Re-Export-Shim (~70 Zeilen).

## [1.28.0] - 2026-04-25
### Changed
- Refactor Phase 6, Schritt 7: Discord-Posting in `puzzle/posting.py` extrahiert
  (`post_puzzle`, `post_blind_puzzle`, `post_next_endless`, `_resilient_send`,
  `_send_optional`, `_upload_puzzles_async`, `_send_puzzle_followups`). `legacy.py` re-exportiert.

## [1.27.0] - 2026-04-25
### Changed
- Refactor Phase 6, Schritt 6: Lichess-API in `puzzle/lichess.py` extrahiert
  (`upload_to_lichess`, `upload_many_to_lichess`, `_lichess_request`, Rate-Limiting,
  `_extract_study_id`, `_export_pgn_for_lichess`). `legacy.py` re-exportiert.

## [1.26.0] - 2026-04-25
### Changed
- Refactor Phase 6, Schritt 5: Puzzle-Auswahl/Caching in `puzzle/selection.py` extrahiert
  (`load_all_lines`, `clear_lines_cache`, `pick_random_lines`, `find_line_by_id`,
  `_find_chapter_prefix`, `_list_chapters`, `_list_pgn_files`, etc.). `legacy.py` re-exportiert.

## [1.25.0] - 2026-04-25
### Changed
- Refactor Phase 6, Schritt 4: Zustand/Persistenz in `puzzle/state.py` extrahiert
  (Puzzle-Msg-Registry, Ignore-System, Endless-Sessions, Puzzle-/Study-/Training-State,
  Books-Config-Cache). `legacy.py` re-exportiert.

## [1.24.0] - 2026-04-25
### Changed
- Refactor Phase 6, Schritt 3: `build_puzzle_embed` in `puzzle/embed.py` extrahiert.
  `legacy.py` re-exportiert.

## [1.23.0] - 2026-04-25
### Changed
- Refactor Phase 6, Schritt 2: PGN-Verarbeitung in `puzzle/processing.py` extrahiert
  (10 Funktionen: `_trim_to_training_position`, `_strip_pgn_annotations`, `_flatten_null_move_variations`,
  `_split_for_blind`, `_format_blind_moves`, `_prelude_pgn`, `_has_training_comment`,
  `_solution_pgn`, `_clean_book_name`, `_clean_pgn_for_lichess`). `legacy.py` re-exportiert.

## [1.22.0] - 2026-04-25
### Changed
- Refactor Phase 6, Schritt 1: Board-Rendering in `puzzle/rendering.py` extrahiert
  (`_svg_to_pil`, `_get_piece`, `_label_font`, `_render_board`). `legacy.py` re-exportiert.

## [1.21.0] - 2026-04-25
### Added
- Command-Tests fuer `/test`, `/bibliothek`, `/tag`, `/autor`, `/reindex`
  (21 neue Checks, gesamt 131). Alle 27 Slash-Commands haben jetzt
  mindestens einen Smoke-Test.

## [1.20.0] - 2026-04-25
### Added
- Puzzle-Command Smoke-Tests: `/puzzle`, `/kurs`, `/train`, `/next`, `/endless`,
  `/blind`, `/daily`, `/ignore_kapitel` (36 neue Checks, gesamt 110).

## [1.19.0] - 2026-04-25
### Added
- Command-Tests fuer `/reminder` (Status, aktivieren, stoppen, Validierung),
  `/announce` (Erfolg, Forbidden), `/greeted` (leer, mit Eintraegen),
  `/stats` (leer, mit Daten). 20 neue Checks, gesamt 74.

## [1.18.0] - 2026-04-25
### Added
- Command-Tests fuer `/wanted`, `/wanted_list`, `/wanted_vote`, `/wanted_delete`
  und `/release-notes` (22 neue Checks, gesamt 54).

## [1.17.0] - 2026-04-25
### Added
- `tests/test_commands.py`: Slash-Command-Testframework mit Mock-Infrastruktur
  (FakeInteraction, FakeBot, temp-CONFIG_DIR). Erste 32 Tests fuer `/help`,
  `/version`, `/elo`, `/resourcen`, `/youtube`.

## [1.16.0] - 2026-04-25
### Added
- `/wanted` Feature-Wunschliste: Vorschläge einreichen, für bestehende
  abstimmen (+1 Toggle), Liste nach Stimmen sortiert anzeigen.
- `/wanted_list` zeigt alle Wünsche als Embed (nach Votes sortiert).
- `/wanted_vote <id>` stimmt für einen Wunsch ab (Toggle).
- `/wanted_delete <id>` (Admin) löscht einen Wunsch.

## [1.15.0] - 2026-04-25
### Added
- `/greeted` (Admin): zeigt alle User, die die Begrüßungs-DM erhalten haben,
  mit aufgelösten Usernamen und IDs.

## [1.14.2] - 2026-04-25
### Changed
- `/stats`: User-Fetches jetzt parallel via `asyncio.gather` statt sequentiell
  (N+1 Problem behoben). Embed-Beschreibung wird bei >4096 Zeichen abgeschnitten.
- `/stats` nutzt jetzt `defer()` + `followup` für robuste Antwortzeiten.
- `command_prefix='!'` durch `when_mentioned` ersetzt (Prefix-Commands waren nie
  im Einsatz, `!` konnte falsch-positive Matches auslösen).

### Fixed
- Endless-Session wird jetzt bei DM-Fehler automatisch beendet statt
  endlos hängen zu bleiben.
- `/announce`: Exception-Details werden nicht mehr an User geleakt
  (generische Fehlermeldung + `log.exception()`).

## [1.14.1] - 2026-04-25
### Changed
- `puzzle/legacy.py`: 3 neue Helper-Funktionen extrahiert:
  - `_clean_book_name()` — ersetzt 9× dupliziertes `.removesuffix()`
  - `_list_pgn_files()` — ersetzt 6× dupliziertes `sorted(listdir(…))`
  - `_export_pgn_for_lichess()` — ersetzt 4× dupliziertes
    `StringExporter + _clean_pgn_for_lichess`

## [1.14.0] - 2026-04-25
### Changed
- `EMBED_COLOR` als zentrale Konstante in `core/version.py` — ersetzt 5×
  hardcoded `0x4e9e4e` in `bot.py`, `library.py`, `commands/test.py`.
- Lichess-/Discord-Limits als benannte Konstanten in `puzzle/legacy.py`:
  `_LICHESS_STUDY_NAME_MAX`, `_LICHESS_CHAPTER_NAME_MAX`,
  `_DISCORD_THREAD_NAME_MAX` — ersetzt 5× Magic Numbers.

## [1.13.3] - 2026-04-25
### Changed
- `commands/elo.py`, `commands/resourcen.py`, `commands/youtube.py`: manuelle
  `json.load/dump` durch `core.json_store` (`atomic_read`/`atomic_write`/
  `atomic_update`) ersetzt — einheitliche, thread-sichere JSON-Persistenz.
- `bot.py`: ungenutztes `import json` entfernt (DM-Greeting nutzt jetzt
  `json_store`).

## [1.13.2] - 2026-04-25
### Fixed
- `DISCORD_TOKEN`-Validierung: fehlendes Token bricht jetzt sofort mit
  klarer Fehlermeldung ab statt kryptischem Crash bei `bot.run()`.
- `PUZZLE_HOUR`/`PUZZLE_MINUTE` Range-Check (0-23 / 0-59) beim Start.
- Blind-Moves Obergrenze (max 50) gegen übermäßige Speicherallokation.
- Discord-Retry-Backoff mit Jitter gegen Thundering-Herd-Effekt.
- `_sftpgo_rel_path()` nutzt jetzt `pathlib.Path.resolve()` gegen
  Path-Traversal (Symlinks, `/../`).

## [1.13.1] - 2026-04-25
### Fixed
- Race Condition in DM-Greeting (`bot.py`): manuelles `json.load/dump` durch
  `atomic_update` aus `core/json_store` ersetzt.
- `on_ready()` feuert nur noch einmalig: Guard-Flag verhindert doppelte
  `PuzzleView`-Registrierung, `tree.sync()` und `puzzle_task.start()` bei
  Discord-Reconnects.
- `build_library_catalog()` Early-Return gibt jetzt 5-Tupel statt 4-Tupel
  zurück (passte nicht zur Signatur).
- `upload_many_to_lichess()` gibt `[]` statt `None` zurück wenn keine
  Study-ID erstellt werden konnte (Signatur: `-> list[str]`).
- Bot-Version wird jetzt im `on_ready`-Log angezeigt.

## [1.13.0] - 2026-04-25
### Added
- `core/json_store.py`: Atomare JSON-Persistenz mit per-Datei-Locks und
  `tempfile` → `os.replace`. Eliminiert Race Conditions bei gleichzeitigem
  Load-Modify-Save in `stats.py`, `dm_log.py`, `reminder.py` und allen
  JSON-Dateien in `puzzle/legacy.py`.
- Helper-Funktionen für duplizierte Patterns: `_extract_study_id()`,
  `_upload_puzzles_async()`, `_solution_pgn()`, `_send_puzzle_followups()`.
- In-Memory-Caches für `_load_ignore_list()`, `_load_chapter_ignore_list()`
  und `_load_books_config()` mit Write-Invalidierung.
- `LICHESS_API_TIMEOUT`-Modulkonstante (vorher 7× hardcoded `15`/`10`).
- Font-Fallbacks für Linux (DejaVu, Liberation) und macOS (Helvetica).

### Changed
- `_puzzle_msg_ids` und `_clicks` sind jetzt `OrderedDict` mit Cap 500 —
  älteste Einträge werden bei Überlauf automatisch entfernt (Memory Leak Fix).
- `_endless_sessions` haben jetzt `last_active`-Timestamp; Sessions >2h
  Inaktivität werden automatisch aufgeräumt (Memory Leak Fix).
- DM-Log (`core/dm_log.py`) entfernt Einträge älter als 30 Tage pro User
  bei jedem Append (Memory Leak Fix).
- `setup()` in `puzzle/legacy.py` von ~650 auf ~60 Zeilen reduziert: 6
  Command-Handler als top-level `async def` extrahiert.
- `puzzle/__init__.py`: Wildcard-Import `from .legacy import *` durch
  explizite Importliste ersetzt.
- `upload_to_lichess()`: Rekursionstiefe bei voller Studie auf max. 1
  begrenzt (verhindert Endlosrekursion).
- `CLAUDE.md`: Architektur-Sektion aktualisiert (aktuelles Modul-Layout
  statt veralteter "single file bot.py"-Beschreibung).

### Fixed
- `.gitignore`: Typo `scrennshots/` korrigiert.

## [1.12.7] - 2026-04-25
### Changed
- `/help` hat jetzt einen optionalen `bereich`-Parameter (`puzzle`,
  `bibliothek`, `community`, `info`, `admin`). Ohne Parameter wird
  eine kompakte Übersicht aller Bereiche angezeigt.

## [1.12.6] - 2026-04-25
### Changed
- README vollständig überarbeitet: aktuelle Modulstruktur, Befehle
  (inkl. Admin-only), Konfiguration, Tests.

## [1.12.5] - 2026-04-25
### Added
- `core/dm_log.py`: alle ausgehenden DMs werden pro User in
  `config/dm_log.json` mitgeschrieben (Timestamp + Textinhalt /
  Embed-Titel). Aktivierung via Monkey-Patch auf `discord.DMChannel.send`.

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
