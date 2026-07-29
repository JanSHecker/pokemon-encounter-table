# Gemeinsame Pokémon-Encounter-Tabelle

Gekoppelte Nuzlocke-Soullink-Tabelle für **Marc**, **Nicolai** und **Knev** – über mehrere
Editionen und Runs hinweg.

- Live-Tabelle: https://bronze-brawl.de/encounter-table/
- Öffentliche API: https://bronze-brawl.de/encounter-table/api/
- API-Dokumentation: https://bronze-brawl.de/encounter-table/api/docs

Unterstützte Spiele: **Pokémon Platin** und **Pokémon Schwarz 2 / Weiß 2**.

## Was die Tabelle kann

- Ein neuer Run enthält **alle Orte des Spiels** in Spielreihenfolge als offene Zeilen.
- Beim Eintragen stehen nur die Pokémon zur Auswahl, die **an diesem Ort fangbar** sind.
- Die gerade gespielten Links sind **hervorgehoben** (★, grüner Rand); der Rest ist die Box.
  Maximal sechs gleichzeitig, ein Zähler oben zeigt den Stand.
- Zeilenfarben auf einen Blick: **grün** im Team, **weiß** lebend in der Box, **grau** Encounter
  verloren, **rot** tot.
- **Sortierung** umschaltbar – Spielreihenfolge, Offene zuerst, Gefangene zuerst, Team zuerst oder
  nach Zustand gruppiert. Die Auswahl bleibt im Browser gespeichert.
- Ein gemeldeter Tod **koppelt automatisch die ganze Reihe** – alle drei gelten als tot.
- Wird eine Zeile auf **Verloren** gesetzt, tragen alle drei „Encounter verloren“.
- Die **Level-Caps** des Spiels stehen über der Tabelle, das jeweils nächste ist hervorgehoben.
- Arten, die ein Spieler im Run schon gefangen hat, sind in der Auswahl mit ⚠ markiert.
- Ein **Typenrechner** als eigene Ansicht: bis zu zwei Typen anklicken, rechts steht, was der
  Kombination wehtut. Die Generation ist umstellbar (1, 2–5, 6+) – beide Editionen liegen in 2–5,
  wo Stahl noch Geist und Unlicht resistiert und es keine Feen gibt.
- Jede Änderung landet in der **Historie** und lässt sich einzeln zurücknehmen.
- Bei einem Tod oder verlorenen Encounter wird **nach dem Schuldigen gefragt** – sonst fehlt der
  Vorfall in der Statistik. „Niemand" ist eine gültige Antwort.
- Alle Browser aktualisieren sich alle 10 Sekunden von selbst.

## Projektstruktur

| Pfad | Inhalt |
| --- | --- |
| `web/` | Frontend: `index.html`, `app.js`, `styles.css` – kein Build-Schritt |
| `api/app.py` | FastAPI-Backend: Runs, Encounter, Statistik, Historie |
| `api/test_app.py` | Tests |
| `data/encounters.json` | Datenstand als versionierbarer Snapshot |
| `data/games/*.json` | **Generierte** Spielkataloge (Orte, Pokémon, Level-Caps) |
| `tools/games/*.py` | Kuratierte Spieldefinitionen – hier wird von Hand gepflegt |
| `tools/build_game_catalog.py` | Baut aus PokeAPI-Daten die Kataloge |
| `tools/dev_server.py` | Lokaler Server: API und Frontend unter einem Origin |

