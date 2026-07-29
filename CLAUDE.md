# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projekt

Gekoppelte Nuzlocke-Soullink-Tabelle für die drei Spieler **Marc**, **Nicolai** und **Knev**,
über mehrere Editionen (Platin, Schwarz 2/Weiß 2) und Runs hinweg. Öffentlich unter
`https://bronze-brawl.de/encounter-table/`.

Inhalte, UI-Texte und Kommentare sind deutsch, Code-Bezeichner englisch.

## Befehle

```bash
python -m venv .venv && .venv\Scripts\Activate.ps1   # bash: . .venv/bin/activate
pip install -r requirements.txt
```

```bash
.venv/Scripts/python.exe -m uvicorn tools.dev_server:app --port 8010 --reload
```

Der Dev-Server liefert Frontend **und** API unter einem Origin und bildet die Produktionspfade nach
(`/encounter-table/` und `/encounter-table/api`) – das Frontend läuft dadurch ohne Anpassung.
Geschrieben wird auf `data/encounters.local.json`, nie auf den committeten Snapshot.

```bash
.venv/Scripts/python.exe -m pytest -q api/test_app.py
```

Einzelner Test: `pytest -q api/test_app.py::test_a_single_death_kills_the_whole_row`.
Tests aus dem Repo-Root über den Pfad `api/test_app.py` starten – `test_app.py` macht
`import app` und verlässt sich auf pytests sys.path-Eintrag.

```bash
python tools/build_game_catalog.py --all --check
```

Katalog-Generator; `--check` vergleicht nur. Läuft gegen PokeAPI und cacht nach `tools/.cache/`.
Kein Linter, kein Build-Schritt, keine Deploy-Skripte im Repo.

## Architektur

### Kuratiert vs. generiert – die zentrale Trennung

`tools/games/<spiel>.py` ist **Handarbeit**: Orte in Spielreihenfolge, Anzeigenamen und Level-Caps.
Nichts davon liefert PokeAPI (die API kennt nur ungeordnete Ortslisten voller Shops und
Battle-Facilities, und keine Trainer-Level).

`data/games/<spiel>.json` ist **generiert** und committed: dieselben Orte, angereichert um die
versionsgefilterten Pokémon-Listen, deutsche Namen und Dex-Nummern. Zur Laufzeit hängt nichts an
PokeAPI. Wer Ortslisten oder Caps ändert, muss den Generator laufen lassen und das Ergebnis
mitcommitten.

Ein neues Spiel kostet genau eine Definitionsdatei plus Generatorlauf – API und Frontend sind
spielunabhängig.

### Persistenz: eine JSON-Datei als Datenbank

Kein DB-Layer. `data_path()` liest `ENCOUNTER_DATA_PATH` **bei jedem Request neu**, weshalb Tests
die Variable pro Test umbiegen können, obwohl der `TestClient` global ist. Dasselbe gilt für
`ENCOUNTER_GAMES_PATH`; die Kataloge werden je Verzeichnis gecacht, Tests rufen
`reset_catalog_cache()`.

Jeder Schreibzugriff läuft durch den Contextmanager `mutate()`: laden → `If-Match` prüfen →
Dict in-place ändern → `updated_at` setzen → atomar speichern → gepufferte Historie schreiben,
alles unter dem globalen `write_lock`. **Neue Schreibpfade gehören in `mutate()`**, sonst fehlt
Sperre, Zeitstempel oder Historieneintrag.

Neben dem Datenstand liegen zwei weitere Dateien, beide gitignored:

- `<datenstand>-history.jsonl` – die Historie, **nur angehängt**. Sie ist bei offenen
  Schreibrechten das einzige Sicherheitsnetz und darf deshalb nicht im Datenstand stehen, wo ein
  paar hundert Requests sie verdrängen könnten. `record_history()` puffert in `_history_buffer`,
  geschrieben wird erst nach erfolgreichem `save_state()`. Eine Rücknahme ändert nichts, sondern
  hängt einen `undo`-Eintrag mit `undo_of` an; `undone` wird beim Lesen daraus abgeleitet.
- `backups/` – eine Kopie pro Tag (`daily_backup()`, die letzten 30) plus eine vor jeder
  Schema-Migration (`migration_backup()`). Backups scheitern still: sie dürfen einen
  Schreibzugriff nie blockieren.

### Migration läuft über die `normalize_*`-Kette

`normalize_state` → `normalize_run` → `normalize_encounter` heben beim Laden alte Stände an und
schreiben bei Abweichung sofort zurück. Sie tragen die komplette v2→v3-Migration:

- `players` von Namensliste zu `{id, name}`; `LEGACY_DISPLAY_NAMES` korrigiert die aus v2 geerbten
  Schreibweisen (Mark→Marc, Nikolai→Nicolai, KNEV→Knev). Das greift auch auf bereits migrierte
  v3-Daten – ein späteres Umbenennen bleibt trotzdem eine reine Datenänderung, solange niemand
  exakt die alte Schreibweise wählt
- die festen Zeilenfelder `mark`/`nikolai`/`knev` + `*_status` zur `picks`-Map
- Species-Slugs werden über den **deutschen Namen aus dem Katalog** zurückgewonnen, damit alte
  Zeilen Artwork bekommen
- alte Zeilen-IDs zu Katalog-Orten über `LEGACY_LOCATION_IDS` plus Regex für `route-NNN`
- `order` wird für verknüpfte Zeilen aus dem Katalog nachgetragen; ohne das haben Alt-Zeilen alle
  `order: 0` und jede Sortierung nach Spielreihenfolge fällt auf die ID-Sortierung zurück

Neue Felder gehören als `setdefault` dort hinein – dann migrieren Bestandsdaten von selbst.

