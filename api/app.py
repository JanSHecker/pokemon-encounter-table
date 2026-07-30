from __future__ import annotations

import copy
import json
import os
import re
import secrets
import shutil
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, get_args

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 5
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

Outcome = Literal["pending", "caught", "dead", "failed"]
OUTCOMES = get_args(Outcome)
PickStatus = Literal["alive", "dead"]
RunStatus = Literal["active", "completed"]

DEFAULT_PLAYERS = [
    {"id": "marc", "name": "Marc"},
    {"id": "nicolai", "name": "Nicolai"},
    {"id": "knev", "name": "Knev"},
]

# Die drei Spieler-Namen sind user-facing Daten und bleiben exakt erhalten.
LEGACY_DISPLAY_NAMES = {"Mark": "Marc", "Nikolai": "Nicolai", "KNEV": "Knev", "Marc": "Marc", "Nicolai": "Nicolai", "Knev": "Knev"}
DEFAULT_GAME_ID = "platinum"

# Freitext, der einen verlorenen Encounter markiert (Alt-Daten und weiterhin erlaubt).
PLACEHOLDER_PREFIXES = ("Encounter verloren", "Kein Encounter")
LOST_LABEL = PLACEHOLDER_PREFIXES[0]

# Die drei Spieler hiessen bis Schema v2 anders und steckten als feste Felder in jeder Zeile.
LEGACY_PLAYER_FIELDS = {"mark": "marc", "nikolai": "nicolai", "knev": "knev"}
LEGACY_PLAYER_LABELS = {"Mark": "marc", "Nikolai": "nicolai", "KNEV": "knev"}

# v2 kannte kein Spiel als Konzept, nur einen freien Namen. Bekannte Schreibweisen
# landen auf der Katalog-ID; alles andere faengt resolve_game_id() ab.
LEGACY_GAME_NAMES = {
    "platin": "platinum",
    "pokemon platin": "platinum",
    "pokémon platin": "platinum",
    "schwarz 2": "black-2-white-2",
    "weiss 2": "black-2-white-2",
    "weiß 2": "black-2-white-2",
    "schwarz 2/weiss 2": "black-2-white-2",
    "schwarz 2/weiß 2": "black-2-white-2",
    "pokemon schwarz 2": "black-2-white-2",
    "pokémon schwarz 2": "black-2-white-2",
    "pokemon weiss 2": "black-2-white-2",
    "pokémon weiß 2": "black-2-white-2",
}

# Alte Zeilen-IDs auf Katalog-Orte. Bewusst explizit - hier wird nicht geraten.
LEGACY_LOCATION_IDS = {
    "starter": "starter",
    "route-201-starter": "starter",
    "lake-verity": "lake-verity",
    "ruinental": "ravaged-path",
    "erzelinger-tunnel": "oreburgh-gate",
    "erzelinger-tunnel-oreburgh-gate": "oreburgh-gate",
    "erzelingen-mine": "oreburgh-mine",
    "windkraftwerk": "valley-windworks",
    "ewigwald": "eterna-forest",
    "alte-villa": "old-chateau",
    "bizarre-hoehle": "wayward-cave",
    "kraterberg": "mt-coronet",
    "siegesstrasse": "sinnoh-victory-road",
    "grossmoor": "great-marsh",
    "eiseninsel": "iron-island",
}
LEGACY_SEA_ROUTES = {"220", "223", "226", "230"}

# Orte, die aus einem Katalog verschwunden sind, samt Nachfolger. v5 loest die
# eigene Starter-Zeile auf: die Starter sind der Encounter des Ortes, an dem man
# sie bekommt, und stehen dort ohnehin schon als Geschenk. Eintraege hier bleiben
# fuer immer stehen - ein alter Datenstand kann jederzeit auftauchen.
RETIRED_LOCATIONS = {
    "platinum": {"starter": "sinnoh-route-201"},
    "black-2-white-2": {"starter": "aspertia-city"},
}

# Felder, die sich per PATCH ausdruecklich auf null setzen (also leeren) lassen.
NULLABLE_ROW_FIELDS = {"responsible_player", "picks"}
NULLABLE_RUN_FIELDS: set[str] = set()

# Taegliche Kopie des Datenstandes, plus eine vor jeder Schema-Migration.
BACKUP_KEEP = 30

# Ein Link belegt bei allen drei Spielern denselben Teamplatz, also gilt schlicht
# die Teamgroesse.
TEAM_SIZE = 6

# Ausdrueckliches "war niemand schuld" - unterscheidbar von "noch nicht eingetragen".
NO_CULPRIT = "niemand"

app = FastAPI(
    title="Pokémon Encounter API",
    version="4.0.0",
    description="Gekoppelte Nuzlocke-Encounter-Tabellen über mehrere Spiele und Runs.",
    root_path="/encounter-table/api",
)
security = HTTPBearer(auto_error=False)
write_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Spielkataloge
# --------------------------------------------------------------------------- #