## Lokale Entwicklung

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1   # bash: . .venv/bin/activate
pip install -r requirements.txt
```

```bash
.venv/Scripts/python.exe -m uvicorn tools.dev_server:app --port 8010 --reload
```

Danach läuft die Tabelle auf http://localhost:8010/encounter-table/ und die API darunter auf
`/encounter-table/api`. Geschrieben wird auf `data/encounters.local.json` (gitignored), der
committete Snapshot bleibt unangetastet.

## Tests

```bash
.venv/Scripts/python.exe -m pytest -q api/test_app.py
```

## Kataloge neu bauen

Nur nötig, wenn eine Definition unter `tools/games/` geändert wurde:

```bash
python tools/build_game_catalog.py --game platinum
```

`--all` baut alle, `--check` vergleicht nur gegen den committeten Stand (für CI). PokeAPI-Antworten
liegen in `tools/.cache/`; Cache löschen erzwingt frische Daten.

### Ein Spiel ergänzen

1. `tools/games/<spiel>.py` anlegen mit `GAME = {...}`: Orte in Spielreihenfolge und Level-Caps.
2. `python tools/build_game_catalog.py --game <id>` laufen lassen.
3. Ergebnis unter `data/games/` committen. Mehr ist nicht nötig – API und Frontend sind
   spielunabhängig.

Nicht aus PokeAPI ableitbar und deshalb Handarbeit: die Reihenfolge der Orte, die Auswahl der
relevanten Orte und die Level-Caps.

## API

Lesen ist offen. **Schreiben ist ebenfalls offen**, solange `ENCOUNTER_API_TOKEN` nicht gesetzt
ist – so gewollt, damit die Seite ohne Login funktioniert. Absichern lässt sich das jederzeit:

```bash
export ENCOUNTER_API_TOKEN='<lokal setzen, nicht committen>'
export ENCOUNTER_DATA_PATH='/var/lib/encounter-table-api/encounters.json'
export ENCOUNTER_GAMES_PATH='/pfad/zu/data/games'      # optional
export ENCOUNTER_HISTORY_PATH='/pfad/zu/history.jsonl' # optional
export ENCOUNTER_BACKUP_DIR='/pfad/zu/backups'         # optional
```

Ist `ENCOUNTER_API_TOKEN` gesetzt, brauchen alle Schreibzugriffe wieder einen Bearer-Token.

### Datensicherung

Neben dem Datenstand entstehen automatisch zwei Dinge:

- `<datenstand>-history.jsonl` – die Änderungshistorie, nur angehängt. Sie liegt bewusst **nicht**
  im Datenstand, damit sie sich nicht durch viele Schreibzugriffe verdrängen lässt.
- `backups/` – eine Kopie pro Tag (die letzten 30) sowie eine zusätzliche direkt vor jeder
  Schema-Migration.

**Vor dem ersten Deploy dieser Version**: der Produktivstand wird beim ersten Request einmalig und
unumkehrbar auf das neue Schema gehoben. Die Migrationskopie unter `backups/migration-*.json`
entsteht automatisch – eine eigene Sicherung vorher schadet trotzdem nicht.

| Endpunkt | Zweck |
| --- | --- |
| `GET /games`, `GET /games/{id}` | Spielkatalog mit Orten, Pokémon und Level-Caps |
| `GET /runs`, `GET /runs/{id}` | Runs und ihre Zusammenfassung |
| `GET /encounters` | Zeilen des aktuellen Runs |
| `PATCH /encounters/{id}` | Zeile ändern (auch `/runs/{run}/encounters/{id}`) |
| `POST /runs` | Run anlegen, standardmäßig aus dem Katalog vorbefüllt |
| `GET /stats` | Negativstatistik, optional `?run_id=` oder `?game_id=` |
| `GET /history`, `POST /history/{id}/undo` | Historie und Rücknahme |

Nützliche Parameter und Header:

- `X-Encounter-Author: marc` – optional; landet in der Historie. Die Weboberfläche schickt das
  nicht, weil es egal ist, wer editiert – für eigene Skripte ist es aber praktisch.
- `?couple=false` – Soullink-Kopplung für diesen Aufruf aussetzen (z. B. Wiederbeleben).
- `?force=true` – Pokémon speichern, das laut Katalog dort nicht vorkommt.
- `If-Match: <updated_at>` – schützt Skripte vor dem Überschreiben fremder Änderungen (412).

## Datenregeln

- Encounter sind nach Ort gekoppelt.
- Stirbt ein Pokémon einer Reihe, gelten alle drei als tot – das erzwingt die API selbst.
- Verlorene Encounter (`Encounter verloren`) gelten ebenfalls für die ganze Reihe, bleiben aber von
  bestätigten Toden getrennt. Ist jemand in der Reihe tot, hat der Tod Vorrang.
- `responsible_player` ist der Spieler, dessen Pokémon gestorben ist bzw. der den Encounter
  vergeigt hat.
- Die Statistik zählt **nur Negatives**, und immer beim Verursacher: ein verschuldeter Tod oder ein
  vergeigter Encounter ist je eine Schuld für genau den Spieler aus `responsible_player`. Ein
  gekoppelter Tod kostet die Reihe drei Pokémon, zählt aber als **ein** Tod. Fangzahlen werden
  nicht geführt.
- `in_team` markiert die Links, die gerade gespielt werden. Höchstens sechs gleichzeitig, nur
  vollständig gefangene Reihen – stirbt oder verliert eine Reihe, fliegt sie automatisch raus.
- Spieler werden intern als IDs geführt (`marc`, `nicolai`, `knev`); die Anzeigenamen stehen in
  `players` und lassen sich ändern, ohne Zeilen anzufassen.
