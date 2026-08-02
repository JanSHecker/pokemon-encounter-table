# Gemeinsame Pokémon-Encounter-Tabelle

Gekoppelte Nuzlocke-Soullink-Tabelle für **Marc**, **Nicolai** und **Knev** – über mehrere
Editionen und Runs hinweg.

- Live-Tabelle: https://bronze-brawl.de/encounter-table/
- Öffentliche API: https://bronze-brawl.de/encounter-table/api/
- API-Dokumentation: https://bronze-brawl.de/encounter-table/api/docs

Unterstützte Spiele: **Pokémon Platin**, **Pokémon Renegade Platin** und
**Pokémon Schwarz 2 / Weiß 2**. Renegade Platin ist der Hack: gleiche Orte wie Platin, eigene
Level-Caps.

## Was die Tabelle kann

**Run-Übersicht** als Startseite: alle Runs mit Fortschrittsbalken (gefangen · tot · vergeigt),
Status (**aktiv · pausiert · fertig · verkackt**, aktiv ist immer höchstens einer), Spieler-Chips
und einem Knopf zum Anlegen. Über ✎ und ✕ an der Karte lässt sich ein Run **umbenennen oder
löschen** (der letzte bleibt stehen). Spieler lassen sich hier hinzufügen und entfernen – jeder
bekommt eine Farbe und eine eigene Spalte in allen Runs.

**Run-Ansicht** mit der Encounter-Tabelle als Hauptspalte:

- Ein neuer Run enthält **alle Orte des Spiels** in Spielreihenfolge als offene Zeilen.
- Jede Zelle zeigt Sprite, Name und **Typ-Badges**; ein Klick öffnet die Auswahl. Oben stehen die
  Arten, die **an diesem Ort vorkommen**, darunter der Rest des Pokedex.
- Der **Pokéball** links schaltet die ganze Reihe ins Team – maximal sechs gleichzeitig.
- Zeilenfarben auf einen Blick: **grün** im Team, **weiß** lebend in der Box, **ocker** Encounter
  verloren, **rot** tot. Filter-Pills (Alle · Team · Box · Tot · Verloren · Offen), ein **Suchfeld
  für Orte** und die **Sortierung** (Spielreihenfolge oder nach Status) blenden den Rest aus.
- Ein gemeldeter Tod (☠) **koppelt automatisch die ganze Reihe** – alle gelten als tot, der
  Meldende wird als Schuldiger eingetragen, „↺“ macht es rückgängig.
- „verloren melden“ fragt nach dem Schuldigen und setzt die Reihe für alle auf verloren.
- Arten, die ein Spieler im Run schon gefangen hat, sind mit ⚠ markiert – das gilt für die ganze
  **Entwicklungslinie**.

Rechts daneben:

- Die **Level-Cap-Karte**: Cap des nächsten Kampfes, Typ und Ort des Gegners sowie eine Zeitleiste
  aller Kämpfe der Edition, in der sich direkt springen lässt.
- Die **Fail-Statistik**: Schuld = Tod ×2 + vergeigter Encounter, sortiert nach Schuldigstem.
- Ein **Typenrechner** mit bis zu zwei Typen: „Angriff“ zeigt die beste Coverage der Kombination,
  „Abwehr“ das Produkt beider Verteidigungswerte (also auch ×4 und ×¼). Ist ein Angriffstyp
  gewählt, markiert die Tabelle die anfälligen Pokémon rot, und unten steht, wer davon betroffen
  ist.

**Alle Browser sehen jede Änderung sofort** – trägt einer etwas ein, steht es bei den anderen in
unter einer Sekunde. Der Server meldet Änderungen über `GET /events` (Server-Sent Events); daneben
läuft weiterhin ein Poll alle 10 Sekunden als Rückfall, falls ein Proxy den Stream schluckt.
Wer gerade einen Dialog offen hat, bekommt die Änderung, sobald er ihn schließt.

## Projektstruktur