def games_path() -> Path:
    """Verzeichnis mit den generierten Katalogen (siehe tools/build_game_catalog.py)."""
    configured = os.environ.get("ENCOUNTER_GAMES_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "data" / "games"


_catalog_cache: dict[str, dict[str, Any]] = {}

# Aus den Katalogen abgeleitete Nachschlagewerke. Kataloge aendern sich zur
# Laufzeit nicht, die Indizes also auch nicht - sie pro Zeile neu aufzubauen
# kostet beim Laden eines Alt-Standes das Vielfache.
_derived_cache: dict[tuple[str, str, str], Any] = {}


def games_key() -> str:
    directory = games_path()
    return str(directory.resolve()) if directory.exists() else str(directory)


def load_games() -> dict[str, dict[str, Any]]:
    """Kataloge lesen und je Verzeichnis cachen (Tests zeigen auf eigene Fixtures)."""
    directory = games_path()
    key = games_key()
    if key in _catalog_cache:
        return _catalog_cache[key]

    catalogs: dict[str, dict[str, Any]] = {}
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                catalog = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Spielkatalog ist ungültig: {path}") from exc
            catalogs[catalog["id"]] = catalog

    _catalog_cache[key] = catalogs
    return catalogs


def reset_catalog_cache() -> None:
    _catalog_cache.clear()
    _derived_cache.clear()
    _state_cache.clear()


def game_or_none(game_id: str) -> dict[str, Any] | None:
    """Katalog zu einer Spiel-ID oder None.

    Einzige Stelle, an der eine Spiel-ID nachgeschlagen wird - alles darueber
    entscheidet nur noch, was ein fehlender Katalog bedeutet.
    """
    return load_games().get(game_id)


def find_game(game_id: str) -> dict[str, Any]:
    game = game_or_none(game_id)
    if game is None:
        known = ", ".join(sorted(load_games())) or "keine"
        raise HTTPException(status_code=404, detail=f"Spiel '{game_id}' nicht gefunden (bekannt: {known}).")
    return game


def game_locations(game_id: str) -> list[dict[str, Any]]:
    game = game_or_none(game_id)
    return game["locations"] if game else []


def derived(kind: str, game_id: str, build: Any) -> Any:
    """Ein abgeleitetes Nachschlagewerk je Spiel, einmal gebaut und gemerkt."""
    key = (games_key(), kind, game_id)
    if key not in _derived_cache:
        _derived_cache[key] = build()
    return _derived_cache[key]


def catalog_locations(game_id: str) -> dict[str, dict[str, Any]]:
    return derived(
        "locations", game_id, lambda: {location["id"]: location for location in game_locations(game_id)}
    )


def resolve_game_id(value: Any) -> str:
    """Spielangabe auf eine Katalog-ID bringen.

    Bereits migrierte Staende tragen hier eine Slug-ID - die bleibt unangetastet,
    auch wenn der zugehoerige Katalog gerade nicht im Verzeichnis liegt. Nur der
    Freitext aus v2 wird abgebildet, sonst waere ein Run dauerhaft unerreichbar:
    das Frontend laedt zu jeder game_id einen Katalog und bricht bei 404 ab.
    """
    candidate = str(value or "").strip()
    if not candidate:
        return DEFAULT_GAME_ID
    if len(candidate) <= 80 and re.fullmatch(SLUG_PATTERN, candidate):
        return candidate

    mapped = LEGACY_GAME_NAMES.get(candidate.casefold())
    if mapped:
        return mapped
    slug = re.sub(r"[^a-z0-9]+", "-", candidate.casefold()).strip("-")
    return slug if slug in load_games() else DEFAULT_GAME_ID


def species_by_german_name(game_id: str) -> dict[str, str]:
    """Deutscher Pokémon-Name -> PokeAPI-Slug, für die Migration der Alt-Daten."""

    def build() -> dict[str, str]:
        lookup: dict[str, str] = {}
        for location in game_locations(game_id):
            for entry in location["encounters"]:
                lookup.setdefault(entry["name"].casefold(), entry["species"])
        return lookup

    return derived("species-by-name", game_id, build)


# --------------------------------------------------------------------------- #
# Modelle
# --------------------------------------------------------------------------- #


class Player(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=SLUG_PATTERN, min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=60)


class Pick(BaseModel):
    """Was ein Spieler an einem Ort gefangen hat."""

    model_config = ConfigDict(extra="forbid")

    species: str | None = Field(default=None, max_length=60)
    name: str = Field(default="", max_length=300)
    status: PickStatus = "alive"


class PickPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    species: str | None = None
    name: str | None = Field(default=None, max_length=300)
    status: PickStatus | None = None


class EncounterRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=SLUG_PATTERN, min_length=1, max_length=80)
    location_id: str | None = Field(default=None, max_length=80)
    order: int = Field(default=0, ge=0)
    encounter: str = Field(min_length=1, max_length=200)
    # 80 Zeichen, weil v2 hier Freitext zuliess - engere Grenzen kippen Bestandsdaten
    # beim Laden. Was beim Schreiben erlaubt ist, klaert validate_responsible().
    responsible_player: str | None = Field(default=None, max_length=80)
    outcome: Outcome = "pending"
    postgame: bool = False
    in_team: bool = False
    picks: dict[str, Pick] = Field(default_factory=dict)


class EncounterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encounter: str | None = Field(default=None, min_length=1, max_length=200)
    responsible_player: str | None = Field(default=None, max_length=80)
    outcome: Outcome | None = None
    in_team: bool | None = None
    picks: dict[str, PickPatch] | None = None


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=SLUG_PATTERN, min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    game_id: str = Field(max_length=80)
    status: RunStatus = "active"
    created_at: str
    completed_at: str | None = None
    progress: int = Field(default=0, ge=0)
    encounters: list[EncounterRow] = Field(default_factory=list)


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, pattern=SLUG_PATTERN, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    game_id: str = Field(max_length=80)
    make_current: bool = True
    prefill: bool = True
    include_postgame: bool = False


class RunPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: RunStatus | None = None
    progress: int | None = Field(default=None, ge=0)
    make_current: bool | None = None


class EncounterCollection(BaseModel):
    players: list[Player]
    run_id: str
    run_name: str
    game_id: str
    game_name: str | None
    progress: int
    encounters: list[EncounterRow]
    updated_at: str


class RunSummary(BaseModel):
    id: str
    name: str
    game_id: str
    game_name: str | None
    status: RunStatus
    created_at: str
    completed_at: str | None
    progress: int
    encounter_count: int
    team_count: int
    pending_count: int
    caught_count: int
    failed_count: int
    death_count: int


class Rules(BaseModel):
    """Werte, die das Frontend kennen muss, um dieselbe Sprache zu sprechen.

    Der Platzhalter fuer verlorene Encounter ist Teil des Protokolls: das
    Frontend schreibt ihn als Namen, die API leitet daraus 'failed' ab. Eine
    zweite Kopie im Frontend faellt beim Umbenennen still auseinander.
    """

    lost_label: str
    no_culprit: str
    team_size: int


class RunsCollection(BaseModel):
    players: list[Player]
    current_run_id: str
    runs: list[RunSummary]
    rules: Rules
    updated_at: str


class GameSummary(BaseModel):
    id: str
    name: str
    location_count: int


# --------------------------------------------------------------------------- #
# Persistenz
# --------------------------------------------------------------------------- #


def data_path() -> Path:
    return Path(os.environ.get("ENCOUNTER_DATA_PATH", "/var/lib/encounter-table-api/encounters.json"))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def next_updated_at(previous: str | None) -> str:
    """Streng monotoner Stand-Zeitstempel.

    Sekundengenau reicht hier nicht: zwei Schreibzugriffe in derselben Sekunde
    ergaeben denselben Wert, womit If-Match eine fremde Aenderung durchwinkt und
    das Polling sie fuer "nichts passiert" haelt.
    """
    stamp = datetime.now(timezone.utc)
    if previous:
        try:
            earlier = datetime.fromisoformat(previous)
        except ValueError:
            earlier = None
        if earlier and stamp <= earlier:
            stamp = earlier + timedelta(microseconds=1)
    return stamp.isoformat()


