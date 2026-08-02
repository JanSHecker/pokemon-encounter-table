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

`tools/games/<spiel>.py` ist **Handarbeit**: Orte in Spielreihenfolge, Anzeigenamen, Level-Caps und
`dex_max`. Nichts davon liefert PokeAPI (die API kennt nur ungeordnete Ortslisten voller Shops und
Battle-Facilities, keine Trainer-Level und keinen National-Dex-Schnitt pro Edition). Zu jedem
Level-Cap gehört ein **`type`**: der Typ des Kampfes, der Badge und Zeitleiste der Cap-Karte
einfärbt. Leer heißt „gemischt“ – Rivalen-, Team- und Champion-Kämpfe haben keinen Typ.

Dateien mit **führendem Unterstrich** sind keine Spiele, sondern geteilte Bausteine: `_sinnoh.py`
hält die Ortsliste, die sich Platin und Renegade Platin teilen. `load_game_definitions()` legt
`tools/games/` dafür auf `sys.path` – `exec_module` tut das nicht von selbst. Renegade Platinum ist
ein Hack von Platin: gleiche Orte, **andere Level-Caps**. Die Wild-Encounter des Hacks kennt PokeAPI
nicht, sein Katalog trägt deshalb die Listen von Platin – im Frontend steht ohnehin der ganze
Pokedex zur Auswahl, die Ortsliste ist nur der Vorschlag oben.

`data/games/<spiel>.json` ist **generiert** und committed: dieselben Orte, angereichert um die
versionsgefilterten Pokémon-Listen, deutsche Namen und Dex-Nummern. Zur Laufzeit hängt nichts an
PokeAPI. Wer Ortslisten oder Caps ändert, muss den Generator laufen lassen und das Ergebnis
mitcommitten.

Dazu kommt `pokedex`: der National-Dex von 1 bis `dex_max` (Platin 493, Schwarz 2/Weiß 2 649), je
Eintrag Slug, deutscher Name, Nummer, **`family`** und **`types`**. Die Familie ist die ID der
`evolution-chain` – sie steht schon in der Species-Antwort, `/evolution-chain/` selbst wird nie
abgefragt. Alle Arten einer Kette teilen sich die Nummer, und genau das ist die Dupes-Clause:
Karpador und Garados sind dieselbe Familie. Der Generator bricht ab, wenn `dex_max` eine Art
auslässt, die an einem Ort vorkommt – sonst hätte ausgerechnet ein fangbares Pokémon keine Familie.

Die Typen stehen **nur im Pokedex**, nicht an den Ortslisten: das Frontend schlägt jede Art ohnehin
im Pokedex nach (`index.species`), eine zweite Kopie machte den Katalog nur größer. Es sind die
heutigen Typen, nicht die der Edition – Piepi ist also auch in Platin eine Fee. Der Typenrechner
rechnet ebenfalls modern; beides auseinanderlaufen zu lassen wäre schlimmer als beides gleich.

Ein neues Spiel kostet genau eine Definitionsdatei plus Generatorlauf – API und Frontend sind
spielunabhängig.

### Persistenz: eine JSON-Datei als Datenbank

Kein DB-Layer. `data_path()` liest `ENCOUNTER_DATA_PATH` **bei jedem Request neu**, weshalb Tests
die Variable pro Test umbiegen können, obwohl der `TestClient` global ist. Dasselbe gilt für
`ENCOUNTER_GAMES_PATH`; die Kataloge werden je Verzeichnis gecacht, Tests rufen
`reset_catalog_cache()`.

Der geladene Stand wird über `(Pfad, mtime, Größe)` gecacht (`_state_cache`); ohne das zahlt jeder
Request Parsen, Modellprüfung und Serialisieren, nur um festzustellen, dass sich nichts geändert
hat. `save_state()` frischt den Cache selbst auf.

Jeder Schreibzugriff läuft durch den Contextmanager `mutate()`: laden → **tiefe Kopie** →
`If-Match` prüfen → ändern → `updated_at` setzen → atomar speichern, alles unter dem globalen
`write_lock`. **Neue Schreibpfade gehören in `mutate()`**, sonst fehlt Sperre oder Zeitstempel.
Die Kopie ist nicht optional: bricht eine
Regel den Vorgang mit 4xx ab, stünde sonst der halb geänderte Stand im Cache. Endpunkte, die auf
einem Run arbeiten, nehmen `write_to_run()` – dieselbe Klammer, plus Auflösung von „benannter Run“
oder „aktueller Run“.