| Pfad | Inhalt |
| --- | --- |
| `web/` | Frontend: `index.html`, `app.js`, `styles.css`, `icons/` – kein Build-Schritt |
| `api/app.py` | FastAPI-Backend: Runs, Encounter, Statistik |
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
   Teilt sich das Spiel die Orte mit einem bestehenden (wie Renegade Platin mit Platin), kommt die
   Liste aus einer Datei mit führendem Unterstrich – die überspringt der Generator (`_sinnoh.py`).
2. `python tools/build_game_catalog.py --game <id>` laufen lassen.
3. Ergebnis unter `data/games/` committen und den Dienst neu starten – Kataloge werden beim Start
   gelesen und dann gecacht. Mehr ist nicht nötig: API und Frontend sind spielunabhängig.

Nicht aus PokeAPI ableitbar und deshalb Handarbeit: die Reihenfolge der Orte, die Auswahl der
relevanten Orte und die Level-Caps.

## API

Lesen ist offen. **Schreiben ist ebenfalls offen**, solange `ENCOUNTER_API_TOKEN` nicht gesetzt
ist – so gewollt, damit die Seite ohne Login funktioniert. Absichern lässt sich das jederzeit:

```bash
export ENCOUNTER_API_TOKEN='<lokal setzen, nicht committen>'
export ENCOUNTER_DATA_PATH='/var/lib/encounter-table-api/encounters.json'
export ENCOUNTER_GAMES_PATH='/pfad/zu/data/games'      # optional
export ENCOUNTER_BACKUP_DIR='/pfad/zu/backups'         # optional
```

Die gemeinsame Tabelle ist bewusst offen beschreibbar; Schreibzugriffe benötigen keinen Bearer-Token.

### Live-Updates im Betrieb

`GET /events` hält eine offene Verbindung pro Browser. Zwei Dinge sind dafür einzustellen:

- **Reverse Proxy:** die Antwort trägt `X-Accel-Buffering: no`, damit nginx den Stream nicht
  puffert – eine eigene `proxy_buffering off;`-Regel ist damit nicht nötig. Andere Proxys brauchen
  gegebenenfalls das Äquivalent.
- **Neustart:** der Stream endet planmäßig nach 30 Sekunden und der Browser verbindet sich neu.
  Ohne diese Grenze würde uvicorn beim Beenden auf die offenen Verbindungen warten. Im Dienst
  zusätzlich `--timeout-graceful-shutdown 5` setzen, dann ist ein Deploy sofort durch.

Fällt der Stream aus (Proxy, Netz, alter Browser), aktualisiert sich die Seite weiterhin alle
10 Sekunden von selbst – nur eben nicht sofort.

### Datensicherung

Neben dem Datenstand entsteht automatisch `backups/`: eine Kopie pro Tag (die letzten 30) sowie
eine zusätzliche direkt vor jeder Schema-Migration. Das ist der einzige Rückholpfad – eine
Änderungshistorie mit Rücknahme gab es bis v4, sie ist bewusst entfallen.

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
| `PATCH /runs/{id}` | Name, Status (`active`/`paused`/`completed`/`failed`) und Level-Cap-Fortschritt |
| `DELETE /runs/{id}` | Run löschen – außer es ist der letzte (409) |
| `GET /players`, `POST /players`, `DELETE /players/{id}` | Kader pflegen – Entfernen löscht die Einträge des Spielers in allen Runs |
| `GET /stats` | Negativstatistik, optional `?run_id=` oder `?game_id=` |
| `GET /events` | Server-Sent Events: meldet jede Änderung als `{"updated_at": …}` |

Nützliche Parameter und Header:

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
- `in_team` markiert die Links, die gerade gespielt werden. Höchstens sechs gleichzeitig, und nur
  Reihen mit mindestens einem lebenden Pokémon – stirbt oder verliert eine Reihe, fliegt sie
  automatisch raus. Dass ein Spieler an einem Ort leer ausgeht, hindert die Reihe nicht: der Link
  belegt trotzdem bei allen denselben Platz.
- Spieler werden intern als IDs geführt (`marc`, `nicolai`, `knev`); Anzeigename und Farbe stehen in
  `players` und lassen sich ändern, ohne Zeilen anzufassen.
