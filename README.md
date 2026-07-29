# Gemeinsame Pokémon-Encounter-Tabelle

Öffentliche, gekoppelte Encounter-Tabelle für unseren Nuzlocke-Run mit **Mark**, **Nikolai** und **KNEV**.

- Live-Tabelle: https://bronze-brawl.de/encounter-table/
- Öffentliche API: https://bronze-brawl.de/encounter-table/api/
- API-Dokumentation: https://bronze-brawl.de/encounter-table/api/docs

## Projektstruktur

- `web/index.html` – read-only Frontend mit Run-Auswahl, Statistiken und PokeAPI-Artwork
- `api/app.py` – FastAPI-Backend mit Runs, Encounter-Zeilen und Statistiken
- `api/test_app.py` – API-Tests
- `data/encounters.json` – aktueller Tabellenstand als versionierbarer Daten-Snapshot

## Lokale Entwicklung

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

cd api
uvicorn app:app --reload
```

Für die lokale Tabelle kann im Frontend `API_BASE` in `web/index.html` auf die lokale API angepasst werden. Standardmäßig erwartet das Frontend den öffentlichen Pfad `/encounter-table/api`.

## Tests

```bash
pytest -q api/test_app.py
```

## API-Konfiguration

Schreibzugriffe benötigen einen Bearer-Token. Der Token darf niemals in Git committed werden.

```bash
export ENCOUNTER_API_TOKEN='<lokal setzen, nicht committen>'
export ENCOUNTER_DATA_PATH='../data/encounters.json'
```

Das Frontend enthält keine Schreib-Credentials und ist öffentlich lesend.

## Datenregeln

- Encounter sind nach Ort gekoppelt.
- Stirbt ein Pokémon einer Reihe, werden alle drei Pokémon der Reihe als tot markiert.
- Verlorene Encounter bleiben von bestätigten Pokémon-Toden getrennt.
- Die Spielernamen werden exakt als `Mark`, `Nikolai` und `KNEV` geführt.