`updated_at` ist über `next_updated_at()` **streng monoton** und mikrosekundengenau. Sekunden
reichten nicht: zwei Schreibzugriffe in derselben Sekunde ergäben denselben Wert, womit `If-Match`
eine fremde Änderung durchwinkt und das Polling sie für „nichts passiert“ hält.

Neben dem Datenstand liegt `backups/`, gitignored: eine Kopie pro Tag (`daily_backup()`, die
letzten 30) plus eine vor jeder Schema-Migration (`migration_backup()`). Backups scheitern still:
sie dürfen einen Schreibzugriff nie blockieren. Bei offenen Schreibrechten sind sie der einzige
Rückholpfad – eine Änderungshistorie mit Undo gab es bis v4, sie ist bewusst entfallen.

### Migration läuft über die `normalize_*`-Kette

`normalize_state` → `normalize_run` → `normalize_encounter` heben beim Laden alte Stände an und
schreiben bei Abweichung sofort zurück. Sie tragen die komplette v2→v3-Migration sowie die
Schritte auf v4, v5 und v6:

- `players` von Namensliste zu `{id, name}`; `LEGACY_DISPLAY_NAMES` korrigiert die aus v2 geerbten
  Schreibweisen (Marc, Nicolai und Knev) werden bei der Migration exakt beibehalten. Das greift auch auf bereits migrierte
  v3-Daten – ein späteres Umbenennen bleibt trotzdem eine reine Datenänderung, solange niemand
  exakt die alte Schreibweise wählt
- die festen Zeilenfelder `mark`/`nikolai`/`knev` + `*_status` zur `picks`-Map
- Species-Slugs werden über den **deutschen Namen aus dem Katalog** zurückgewonnen, damit alte
  Zeilen Artwork bekommen
- alte Zeilen-IDs zu Katalog-Orten über `LEGACY_LOCATION_IDS` plus Regex für `route-NNN`
- `order` wird für verknüpfte Zeilen aus dem Katalog nachgetragen; ohne das haben Alt-Zeilen alle
  `order: 0` und jede Sortierung nach Spielreihenfolge fällt auf die ID-Sortierung zurück
- v2 kannte nur einen **freien Spielnamen**; `resolve_game_id()` bildet ihn über
  `LEGACY_GAME_NAMES` auf eine Katalog-ID ab. Eine bereits migrierte Slug-ID bleibt unangetastet,
  auch wenn ihr Katalog gerade fehlt – sie zu überschreiben wäre Datenverlust. Freitext, der
  nirgends passt, fällt auf `DEFAULT_GAME_ID`: eine game_id ohne Katalog macht den Run unerreichbar,
  weil das Frontend zu jeder game_id einen Katalog lädt und bei 404 abbricht
- v4 entfernt das Zeilenfeld `note` ersatzlos. `normalize_encounter` **poppt** es, statt es zu
  ignorieren: `EncounterRow` verbietet unbekannte Felder, ein stehengebliebenes `note` aus
  Altdaten ließe das Laden scheitern. Genau dieser Pop löscht die Texte auch aus dem Datenstand –
  die Kopie davor liefert `migration_backup()`, das nur beim Sprung von `SCHEMA_VERSION` greift.
  **Ein Feld zu entfernen ist deshalb immer auch ein Versionssprung**, sonst verschwinden Daten
  ohne Sicherung

- v5 löst die eigene Starter-Zeile auf: die Starter sind der Encounter des Ortes, an dem man sie
  bekommt, und stehen dort ohnehin schon als „Geschenk“. Das erledigt `apply_catalog_moves()`, weil
  es den ganzen Run braucht: `RETIRED_LOCATIONS` zieht die Zeile auf ihren Nachfolger, und steht
  der schon als eigene Zeile im Run, legt `merge_rows()` beide zusammen – die **inhaltsreichere**
  bleibt, sonst gewänne die leere und genau die gefangenen Pokémon wären weg. Im selben Durchgang
  kommt `order` frisch aus dem Katalog: fällt ein Ort weg, rücken alle nachfolgenden auf, und
  Alt-Zeilen mischten sich sonst mit ihrer alten Nummer falsch unter später angelegte

