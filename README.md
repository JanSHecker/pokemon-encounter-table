# Gemeinsame Pokémon-Encounter-Tabelle

Gekoppelte Nuzlocke-Soullink-Tabelle für **Marc**, **Nicolai** und **KNEV** – über mehrere
Editionen und Runs hinweg.

- Live-Tabelle: https://bronze-brawl.de/encounter-table/
- Öffentliche API: https://bronze-brawl.de/encounter-table/api/
- API-Dokumentation: https://bronze-brawl.de/encounter-table/api/docs

Unterstützte Spiele: **Pokémon Platin** und **Pokémon Schwarz 2 / Weiß 2**.

## Was die Tabelle kann

- Ein neuer Run enthält **alle Orte des Spiels** in Spielreihenfolge als offene Zeilen.
- Beim Eintragen stehen nur die Pokémon zur Auswahl, die **an diesem Ort fangbar** sind.
- Ein gemeldeter Tod **koppelt automatisch die ganze Reihe** – alle drei gelten als tot.
- Wird eine Zeile auf **Verloren** gesetzt, tragen alle drei „Encounter verloren“.
- Die **Level-Caps** des Spiels stehen über der Tabelle, das jeweils nächste ist hervorgehoben.
- Arten, die ein Spieler im Run schon gefangen hat, sind in der Auswahl mit ⚠ markiert.
- Ganz rechts steht pro Zeile ein freies **Notizfeld**.
- Jede Änderung landet in der **Historie** und lässt sich einzeln zurücknehmen.
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
export ENCOUNTER_GAMES_PATH='/pfad/zu/data/games'   # optional
```

Ist die Variable gesetzt, brauchen alle Schreibzugriffe wieder einen Bearer-Token.

| Endpunkt | Zweck |
| --- | --- |
| `GET /games`, `GET /games/{id}` | Spielkatalog mit Orten, Pokémon und Level-Caps |
| `GET /runs`, `GET /runs/{id}` | Runs und ihre Zusammenfassung |
| `GET /encounters` | Zeilen des aktuellen Runs |
| `PATCH /encounters/{id}` | Zeile ändern (auch `/runs/{run}/encounters/{id}`) |
| `POST /runs` | Run anlegen, standardmäßig aus dem Katalog vorbefüllt |
| `GET /stats` | Statistik, optional `?run_id=` oder `?game_id=` |
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
- Spieler werden intern als IDs geführt (`marc`, `nicolai`, `knev`); die Anzeigenamen stehen in
  `players` und lassen sich ändern, ohne Zeilen anzufassen.