def is_placeholder(value: Any) -> bool:
    return str(value or "").startswith(PLACEHOLDER_PREFIXES)


def pick_is_filled(pick: dict[str, Any]) -> bool:
    return bool(pick.get("species")) or bool(str(pick.get("name") or "").strip())


def derive_outcome(picks: dict[str, Any], previous: str | None = None) -> Outcome:
    """Ergebnis einer Zeile aus den Picks ableiten.

    Ein Todesfall schlägt alles; danach zählt der Freitext für verlorene
    Encounter; ein einmal gesetztes 'failed' bleibt bestehen, solange niemand
    etwas eingetragen hat.
    """
    values = list(picks.values())
    if any(pick.get("status") == "dead" for pick in values):
        return "dead"
    if any(is_placeholder(pick.get("name")) for pick in values):
        return "failed"
    if any(pick_is_filled(pick) for pick in values):
        return "caught"
    return "failed" if previous == "failed" else "pending"


def legacy_location_id(row_id: str) -> str | None:
    if row_id in LEGACY_LOCATION_IDS:
        return LEGACY_LOCATION_IDS[row_id]
    match = re.fullmatch(r"route-(\d{3})", row_id)
    if match:
        number = match.group(1)
        prefix = "sinnoh-sea-route" if number in LEGACY_SEA_ROUTES else "sinnoh-route"
        return f"{prefix}-{number}"
    return None


def normalize_encounter(raw: dict[str, Any], player_ids: list[str], game_id: str) -> dict[str, Any]:
    row = dict(raw)
    # v3 -> v4: das Notizfeld ist ersatzlos weg. Der Wert muss hier verschwinden,
    # nicht nur unbeachtet bleiben: EncounterRow verbietet unbekannte Felder, ein
    # stehengebliebenes 'note' aus Altdaten liesse das Laden scheitern. Damit ist
    # das die Stelle, die den Text tatsaechlich loescht - vorher greift wegen des
    # Versionssprungs migration_backup().
    row.pop("note", None)
    row.setdefault("order", 0)
    row.setdefault("postgame", False)
    row.setdefault("in_team", False)

    if "picks" not in row:
        # Schema v2: mark/nikolai/knev als feste Felder plus *_status.
        names = species_by_german_name(game_id)
        picks: dict[str, Any] = {}
        for legacy_field, player_id in LEGACY_PLAYER_FIELDS.items():
            name = str(row.pop(legacy_field, "") or "")
            legacy_status = row.pop(f"{legacy_field}_status", "alive")
            picks[player_id] = {
                "species": None if is_placeholder(name) else names.get(name.casefold()),
                "name": name,
                "status": legacy_status if legacy_status in ("alive", "dead") else "alive",
            }
        row["picks"] = picks
        row.setdefault("location_id", legacy_location_id(str(row.get("id", ""))))

    row.setdefault("location_id", None)

    # 'order' steht im Katalog und wird in apply_catalog_moves() gesetzt - dort
    # ist der ganze Run im Blick, was fuers Zusammenlegen von Zeilen noetig ist.

    responsible = row.get("responsible_player")
    if responsible in LEGACY_PLAYER_LABELS:
        row["responsible_player"] = LEGACY_PLAYER_LABELS[responsible]
    elif isinstance(responsible, str) and len(responsible) > 80:
        # Lieber ein gekuerzter Schuldiger als eine Datei, die sich nicht mehr laedt.
        row["responsible_player"] = responsible[:80]

    # Fehlende Felder ergaenzt gleich das Pick-Modell; hier fehlt nur, dass jeder
    # Spieler ueberhaupt einen Eintrag hat und dass Altfelder verschwinden.
    picks = row["picks"]
    for player_id in player_ids:
        pick = dict(picks.get(player_id) or {})
        pick.pop("level", None)  # bis v3.0 erfasst, wird nicht mehr gefuehrt
        picks[player_id] = pick

    if row.get("outcome") not in OUTCOMES:
        row["outcome"] = derive_outcome(picks)

    return EncounterRow.model_validate(row).model_dump()


def filled_picks(row: dict[str, Any]) -> int:
    return sum(pick_is_filled(pick) for pick in row["picks"].values())


def merge_rows(keep: dict[str, Any], drop: dict[str, Any]) -> dict[str, Any]:
    """Zwei Zeilen desselben Ortes zu einer machen.

    Uebernommen wird nur, was in `keep` leer ist - andersherum wuerde ein leerer
    Platzhalter die eingetragenen Pokémon ueberschreiben.
    """
    for player_id, pick in drop["picks"].items():
        if pick_is_filled(pick) and not pick_is_filled(keep["picks"].get(player_id) or {}):
            keep["picks"][player_id] = pick
    if keep["outcome"] == "pending":
        keep["outcome"] = drop["outcome"]
    if not keep.get("responsible_player"):
        keep["responsible_player"] = drop.get("responsible_player")
    keep["in_team"] = keep["in_team"] or drop["in_team"]
    return keep


def apply_catalog_moves(rows: list[dict[str, Any]], game_id: str) -> list[dict[str, Any]]:
    """Die Zeilen eines Runs auf den aktuellen Katalog ziehen.

    Zwei Dinge, die nur mit Blick auf den ganzen Run gehen und deshalb nicht in
    `normalize_encounter` stehen:

    * Ein aufgeloester Ort (`RETIRED_LOCATIONS`) wandert auf seinen Nachfolger.
      Steht der schon als eigene Zeile im Run, treffen zwei Zeilen auf denselben
      Ort - dann bleibt die mit den Eintraegen, sonst gewaenne beim Zusammenlegen
      die leere und genau die gefangenen Pokémon waeren weg. Fehlt der Katalog
      gerade, bleibt die Zeile unangetastet: ein Ort, den niemand kennt, ist
      schlechter als ein veralteter.
    * `order` kommt frisch aus dem Katalog. Faellt ein Ort weg, verschieben sich
      alle nachfolgenden Nummern; Alt-Zeilen behielten sonst die Nummerierung von
      vorher und mischten sich falsch unter spaeter angelegte.
    """
    catalog = catalog_locations(game_id)
    retired = RETIRED_LOCATIONS.get(game_id, {})

    result: list[dict[str, Any]] = []
    index_of: dict[str, int] = {}

    for row in rows:
        successor = catalog.get(retired.get(row.get("location_id") or "", ""))
        if successor:
            row["id"] = successor["id"]
            row["location_id"] = successor["id"]
            row["encounter"] = successor["name"]

        location_id = row.get("location_id")
        at = index_of.get(location_id) if location_id else None
        if at is None:
            if location_id:
                index_of[location_id] = len(result)
            result.append(row)
            continue

        existing = result[at]
        # Die inhaltsreichere Zeile bleibt stehen, die andere geht in ihr auf.
        result[at] = (
            merge_rows(row, existing) if filled_picks(row) > filled_picks(existing) else merge_rows(existing, row)
        )

    for row in result:
        location = catalog.get(row.get("location_id") or "")
        if location:
            row["order"] = location["order"]

    return result