- v6 gibt jedem Spieler eine **Farbe** aus `PLAYER_COLORS` und dem Run zwei weitere Status
  (`paused`, `failed`). Beides ist rein additiv, trotzdem ein Versionssprung: alter Code kennt die
  neuen Status nicht und würde beim Laden abbrechen – der Sprung sichert wenigstens den Stand
  davor. Bestandsspieler bekommen die Farbe der Reihe nach, also genau die, die beim Anlegen
  vergeben worden wäre. Ein **unbekannter Run-Status** fällt auf `active` zurück, statt beim Laden
  die ganze API lahmzulegen

Grenzen dürfen hier nur **weiter** werden: `normalize_*` prüft Bestandsdaten gegen die aktuellen
Modelle, ein engeres Feld legt beim Laden die ganze API lahm statt nur die betroffene Zeile
(`responsible_player` steht deshalb auf 80 Zeichen wie in v2, überlange Werte werden gekürzt).

Neue Felder gehören als `setdefault` dort hinein – dann migrieren Bestandsdaten von selbst,
entfallene als `pop`. Was das Modell ohnehin per Default füllt, gehört **nicht** hierher. Was
mehrere Zeilen gleichzeitig betrifft – Orte zusammenlegen, `order` nachziehen – gehört dagegen in
`apply_catalog_moves()`; `normalize_encounter` sieht immer nur eine Zeile.

**Einen Ort aus einem Katalog zu entfernen ist ein Versionssprung**, so wie ein entfallenes Feld:
ohne den greift `migration_backup()` nicht, und Zeilen zusammenzulegen ist nicht umkehrbar. Wer mit
altem Code auf einen neueren Stand losgeht, schreibt ihn übrigens stillschweigend auf die alte
Version zurück – nach einem Katalogwechsel gehört der Dienst neu gestartet, bevor jemand die
Tabelle öffnet.

### Datenmodell

Eine Zeile hält `picks: {player_id: {species, name, status}}`. `name` ist Freitext und trägt
weiterhin Sonderfälle wie `"Encounter verloren"`; `species` ist optional und liefert nur das
Artwork. Die Spieler sind damit **keine Schemafelder mehr** – ein vierter Spieler oder eine
Umbenennung ist eine Datenänderung.

Ein Spieler ist `{id, name, color}` und wird über `POST /players` / `DELETE /players/{id}`
gepflegt. Die Farbe steht **am Datensatz** und wird nicht aus der Position abgeleitet: sonst
tauschten beim Entfernen eines Spielers alle nachfolgenden die Farbe, und die Farbe ist in
Tabellenkopf, Chips und Statistik seine Identität. Neu vergeben wird die erste freie aus
`PLAYER_COLORS`.

Beide Schreibwege müssen den Rest des Standes mitziehen: **Anlegen** setzt in jeder Zeile jedes
Runs einen leeren Pick (ohne den läuft der nächste Patch dieser Zeile in einen `KeyError` statt in
eine Antwort), **Entfernen** löscht die Picks, leitet das Outcome neu ab und nimmt die Zeile
gegebenenfalls aus dem Team. War der Entfernte der Schuldige, wird daraus `NO_CULPRIT` statt
„niemand eingetragen“ – sonst fiele der Vorfall aus der Negativstatistik und `require_culprit()`
würde die Zeile beim nächsten Schreibzugriff ablehnen.

`run.status` ist `active` | `paused` | `completed` | `failed` („verkackt“). **Aktiv ist höchstens
ein Run**: `pause_other_active_runs()` setzt die übrigen auf `paused`, sowohl beim Anlegen als auch
beim Reaktivieren, und zieht `current_run_id` mit. Ohne das zeigten Übersicht (Status) und
`/encounters` (`current_run_id`) auf verschiedene Runs.

`DELETE /runs/{id}` löscht einen Run samt Zeilen, **außer es ist der letzte**: ohne Runs legt
`normalize_state` beim nächsten Laden stillschweigend einen neuen an – das Löschen sähe aus, als
wäre es fehlgeschlagen. War der gelöschte der aktuelle, rückt ein anderer nach; war er auch der
laufende, übernimmt der nächste **pausierte**. Ein fertiger oder verkackter Run wird dabei nicht
reaktiviert – das wäre eine Aussage über den Run, die niemand getroffen hat.