### Datenmodell

Eine Zeile hält `picks: {player_id: {species, name, status}}`. `name` ist Freitext und trägt
weiterhin Sonderfälle wie `"Encounter verloren"`; `species` ist optional und liefert nur das
Artwork. Die Spieler sind damit **keine Schemafelder mehr** – ein vierter Spieler oder eine
Umbenennung ist eine Datenänderung.

`outcome` (`pending` | `caught` | `dead` | `failed`) wird in `derive_outcome()` abgeleitet, nicht
vom Client gepflegt: Tod schlägt alles, dann `PLACEHOLDER_PREFIXES` im Namen, dann „irgendwas
eingetragen“ = `caught`, sonst `pending`. Ein explizit gesetztes `failed` bleibt bestehen, solange
niemand etwas einträgt.

### Statistik ist reine Negativstatistik

`get_stats()` zählt ausschließlich Tode und vergeigte Encounter, jeweils **eine Zeile = ein
Vorfall**, zugeschrieben an `responsible_player`. Ein gekoppelter Tod kostet die Reihe drei
Pokémon, zählt aber als ein Tod – nämlich der des Verursachers. Schuld = Tode + vergeigte
Encounter. Fangzahlen gibt es bewusst nicht mehr. Zeilen ohne Schuldigen laufen in
`unassigned_*`, damit sie nicht stillschweigend aus der Summe fallen.

### Regeln, die der Code durchsetzt

- **Soullink**: `couple_deaths()` in `apply_encounter_patch()` macht aus einem Tod den Tod der
  ganzen Reihe. `?couple=false` ist der Ausweg – das Frontend nutzt ihn nur zum Wiederbeleben.
- **Verlorene Encounter**: `couple_failure()` trägt bei `outcome: failed` bei allen Spielern
  „Encounter verloren“ ein. Ein Tod in der Reihe hat Vorrang und blockt das ab.
- **Schuldiger ist Pflicht**: `require_culprit()` verlangt bei `dead` und `failed` einen Eintrag in
  `responsible_player` – sonst fiele der Vorfall aus der Negativstatistik. `NO_CULPRIT`
  (`"niemand"`) ist die ausdrückliche Variante für „war keiner schuld" und unterscheidbar von
  „noch nicht eingetragen".
- **Aktive Links**: `apply_team_rules()` hält `in_team` sauber – nur `caught`-Reihen dürfen rein,
  maximal `TEAM_SIZE` (6) gleichzeitig, und wer stirbt oder den Encounter verliert, fliegt
  automatisch raus. Ein Link belegt bei allen drei Spielern denselben Platz, daher genau ein Flag
  pro Zeile statt eines pro Spieler.
- **Species-Prüfung**: `validate_species()` lässt nur Pokémon zu, die laut Katalog an diesem Ort
  vorkommen. Geprüft wird **nur, was der Patch anfasst** – sonst würde ein per `?force=true`
  gespeicherter Sonderfall jede spätere Änderung derselben Zeile blockieren (dafür gibt es einen
  Test).
- **Offene Writes**: `require_write_token()` verlangt nur dann einen Bearer-Token, wenn
  `ENCOUNTER_API_TOKEN` gesetzt ist. Default ist offen – bewusste Entscheidung; abgesichert wird
  über die Historie mit Undo, nicht über Auth.

### Frontend

Drei Dateien in `web/`, kein Build. `API_BASE` lässt sich per `?api=` oder localStorage
überschreiben, sonst gilt der Produktionspfad.

- Rendering ist durchgehend `innerHTML` ⇒ **jeder** ausgegebene Wert muss durch `esc()`.
- Geschrieben wird sofort bei `change`. Der Pfad ist bewusst idempotent (`patchPick()` vergleicht
  vorher) und nimmt vor dem Neuzeichnen den Fokus aus der Zeile – sonst erzeugen Re-Render und
  Event-Delegation Doppel-Schreibvorgänge.
- `write()` reiht Schreibvorgänge über `writeChain` auf, statt bei laufendem Request auszusteigen.
  Wer schnell mehrere Zeilen umschaltet, verliert sonst Klicks ohne jede Rückmeldung.
- Kein Login und keine Identität – wer editiert, wird bewusst nicht erfasst. Die API kann per
  `X-Encounter-Author` trotzdem einen Autor mitschreiben; das Frontend nutzt das nicht.
- Polling alle 10 s auf `updated_at`; pausiert, solange ein Feld der Tabelle den Fokus hat.
- Artwork kommt deterministisch aus der Dex-Nummer des Katalogs – es gibt **keine** gepflegte
  Namensliste mehr und keinen PokeAPI-Request zur Laufzeit.

## Fallstricke

- Der committete `data/encounters.json` ist ein Snapshot, nicht der Live-Store. Produktiv liegt die
  Datei unter `ENCOUNTER_DATA_PATH`.
- `normalize_state` ändert verschachtelte Teile des eingelesenen Dicts **in-place**. `load_state`
  vergleicht deshalb den serialisierten Text mit dem Dateiinhalt, nicht Dict gegen Dict – sonst
  gelten Migrationen, die nur tief unten etwas ändern, als „nichts passiert“ und werden nie
  zurückgeschrieben.
- PokeAPI kennt für Schwarz 2/Weiß 2 keine Jahreszeiten; die Listen fassen alle vier zusammen.
- Die B2W2-Level-Caps gelten für den **Normal-Modus** (Easy und Challenge weichen ab).
- Nicht jedes Pokémon aus den Alt-Daten ist im Katalog: Skunkapuh ist in Platin z. B. gar nicht
  wild fangbar. Solche Zeilen bleiben als Freitext erhalten – das ist kein Fehler.