def normalize_run(raw: dict[str, Any], fallback_id: str, player_ids: list[str]) -> dict[str, Any]:
    run = dict(raw)
    run.setdefault("id", fallback_id)
    run.setdefault("name", f"Run {fallback_id.removeprefix('run-')}")
    run.setdefault("status", "active")
    run.setdefault("created_at", now_iso())
    run.setdefault("completed_at", None)
    run.setdefault("progress", 0)

    # v2 kannte nur einen freien Spielnamen, kein Spiel als Konzept. Das Feld muss
    # in jedem Fall weg - RunRecord verbietet Unbekanntes.
    legacy_game = run.pop("game", None)
    run["game_id"] = resolve_game_id(run.get("game_id") or legacy_game)

    rows = [normalize_encounter(row, player_ids, run["game_id"]) for row in run.get("encounters", [])]
    run["encounters"] = apply_catalog_moves(rows, run["game_id"])
    return RunRecord.model_validate(run).model_dump()


def normalize_state(raw: dict[str, Any]) -> dict[str, Any]:
    players = raw.get("players") or DEFAULT_PLAYERS
    if players and isinstance(players[0], str):
        # v2 fuehrte nur Anzeigenamen.
        players = [
            {"id": LEGACY_PLAYER_LABELS.get(name, re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")), "name": name}
            for name in players
        ]
    players = [
        Player.model_validate(player).model_dump() | {"name": LEGACY_DISPLAY_NAMES.get(player["name"], player["name"])}
        for player in players
    ]
    player_ids = [player["id"] for player in players]

    runs_raw = raw.get("runs")
    if runs_raw is None:
        # Ganz altes Format: eine flache Encounter-Liste ohne Runs.
        runs_raw = [
            {
                "id": "run-1",
                "name": "Run 1",
                "created_at": raw.get("updated_at") or now_iso(),
                "encounters": raw.get("encounters", []),
            }
        ]

    runs = [normalize_run(run, f"run-{index}", player_ids) for index, run in enumerate(runs_raw, start=1)]
    if not runs:
        return initial_state()

    current_run_id = raw.get("current_run_id") or runs[0]["id"]
    if not any(run["id"] == current_run_id for run in runs):
        current_run_id = runs[0]["id"]

    # Ein 'history'-Block aus alten Staenden faellt hier weg: die Auflistung ist
    # abschliessend, unbekannte Schluessel werden nicht uebernommen.
    return {
        "schema_version": SCHEMA_VERSION,
        "players": players,
        "current_run_id": current_run_id,
        "runs": runs,
        "updated_at": raw.get("updated_at") or now_iso(),
    }


def build_rows(game_id: str, include_postgame: bool, player_ids: list[str]) -> list[dict[str, Any]]:
    """Alle Orte eines Spiels als offene Zeilen anlegen."""
    rows = []
    for location in game_locations(game_id):
        if location.get("postgame") and not include_postgame:
            continue
        rows.append(
            EncounterRow(
                id=location["id"],
                location_id=location["id"],
                order=location["order"],
                encounter=location["name"],
                outcome="pending",
                postgame=bool(location.get("postgame")),
                picks={player_id: Pick() for player_id in player_ids},
            ).model_dump()
        )
    return rows


def initial_state() -> dict[str, Any]:
    players = [Player.model_validate(player).model_dump() for player in DEFAULT_PLAYERS]
    player_ids = [player["id"] for player in players]
    games = load_games()
    game_id = DEFAULT_GAME_ID if DEFAULT_GAME_ID in games else (next(iter(games), DEFAULT_GAME_ID))
    timestamp = now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "players": players,
        "current_run_id": "run-1",
        "runs": [
            {
                "id": "run-1",
                "name": "Run 1",
                "game_id": game_id,
                "status": "active",
                "created_at": timestamp,
                "completed_at": None,
                "progress": 0,
                "encounters": build_rows(game_id, include_postgame=False, player_ids=player_ids),
            }
        ],
        "updated_at": timestamp,
    }


# --------------------------------------------------------------------------- #
# Backups
# --------------------------------------------------------------------------- #


def backups_dir() -> Path:
    configured = os.environ.get("ENCOUNTER_BACKUP_DIR")
    return Path(configured) if configured else data_path().parent / "backups"


def daily_backup(source: Path) -> None:
    """Eine Kopie pro Tag, angelegt bevor der Tag zum ersten Mal ueberschrieben wird."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    directory = backups_dir()
    target = directory / f"{source.stem}-{stamp}.json"
    if target.exists():
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

        for outdated in sorted(directory.glob(f"{source.stem}-????-??-??.json"))[:-BACKUP_KEEP]:
            outdated.unlink(missing_ok=True)
    except OSError:
        pass  # ein fehlgeschlagenes Backup darf den Schreibzugriff nicht blockieren


def migration_backup(source: Path, from_version: Any) -> None:
    """Vor jeder Schema-Migration - die laeuft nur einmal und ist nicht umkehrbar."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    directory = backups_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, directory / f"migration-{source.stem}-v{from_version or 'unbekannt'}-{stamp}.json")
    except OSError:
        pass


def serialize_state(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, indent=2) + "\n"


def save_state(state: dict[str, Any]) -> None:
    target = data_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        daily_backup(target)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(serialize_state(state), encoding="utf-8")
    os.replace(temporary, target)
    _state_cache.update(fingerprint=state_fingerprint(target), state=state)


# Zuletzt geladener Stand, samt Fingerabdruck der Datei. Jeder Request laedt
# sonst neu: parsen, jede Zeile durch die Modelle schicken und das Ganze wieder
# serialisieren, nur um es mit dem Dateitext zu vergleichen.
_state_cache: dict[str, Any] = {}


def state_fingerprint(target: Path) -> tuple[Any, ...] | None:
    try:
        stat = target.stat()
    except OSError:
        return None
    return (str(target), stat.st_mtime_ns, stat.st_size)


def load_state() -> dict[str, Any]:
    target = data_path()
    if not target.exists():
        state = initial_state()
        save_state(state)
        return state

    fingerprint = state_fingerprint(target)
    if fingerprint is not None and _state_cache.get("fingerprint") == fingerprint:
        return _state_cache["state"]

    try:
        stored = target.read_text(encoding="utf-8")
        raw = json.loads(stored)
        state = normalize_state(raw)

        # Gegen den Dateitext vergleichen, nicht gegen das geparste Dict: die
        # normalize_*-Kette aendert verschachtelte Teile in-place, ein Vergleich
        # mit dem Eingabe-Dict wuerde Migrationen als "nichts geaendert" sehen.
        if serialize_state(state) != stored:
            if raw.get("schema_version") != SCHEMA_VERSION:
                migration_backup(target, raw.get("schema_version"))
            save_state(state)

        # Nach dem moeglichen Rueckschreiben abnehmen, sonst zeigt der Abdruck
        # auf den Stand vor der Migration und der Cache greift nie.
        _state_cache.update(fingerprint=state_fingerprint(target), state=state)
        return state
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise RuntimeError(f"Encounter-Daten sind ungültig: {target}") from exc


# --------------------------------------------------------------------------- #
# Schreibzugriff
# --------------------------------------------------------------------------- #


def require_write_token(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> None:
    """Token nur pruefen, wenn einer konfiguriert ist.

    Ohne ENCOUNTER_API_TOKEN ist die Tabelle offen beschreibbar - so gewollt.
    Wer das zumachen will, setzt die Variable; dann gilt wieder Bearer-Pflicht.
    """
    configured_token = os.environ.get("ENCOUNTER_API_TOKEN", "")
    if not configured_token:
        return
    supplied_token = credentials.credentials if credentials else ""
    if not secrets.compare_digest(supplied_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Für Schreibzugriffe ist ein gültiger Bearer-Token nötig.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@contextmanager
def mutate(if_match: str | None) -> Iterator[dict[str, Any]]:
    """Laden, pruefen, aendern, speichern - unter dem globalen Schreib-Lock."""
    with write_lock:
        # Auf einer Kopie arbeiten: bricht eine Regel den Vorgang ab, ist der
        # zwischengespeicherte Stand nicht schon halb veraendert.
        state = copy.deepcopy(load_state())
        if if_match and if_match.strip('"') != state["updated_at"]:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail="Die Tabelle wurde zwischenzeitlich geändert. Neu laden und erneut versuchen.",
            )
        yield state
        state["updated_at"] = next_updated_at(state.get("updated_at"))
        save_state(state)


@contextmanager
def write_to_run(if_match: str | None, run_id: str | None) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Schreibzugriff auf einen Run - benannt oder den aktuellen.

    Die Endpunkte fuer den aktuellen Run und die run-spezifischen unterscheiden
    sich nur hierin. Ohne gemeinsame Klammer driften die beiden Varianten
    derselben Operation auseinander.
    """
    with mutate(if_match) as state:
        yield state, find_run(state, run_id) if run_id is not None else current_run(state)


# --------------------------------------------------------------------------- #
# Nachschlagen
# --------------------------------------------------------------------------- #


def find_run(state: dict[str, Any], run_id: str) -> dict[str, Any]:
    for run in state["runs"]:
        if run["id"] == run_id:
            return run
    raise HTTPException(status_code=404, detail=f"Run '{run_id}' nicht gefunden.")


def current_run(state: dict[str, Any]) -> dict[str, Any]:
    return find_run(state, state["current_run_id"])


def find_row(run: dict[str, Any], row_id: str) -> dict[str, Any]:
    for row in run["encounters"]:
        if row["id"] == row_id:
            return row
    raise HTTPException(status_code=404, detail=f"Encounter '{row_id}' in Run '{run['id']}' nicht gefunden.")


def player_ids_of(state: dict[str, Any]) -> list[str]:
    return [player["id"] for player in state["players"]]


def game_name_of(game_id: str) -> str | None:
    game = game_or_none(game_id)
    return game["name"] if game else None


def clamp_progress(game_id: str, value: int) -> int:
    """Fortschritt zaehlt Level-Caps ab - mehr als der Katalog kennt, gibt es nicht.

    Die Grenze gehoert auf den Schreibpfad und nicht nur ins Frontend, sonst
    laufen andere Clients aus dem Wertebereich, den renderCaps erwartet.
    """
    game = game_or_none(game_id)
    if game is None:
        return max(value, 0)
    return max(0, min(value, len(game.get("level_caps") or [])))


def collection_for(state: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    return {
        "players": state["players"],
        "run_id": run["id"],
        "run_name": run["name"],
        "game_id": run["game_id"],
        "game_name": game_name_of(run["game_id"]),
        "progress": run["progress"],
        "encounters": run["encounters"],
        "updated_at": state["updated_at"],
    }


def row_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "encounter_count": len(rows),
        "team_count": sum(bool(row.get("in_team")) for row in rows),
        "pending_count": sum(row["outcome"] == "pending" for row in rows),
        "caught_count": sum(row["outcome"] == "caught" for row in rows),
        "failed_count": sum(row["outcome"] == "failed" for row in rows),
        "death_count": sum(
            row["outcome"] == "dead" or any(pick["status"] == "dead" for pick in row["picks"].values()) for row in rows
        ),
    }


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    base = {key: run[key] for key in ("id", "name", "game_id", "status", "created_at", "completed_at", "progress")}
    return base | {"game_name": game_name_of(run["game_id"])} | row_counts(run["encounters"])


def slugify_run_id(name: str, existing_ids: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "run"
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


# --------------------------------------------------------------------------- #
# Aendern
# --------------------------------------------------------------------------- #


def allowed_species(game_id: str) -> dict[str, set[str]]:
    """Ort -> fangbare Arten."""

    def build() -> dict[str, set[str]]:
        return {
            location["id"]: {entry["species"] for entry in location["encounters"]}
            for location in game_locations(game_id)
        }

    return derived("allowed-species", game_id, build)


def validate_species(run: dict[str, Any], row: dict[str, Any], picks: dict[str, Any], force: bool) -> None:
    """Nur Pokémon zulassen, die es an diesem Ort ueberhaupt gibt."""
    if force or not row.get("location_id"):
        return
    allowed = allowed_species(run["game_id"]).get(row["location_id"])
    if allowed is None:
        return
    for player_id, pick in picks.items():
        species = pick.get("species")
        if species and species not in allowed:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"'{species}' ist an '{row['encounter']}' nicht fangbar "
                    f"(Spieler '{player_id}'). Mit force=true trotzdem speichern."
                ),
            )


def reject_null_fields(updates: dict[str, Any], nullable: set[str]) -> None:
    """Ausdrueckliches null nur dort zulassen, wo es ein Feld auch leeren kann.

    Ohne diese Pruefung landet das None im Datensatz und erst die Modellpruefung
    am Ende schlaegt fehl - der Aufrufer saehe einen 500er statt eines Hinweises.
    """
    invalid = sorted(key for key, value in updates.items() if value is None and key not in nullable)
    if invalid:
        raise HTTPException(status_code=422, detail=f"Diese Felder dürfen nicht null sein: {', '.join(invalid)}.")


def validate_responsible(value: Any, player_ids: list[str]) -> None:
    if value is None or value == NO_CULPRIT or value in player_ids:
        return
    allowed = ", ".join([*player_ids, NO_CULPRIT])
    raise HTTPException(status_code=422, detail=f"'{value}' ist kein gültiger Schuldiger (erlaubt: {allowed}).")


def require_culprit(row: dict[str, Any]) -> None:
    """Ohne Schuldigen fehlt der Vorfall in der Statistik - also gleich einfordern."""
    if row["outcome"] in ("dead", "failed") and not row.get("responsible_player"):
        incident = "Tod" if row["outcome"] == "dead" else "verlorener Encounter"
        raise HTTPException(
            status_code=422,
            detail=(
                f"Bei '{row['encounter']}' fehlt der Schuldige ({incident}). "
                f"Spieler eintragen oder ausdrücklich '{NO_CULPRIT}', wenn niemand schuld war."
            ),
        )


def require_team_slot(run: dict[str, Any], row: dict[str, Any]) -> None:
    """Mehr als sechs Links gleichzeitig gehen nicht - erst einer raus."""
    active = [entry for entry in run["encounters"] if entry.get("in_team") and entry["id"] != row["id"]]
    if len(active) >= TEAM_SIZE:
        current = ", ".join(entry["encounter"] for entry in active)
        raise HTTPException(
            status_code=409,
            detail=f"Das Team ist voll ({TEAM_SIZE} Links). Erst einen herausnehmen. Aktuell dabei: {current}.",
        )


def team_ready(row: dict[str, Any]) -> bool:
    """Ein Link belegt einen Platz fuer alle - also braucht jeder ein lebendes Pokémon.

    Das Outcome allein reicht als Kriterium nicht: 'caught' steht schon, sobald
    ein einziger Spieler etwas eingetragen hat.
    """
    picks = list(row["picks"].values())
    if row["outcome"] != "caught" or not picks:
        return False
    return all(pick_is_filled(pick) and pick.get("status") != "dead" for pick in picks)


def apply_team_rules(run: dict[str, Any], row: dict[str, Any], requested: bool | None) -> None:
    """Nur vollstaendige, lebende Reihen spielen mit."""
    ready = team_ready(row)
    if requested and not ready:
        raise HTTPException(
            status_code=422,
            detail="Nur Reihen, in denen alle drei ein lebendes Pokémon haben, können ins Team.",
        )
    if not ready:
        row["in_team"] = False
    elif requested:
        require_team_slot(run, row)


def require_known_players(picks: dict[str, Any], player_ids: list[str]) -> None:
    unknown = set(picks) - set(player_ids)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unbekannte Spieler: {', '.join(sorted(unknown))}")


def require_consistent_outcome(row: dict[str, Any]) -> None:
    """'dead' lebt in den Picks, nicht im Outcome-Feld.

    Ohne toten Pick waere der Tod nicht haltbar: die naechste Aenderung an der
    Zeile leitet das Outcome neu ab und macht stillschweigend wieder 'caught'
    daraus - der Vorfall verschwaende aus der Statistik.
    """
    if row["outcome"] == "dead" and not any(pick["status"] == "dead" for pick in row["picks"].values()):
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{row['encounter']}' lässt sich ohne Kopplung nicht auf 'tot' setzen. "
                "Den Status der betroffenen Pokémon setzen."
            ),
        )


def couple_deaths(row: dict[str, Any], responsible: str | None, requested_outcome: str | None = None) -> bool:
    """Soullink: stirbt ein Pokémon der Reihe, sterben alle.

    Greift auch, wenn die Zeile selbst auf 'dead' gesetzt wird - sonst stuende
    dort ein Tod, den kein einziger Pick traegt.

    Gibt True zurueck, wenn die Kopplung etwas veraendert hat.
    """
    picks = row["picks"]
    if requested_outcome != "dead" and not any(pick["status"] == "dead" for pick in picks.values()):
        return False

    changed = False
    for pick in picks.values():
        if pick["status"] != "dead":
            pick["status"] = "dead"
            changed = True
    row["outcome"] = "dead"
    if responsible and not row.get("responsible_player"):
        row["responsible_player"] = responsible
    return changed


def couple_failure(row: dict[str, Any], requested_outcome: str | None) -> bool:
    """Ein verlorener Encounter ist fuer die ganze Reihe verloren.

    Wird die Zeile auf 'failed' gesetzt, tragen alle Spieler den Platzhalter -
    ausser jemand ist tot, dann gilt der Tod und nicht der verlorene Encounter.
    """
    if requested_outcome != "failed":
        return False
    if any(pick["status"] == "dead" for pick in row["picks"].values()):
        return False

    changed = False
    for pick in row["picks"].values():
        if pick["name"] != LOST_LABEL or pick["species"] is not None:
            pick["species"] = None
            pick["name"] = LOST_LABEL
            changed = True
    return changed


def apply_encounter_patch(
    run: dict[str, Any],
    row_id: str,
    changes: EncounterPatch,
    *,
    couple: bool,
    force: bool,
    player_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    updates = changes.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Mindestens ein Feld muss angegeben werden.")
    reject_null_fields(updates, NULLABLE_ROW_FIELDS)

    row = find_row(run, row_id)
    before = json.loads(json.dumps(row))

    pick_updates = updates.pop("picks", None) or {}
    require_known_players(pick_updates, player_ids)

    merged_picks = {player_id: dict(row["picks"][player_id]) for player_id in player_ids}
    for player_id, pick_patch in pick_updates.items():
        merged_picks[player_id].update({key: value for key, value in pick_patch.items() if key in Pick.model_fields})

    # Nur pruefen, was dieser Patch wirklich anfasst - sonst blockiert ein einmal
    # per force gespeicherter Sonderfall jede spaetere Aenderung am selben Pick,
    # bis hin zum Kill-Button, der nur den Status setzt.
    touched_species = {
        player_id: merged_picks[player_id] for player_id, patch in pick_updates.items() if "species" in patch
    }
    validate_species(run, row, touched_species, force)

    row["picks"] = merged_picks
    row.update(updates)

    if couple:
        couple_deaths(row, updates.get("responsible_player") or row.get("responsible_player"), updates.get("outcome"))
        couple_failure(row, updates.get("outcome"))
    if "outcome" not in updates:
        row["outcome"] = derive_outcome(row["picks"], before.get("outcome"))

    require_consistent_outcome(row)
    apply_team_rules(run, row, updates.get("in_team"))
    if "responsible_player" in updates:
        validate_responsible(updates["responsible_player"], player_ids)
    require_culprit(row)

    return EncounterRow.model_validate(row).model_dump(), before


def replace_row(run: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    for index, existing in enumerate(run["encounters"]):
        if existing["id"] == row["id"]:
            run["encounters"][index] = row
            return row
    run["encounters"].append(row)
    return row


# --------------------------------------------------------------------------- #
# Lesen
# --------------------------------------------------------------------------- #


@app.get("/", summary="Überblick")
def api_overview() -> dict[str, Any]:
    return {
        "name": "Pokémon Encounter API",
        "schema_version": SCHEMA_VERSION,
        "read": "GET /games, GET /runs, GET /encounters, GET /stats",
        "write": "POST/PATCH/DELETE; Bearer-Token nur nötig, wenn ENCOUNTER_API_TOKEN gesetzt ist",
        "openapi": "/openapi.json",
    }


@app.get("/games", response_model=list[GameSummary], summary="Verfügbare Spiele")
def get_games() -> list[dict[str, Any]]:
    return [
        {"id": game["id"], "name": game["name"], "location_count": len(game["locations"])}
        for game in sorted(load_games().values(), key=lambda entry: entry["name"])
    ]


@app.get("/games/{game_id}", summary="Katalog eines Spiels")
def get_game(game_id: str) -> dict[str, Any]:
    return find_game(game_id)


@app.get("/encounters", response_model=EncounterCollection, summary="Aktuellen Run lesen")
def get_encounters() -> dict[str, Any]:
    state = load_state()
    return collection_for(state, current_run(state))


@app.get("/encounters/{row_id}", response_model=EncounterRow, summary="Eine Zeile des aktuellen Runs")
def get_encounter(row_id: str) -> dict[str, Any]:
    state = load_state()
    return find_row(current_run(state), row_id)


@app.get("/runs", response_model=RunsCollection, summary="Alle Runs")
def get_runs() -> dict[str, Any]:
    state = load_state()
    return {
        "players": state["players"],
        "current_run_id": state["current_run_id"],
        "runs": [run_summary(run) for run in state["runs"]],
        "rules": {
            "lost_label": LOST_LABEL,
            "no_culprit": NO_CULPRIT,
            "team_size": TEAM_SIZE,
        },
        "updated_at": state["updated_at"],
    }


@app.get("/runs/{run_id}", response_model=RunRecord, summary="Einen Run lesen")
def get_run(run_id: str) -> dict[str, Any]:
    return find_run(load_state(), run_id)


@app.get("/runs/{run_id}/encounters", response_model=EncounterCollection, summary="Encounter eines Runs")
def get_run_encounters(run_id: str) -> dict[str, Any]:
    state = load_state()
    return collection_for(state, find_run(state, run_id))


# --------------------------------------------------------------------------- #
# Schreiben
# --------------------------------------------------------------------------- #


@app.post(
    "/runs",
    response_model=RunRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_token)],
    summary="Run anlegen",
)
def create_run(
    run: RunCreate,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    find_game(run.game_id)
    with mutate(if_match) as state:
        existing_ids = {entry["id"] for entry in state["runs"]}
        run_id = run.id or slugify_run_id(run.name, existing_ids)
        if run_id in existing_ids:
            raise HTTPException(status_code=409, detail=f"Run '{run_id}' existiert bereits.")

        rows = build_rows(run.game_id, run.include_postgame, player_ids_of(state)) if run.prefill else []
        created = RunRecord(
            id=run_id,
            name=run.name,
            game_id=run.game_id,
            created_at=now_iso(),
            encounters=[EncounterRow.model_validate(row) for row in rows],
        ).model_dump()
        state["runs"].append(created)
        if run.make_current:
            state["current_run_id"] = run_id
        return created


@app.patch(
    "/runs/{run_id}",
    response_model=RunRecord,
    dependencies=[Depends(require_write_token)],
    summary="Run bearbeiten",
)
def patch_run(
    run_id: str,
    changes: RunPatch,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    updates = changes.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Mindestens ein Feld muss angegeben werden.")
    make_current = updates.pop("make_current", None)
    reject_null_fields(updates, NULLABLE_RUN_FIELDS)

    with mutate(if_match) as state:
        run = find_run(state, run_id)
        if make_current:
            state["current_run_id"] = run_id
        if "progress" in updates:
            updates["progress"] = clamp_progress(run["game_id"], updates["progress"])
        if updates.get("status") == "completed" and run["status"] != "completed":
            run["completed_at"] = now_iso()
        elif updates.get("status") == "active":
            run["completed_at"] = None
        run.update(updates)
        return run


@app.post(
    "/runs/{run_id}/encounters",
    response_model=EncounterRow,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_token)],
    summary="Zeile zu einem Run hinzufügen",
)
def create_run_encounter(
    run_id: str,
    row: EncounterRow,
    force: bool = Query(default=False),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    with write_to_run(if_match, run_id) as (state, run):
        return add_row(state, run, row, force=force)


@app.patch(
    "/runs/{run_id}/encounters/{row_id}",
    response_model=EncounterRow,
    dependencies=[Depends(require_write_token)],
    summary="Zeile eines Runs ändern",
)
def patch_run_encounter(
    run_id: str,
    row_id: str,
    changes: EncounterPatch,
    couple: bool = Query(default=True, description="Soullink-Kopplung anwenden"),
    force: bool = Query(default=False, description="Species-Prüfung übergehen"),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    with write_to_run(if_match, run_id) as (state, run):
        return patch_row(state, run, row_id, changes, couple=couple, force=force)


@app.delete(
    "/runs/{run_id}/encounters/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_write_token)],
    summary="Zeile eines Runs löschen",
)
def delete_run_encounter(
    run_id: str,
    row_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> Response:
    with write_to_run(if_match, run_id) as (state, run):
        remove_row(run, row_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/encounters",
    response_model=EncounterRow,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_token)],
    summary="Zeile im aktuellen Run anlegen",
)
def create_encounter(
    row: EncounterRow,
    force: bool = Query(default=False),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    with write_to_run(if_match, None) as (state, run):
        return add_row(state, run, row, force=force)


@app.patch(
    "/encounters/{row_id}",
    response_model=EncounterRow,
    dependencies=[Depends(require_write_token)],
    summary="Zeile im aktuellen Run ändern",
)
def patch_encounter(
    row_id: str,
    changes: EncounterPatch,
    couple: bool = Query(default=True, description="Soullink-Kopplung anwenden"),
    force: bool = Query(default=False, description="Species-Prüfung übergehen"),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    with write_to_run(if_match, None) as (state, run):
        return patch_row(state, run, row_id, changes, couple=couple, force=force)


@app.delete(
    "/encounters/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_write_token)],
    summary="Zeile im aktuellen Run löschen",
)
def delete_encounter(
    row_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> Response:
    with write_to_run(if_match, None) as (state, run):
        remove_row(run, row_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)



# --------------------------------------------------------------------------- #
# Gemeinsame Schreiblogik
# --------------------------------------------------------------------------- #


def add_row(
    state: dict[str, Any],
    run: dict[str, Any],
    row: EncounterRow,
    *,
    force: bool,
) -> dict[str, Any]:
    if any(existing["id"] == row.id for existing in run["encounters"]):
        raise HTTPException(status_code=409, detail=f"Encounter '{row.id}' existiert in Run '{run['id']}' bereits.")

    player_ids = player_ids_of(state)
    record = row.model_dump()
    require_known_players(record["picks"], player_ids)
    for player_id in player_ids:
        record["picks"].setdefault(player_id, Pick().model_dump())
    validate_species(run, record, record["picks"], force)
    record["outcome"] = row.outcome if "outcome" in row.model_fields_set else derive_outcome(record["picks"])

    # Dieselbe Regelkette wie beim Patch - sonst entstehen ueber POST Zeilen,
    # die ueber PATCH nie entstehen koennten.
    couple_deaths(record, record.get("responsible_player"), record["outcome"])
    couple_failure(record, record["outcome"])
    require_consistent_outcome(record)
    apply_team_rules(run, record, record["in_team"])
    validate_responsible(record.get("responsible_player"), player_ids)
    require_culprit(record)

    run["encounters"].append(record)
    return record


def patch_row(
    state: dict[str, Any],
    run: dict[str, Any],
    row_id: str,
    changes: EncounterPatch,
    *,
    couple: bool,
    force: bool,
) -> dict[str, Any]:
    updated, _ = apply_encounter_patch(
        run, row_id, changes, couple=couple, force=force, player_ids=player_ids_of(state)
    )
    replace_row(run, updated)
    return updated


def remove_row(run: dict[str, Any], row_id: str) -> None:
    find_row(run, row_id)  # nur wegen des 404, wenn es die Zeile gar nicht gibt
    run["encounters"] = [entry for entry in run["encounters"] if entry["id"] != row_id]


# --------------------------------------------------------------------------- #
# Statistik
# --------------------------------------------------------------------------- #


@app.get("/stats", summary="Negativstatistik über alle Runs oder einen Run")
def get_stats(
    run_id: str | None = Query(default=None),
    game_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Wer hat was verbockt.

    Gezählt wird ausschließlich, was schiefgegangen ist, und zwar beim
    Verursacher. Ein gekoppelter Tod kostet die Reihe zwar drei Pokémon, zählt
    aber als **ein** Tod - nämlich der des Spielers, der ihn verschuldet hat.
    Dasselbe gilt für einen vergeigten Encounter.

    Schuld = verschuldete Tode + vergeigte Encounter.
    """
    state = load_state()
    runs = state["runs"]
    if run_id is not None:
        runs = [find_run(state, run_id)]
    if game_id is not None:
        runs = [run for run in runs if run["game_id"] == game_id]

    player_ids = player_ids_of(state)
    # Tod und vergeigter Encounter werden identisch verbucht - nur in andere
    # Toepfe. Ein Zweig pro Outcome liefe unweigerlich auseinander.
    by_player = {outcome: {player_id: 0 for player_id in player_ids} for outcome in ("dead", "failed")}
    unassigned = {"dead": 0, "failed": 0}
    per_run = []

    for run in runs:
        run_counts = {"dead": 0, "failed": 0}
        for row in run["encounters"]:
            outcome = row["outcome"]
            if outcome not in run_counts:
                continue
            run_counts[outcome] += 1
            responsible = row.get("responsible_player")
            if responsible in by_player[outcome]:
                by_player[outcome][responsible] += 1
            else:
                unassigned[outcome] += 1

        per_run.append(
            {
                "id": run["id"],
                "name": run["name"],
                "game_id": run["game_id"],
                "game_name": game_name_of(run["game_id"]),
                "status": run["status"],
                "deaths": run_counts["dead"],
                "failed_encounters": run_counts["failed"],
            }
        )

    deaths, failed = by_player["dead"], by_player["failed"]
    unassigned_deaths, unassigned_failed = unassigned["dead"], unassigned["failed"]
    blame = {player_id: deaths[player_id] + failed[player_id] for player_id in player_ids}
    total_deaths = sum(deaths.values()) + unassigned_deaths
    total_failed = sum(failed.values()) + unassigned_failed

    return {
        "scope": run_id or game_id or "all-time",
        "players": state["players"],
        "total_runs": len(runs),
        "total_deaths": total_deaths,
        "total_failed_encounters": total_failed,
        "total_blame": total_deaths + total_failed,
        "deaths_by_player": deaths,
        "failed_encounters_by_player": failed,
        "blame_by_player": blame,
        # Zeilen, bei denen niemand als Schuldiger eingetragen ist.
        "unassigned_deaths": unassigned_deaths,
        "unassigned_failed_encounters": unassigned_failed,
        "runs": per_run,
        "updated_at": state["updated_at"],
    }