`outcome` (`pending` | `caught` | `dead` | `failed`) wird in `derive_outcome()` abgeleitet, nicht
vom Client gepflegt: Tod schlägt alles, dann `PLACEHOLDER_PREFIXES` im Namen, dann „irgendwas
eingetragen“ = `caught`, sonst `pending`. Ein explizit gesetztes `failed` bleibt bestehen, solange
niemand etwas einträgt. Beachte: `caught` heißt **irgendwer** hat etwas eingetragen, nicht alle –
wer „jeder hat etwas“ meint, muss die Picks selbst durchgehen.

### Live-Updates: ein Stream, der absichtlich endet

`GET /events` schickt bei jeder Änderung den neuen `updated_at` als Server-Sent Event. Mehr steht
nicht drin: wer den Zeitstempel nicht kennt, lädt selbst nach. Damit weiß das Nachrichtenformat
nichts über Runs, Zeilen oder Spieler und kann davon auch nichts veralten lassen.

Zwei Details sind nicht optional:

- **`X-Accel-Buffering: no`.** Ohne den Header puffert nginx den Stream und die Meldung kommt erst
  an, wenn der Puffer voll ist – das spart eine Anpassung an der Proxy-Konfiguration.
- **`STREAM_MAX_SECONDS`.** Ein Stream, der nie endet, hält den Prozess fest: uvicorn wartet beim
  Beenden auf offene Verbindungen („Waiting for connections to close“) und hängt, solange auch nur
  ein Browser lauscht – jeder Neustart und jedes Deployment bliebe stehen. Deshalb endet der Stream
  nach einer halben Minute und der Browser verbindet sich neu (`retry:` am Anfang setzt die
  Wartezeit auf eine Sekunde). Ein Neustart kostet damit höchstens diese halbe Minute; in der
  Dienst-Konfiguration gehört zusätzlich `--timeout-graceful-shutdown` gesetzt.

Der Stream sieht einmal pro Sekunde nach. Das ist billig, weil `load_state()` nur
`(Pfad, mtime, Größe)` vergleicht und sonst aus dem Cache antwortet – geparst wird nur, wenn
wirklich jemand geschrieben hat.

Getestet wird der **Generator direkt**, nicht über HTTP: über den `TestClient` gelesen hängt ein
Stream, der nicht von selbst endet, den ganzen Testlauf auf.

### Statistik ist reine Negativstatistik

`get_stats()` zählt ausschließlich Tode und vergeigte Encounter, jeweils **eine Zeile = ein
Vorfall**, zugeschrieben an `responsible_player`. Ein gekoppelter Tod kostet die Reihe drei
Pokémon, zählt aber als ein Tod – nämlich der des Verursachers. Schuld = Tode + vergeigte
Encounter. Fangzahlen gibt es bewusst nicht mehr. Zeilen ohne Schuldigen laufen in
`unassigned_*`, damit sie nicht stillschweigend aus der Summe fallen.

### Regeln, die der Code durchsetzt

- **Soullink**: `couple_deaths()` macht aus einem Tod den Tod der ganzen Reihe – ausgelöst durch
  einen toten Pick **oder** durch ein angefordertes `outcome: dead` (so meldet das Frontend den
  Tod). `?couple=false` ist der Ausweg – das Frontend nutzt ihn nur zum Wiederbeleben.
- **Outcome und Picks bleiben konsistent**: `require_consistent_outcome()` verbietet ein `dead`
  ohne toten Pick. Ein solcher Stand hielte nicht: die nächste Änderung an der Zeile leitet das
  Outcome neu ab und macht stillschweigend wieder `caught` daraus – der Tod verschwände aus der
  Negativstatistik.
- **Verlorene Encounter**: `couple_failure()` trägt bei `outcome: failed` bei allen Spielern
  „Encounter verloren“ ein. Ein Tod in der Reihe hat Vorrang und blockt das ab.
- **Anlegen folgt derselben Kette wie Ändern**: `add_row()` durchläuft Kopplung, Konsistenz-,
  Team- und Schuldigenprüfung wie `apply_encounter_patch()`. Sonst entstehen über POST Zeilen,
  die über PATCH nie entstehen könnten.
- **Schuldiger ist Pflicht**: `require_culprit()` verlangt bei `dead` und `failed` einen Eintrag in
  `responsible_player` – sonst fiele der Vorfall aus der Negativstatistik. `NO_CULPRIT`
  (`"niemand"`) ist die ausdrückliche Variante für „war keiner schuld" und unterscheidbar von
  „noch nicht eingetragen".
- **Aktive Links**: `apply_team_rules()` hält `in_team` sauber – rein darf nur, was `team_ready()`
  bejaht, und das ist seit v6 schlicht `outcome == "caught"`: irgendwer hat etwas Lebendes.
  Maximal `TEAM_SIZE` (6) gleichzeitig, und wer stirbt oder den Encounter verliert, fliegt
  automatisch raus. Ein Link belegt bei allen Spielern denselben Platz, daher genau ein Flag pro
  Zeile statt eines pro Spieler. Bis v5 verlangte die Prüfung einen lebenden Eintrag von **jedem** –
  damit ließ sich eine Reihe, in der einer leer ausging, nie spielen, obwohl die anderen ihr Pokémon
  im Team hatten. Dass jemand an einem Ort nichts bekommt, ist im Soullink der Normalfall.
- **Species-Prüfung**: `validate_species()` lässt nur Pokémon zu, die laut Katalog an diesem Ort
  vorkommen. Geprüft wird **nur, wo der Patch `species` anfasst** – nicht jeder Pick, den er
  berührt. Sonst blockiert ein per `?force=true` gespeicherter Sonderfall jede spätere Änderung an
  genau diesem Pick, bis hin zum Kill-Button, der nur den Status setzt (dafür gibt es zwei Tests:
  anderer Spieler und derselbe Spieler). Das Frontend stellt inzwischen den ganzen Pokedex zur
  Auswahl und schickt für alles außerhalb der Ortsliste `force=true` mit – die Regel schützt damit
  noch fremde Clients und Tippfehler in der API, nicht mehr den Klickweg.
- **Dupes-Clause ist Anzeige, keine Regel**: dass ein Spieler dieselbe Entwicklungslinie kein
  zweites Mal fangen darf, steht **nur** im Frontend als ⚠. Bewusst so entschieden – während einer
  Session ist ein 422 mitten im Eintragen lästiger als ein übersehener Doppeleintrag, und Alt-Zeilen
  mit Freitext statt `species` könnte die API ohnehin nicht prüfen. Wer das umdreht, braucht eine
  Regelfunktion in derselben Kette wie `require_culprit()` **und** einen Weg vorbei, sonst sind
  Sonderfälle wie ein geschenktes Pokémon nicht mehr eintragbar.
- **Kein `null` für Pflichtfelder**: `reject_null_fields()` weist ausdrückliche Nullwerte für
  Felder ab, die eine Zeile braucht. Ohne das landet `None` im Datensatz und erst die
  Modellprüfung am Ende schlägt fehl – der Aufrufer sähe einen 500er statt eines Hinweises.
- **Offene Writes**: `require_write_token()` verlangt nur dann einen Bearer-Token, wenn
  `ENCOUNTER_API_TOKEN` gesetzt ist. Default ist offen – bewusste Entscheidung. Ein Undo gibt es
  seit v4 nicht mehr; wer etwas zerschießt, holt es aus `backups/` zurück.

### Frontend

Drei Dateien in `web/` plus `web/icons/` (18 Typ-Symbole, MIT, aus
`duiker101/pokemon-type-svg-icons`), kein Build. `API_BASE` lässt sich per `?api=` oder localStorage
überschreiben, sonst gilt der Produktionspfad. Vorlage ist das Design-Bundle
`design_handoff_pokemon_tracker` (nicht im Repo, liegt bei Marc): High-Fidelity-Prototyp als HTML,
gedacht als Referenz für Farben, Maße und Verhalten – nicht als Produktionscode.

**Zwei Ansichten, ein Dokument**: `state.view` schaltet zwischen Run-Übersicht (`#home-view`) und
Run-Dashboard (`#run-view`); `render()` zeichnet Kopf plus die sichtbare Ansicht. Die Seite ist
öffentlich und ohne Login, es gibt also kein „mein Team“ – die Teamzugehörigkeit steht als
Pokéball in der Tabelle.

- Rendering ist durchgehend `innerHTML` ⇒ **jeder** ausgegebene Wert muss durch `esc()`. Das gilt
  auch für Zahlen aus der API: `?api=` ist per URL überschreibbar, ein geteilter Link kann die
  Antworten also fremdbestimmen.
- Typfarben und -symbole stehen als Klassen (`.t-fire` und Co.) in der CSS, nicht als Inline-Style:
  die 18 Typen sind fest, und die Tabelle rendert sie hundertfach. `typeBadge()` setzt nur die
  Klasse, eingefärbt wird per CSS-Mask.
- Zwei CSS-Regeln sind nicht kosmetisch: `[hidden] { display: none !important }` und
  `dialog:not([open]) { display: none }`. Ansichten und Dialoge tragen eigene `display`-Werte
  (`grid`, `flex`), die sonst gegen das `hidden`-Attribut bzw. gegen die UA-Regel für geschlossene
  Dialoge gewinnen – beide Views stünden untereinander und Dialoge blieben nach dem Schließen stehen.
- Werte, die zum API-Vertrag gehören (`LOST_LABEL`, `NO_CULPRIT`, `TEAM_SIZE`), kommen aus
  `GET /runs` → `rules`. Der Platzhalter ist Protokoll: die API trägt ihn bei `outcome: failed`
  selbst bei allen Spielern ein. Eine zweite Kopie im Frontend fiele beim Umbenennen still
  auseinander.
- `category()` fasst Outcome und `in_team` zu den fünf Zuständen zusammen, die Filter, Sortierung
  und Zeilenfarbe brauchen: `team` › `box` › `tot` › `verloren` › `offen`. **Die Kategorie ist auch
  die CSS-Klasse** (`is-tot`, `is-verloren`, …) – wer hier umbenennt, muss die Regeln in
  `styles.css` mitziehen, sonst verlieren die Zeilen still ihre Farbe. Der Pokéball ist klickbar,
  sobald `outcome === "caught"` – dieselbe Bedingung wie `team_ready()` der API, sonst liefe der
  Klick in ein 422.
- Das Suchfeld über der Tabelle filtert nur nach **Ortsnamen** und zeichnet ausschließlich die
  Tabelle neu (`renderTable()`), nicht die Toolbar: sonst verlöre das Feld bei jedem Tastendruck
  den Fokus. Die Zähler an den Filter-Pills bleiben absichtlich die des ganzen Runs.
- Sortiert wird nur für die Anzeige (`visibleRows()`); `state.run.encounters` behält die Reihenfolge
  der API. „Nach Status“ **gruppiert** nur, innerhalb der Gruppe gilt weiter die Spielreihenfolge
  (`order`) – für einen Nuzlocke zählt, was als Nächstes drankommt.
- Nach jedem Schreibzugriff zeichnet `patchRow()` die ganze Run-Ansicht neu. Eine einzelne Änderung
  verschiebt Filterzähler, Sortiergruppe, Kopfzahlen, Fail-Statistik und Typen-Check gleichzeitig;
  nur die eine Zeile zu tauschen ließe den Rest bis zum nächsten Poll falsch stehen. Bei 43 Zeilen
  ohne Eingabefelder ist das billig – die Zellen sind Buttons, es geht kein Tippfortschritt verloren.
- Kataloge werden beim Laden **indiziert** (`catalog.index`), Dupe-Zähler einmal pro
  Zeichenvorgang (`pickCounts()`). Vorher scannte jede Zelle Tabelle und Katalog komplett.
  `index.species` führt Ortslisten und `pokedex` zusammen, der Pokedex gewinnt – er allein kennt
  `family` und `types`. Fehlt er (Katalog noch nicht neu generiert), fällt `familyOf()` auf den Slug
  zurück und die Typ-Badges bleiben leer: lieber die alte Artenprüfung als gar keine.
- Die Zelle zeigt nur den Stand; gewählt wird im **Auswahldialog** (`openPicker()`), einem einzigen
  für die ganze Tabelle. Oben stehen die Arten des Ortes nach Methode gruppiert, darunter „Alle
  anderen“ mit dem Rest des Pokedex, und ein Suchfeld filtert beides (Enter nimmt den ersten
  Treffer). Als `<select>` je Zelle ginge das nicht: 43 Zeilen × 3 Spieler × 500 Einträge wären
  zehntausende `<option>`, und suchen ließe sich darin trotzdem nicht.
- Das ⚠ an einem Eintrag meint die **Entwicklungslinie**, nicht die Art: wer ein Karpador hat,
  bekommt es auch an Garados. Der Status zählt dabei nicht – ein totes Karpador gibt die Linie
  nicht wieder frei.
- Der **Typenrechner** rechnet mit der heutigen Tabelle (`CHART`, 18 Typen) und kennt zwei Modi:
  Angriff nimmt je Verteidigertyp den **besten** Multiplikator der Auswahl (Coverage), Abwehr das
  **Produkt** beider Verteidigungswerte – daher gibt es dort ×4 und ×¼. Bei gewähltem Angriffstyp
  bekommen anfällige Pokémon in der Tabelle einen roten Innenring plus „×2“/„×4“; im Abwehrmodus
  markiert die Tabelle nichts, dort beantwortet die Liste unten „wer hat Links dieses Typs“. Der
  Modus wird deshalb **nicht** gespeichert: ein aus der letzten Sitzung stehengebliebenes „Abwehr“
  sähe aus, als wäre die Markierung kaputt. Ein Generationsumschalter (Gen 1 / 2–5 / 6+) stand bis
  zum UI-Rework hier und ist mit dem Design entfallen; die Typen im Katalog sind ohnehin die
  heutigen.
- Die **Fail-Statistik** rechnet lokal aus dem geladenen Run (`failStats()`, Schuld = Tod ×2 +
  vergeigter Encounter), damit sich die Balken mit der Tabelle ändern statt erst beim nächsten Poll.
  `GET /stats` wird nur für den Spieler-Dialog geholt – dort zählen alle Runs.
- `poll()` lädt über `loadRuns()`, nicht mit eigenem Fetch: nur so greift der Rückfall auf den
  aktuellen Run des Servers, wenn der eigene gelöscht wurde. Er pausiert, solange ein **Dialog**
  offen ist oder der Tab im Hintergrund liegt, und merkt sich das in `refreshPending`;
  `refreshWhenFree()` holt es nach, sobald der Dialog zugeht oder der Tab wieder sichtbar wird.
  Das Suchfeld über der Tabelle blockiert bewusst **nicht** – es steht außerhalb des neu
  gezeichneten Bereichs und behält seinen Fokus.
- Die Änderung eines anderen kommt über `connectStream()` (`GET /events`, Server-Sent Events) und
  ist in unter einer Sekunde sichtbar. Das Polling bleibt daneben bestehen: schluckt ein Proxy den
  Stream, fällt es auf die zehn Sekunden von vorher zurück statt auf gar nichts. Der `EventSource`
  verbindet sich nach dem geplanten Ende des Streams von selbst neu.
- `write()` reiht Schreibvorgänge über `writeChain` auf, statt bei laufendem Request auszusteigen.
  Wer schnell mehrere Zeilen umschaltet, verliert sonst Klicks ohne jede Rückmeldung. `patchPick()`
  vergleicht vorher und schluckt Phantom-Events.
- Kein Login und keine Identität – wer editiert, wird bewusst nicht erfasst.
- Sprites kommen deterministisch aus der Dex-Nummer des Katalogs (die kleinen Spielsprites,
  `image-rendering: pixelated`) – es gibt **keine** gepflegte Namensliste und keinen
  PokeAPI-Request zur Laufzeit.

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
- Mit dem UI-Rework sind drei Bedienwege ersatzlos entfallen, ihre Endpunkte gibt es weiter:
  „Ort hinzufügen“ (`POST /runs/{id}/encounters`, damit auch Postgame-Orte nachträglich),
  Freitext-Eintrag statt einer Art (`?force=true` mit `species: null`) und die Dashboard-Ansicht
  über `GET /stats`. Wer sie zurückwill, braucht nur Frontend.
- `level_caps` führt **jeden Kampf, der ein Cap setzt**, nicht nur die Arenen: bei Renegade Platin
  stehen Mars, Barry und Zyrus mit drin, sonst spränge die Karte von Lv 16 auf Lv 26. `leader` und
  `place` sind deutsch (die Karte zeigt „Veit · Erzelingen“), die Teamdetails (`ace`, `moves`, …)
  bleiben englisch – sie stammen aus der Dokumentation des Hacks.
- Ein **neuer Katalog wird erst nach einem Neustart sichtbar**: `load_games()` cacht je Verzeichnis
  und leert den Cache nur beim Prozessstart. Wer eine Spieldatei ergänzt und sich wundert, warum
  der Dialog sie nicht anbietet, hat den Dienst nicht neu gestartet.
