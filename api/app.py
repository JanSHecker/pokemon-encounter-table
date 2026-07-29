from __future__ import annotations

import json
import os
import re
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 3
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

Outcome = Literal["pending", "caught", "dead", "failed"]
PickStatus = Literal["alive", "dead"]
RunStatus = Literal["active", "completed"]

DEFAULT_PLAYERS = [
    {"id": "marc", "name": "Marc"},
    {"id": "nicolai", "name": "Nicolai"},
    {"id": "knev", "name": "KNEV"},
]
DEFAULT_GAME_ID = "platinum"

# Freitext, der einen verlorenen Encounter markiert (Alt-Daten und weiterhin erlaubt).
PLACEHOLDER_PREFIXES = ("Encounter verloren", "Kein Encounter")
LOST_LABEL = PLACEHOLDER_PREFIXES[0]

# Die drei Spieler hiessen bis Schema v2 anders und steckten als feste Felder in jeder Zeile.
LEGACY_PLAYER_FIELDS = {"mark": "marc", "nikolai": "nicolai", "knev": "knev"}
LEGACY_PLAYER_LABELS = {"Mark": "marc", "Nikolai": "nicolai", "KNEV": "knev"}

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

HISTORY_LIMIT = 500

app = FastAPI(
    title="Pokémon Encounter API",
    version="3.0.0",
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


def load_games() -> dict[str, dict[str, Any]]:
    """Kataloge lesen und je Verzeichnis cachen (Tests zeigen auf eigene Fixtures)."""
    directory = games_path()
    key = str(directory.resolve()) if directory.exists() else str(directory)
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


def find_game(game_id: str) -> dict[str, Any]:
    games = load_games()
    if game_id not in games:
        known = ", ".join(sorted(games)) or "keine"
        raise HTTPException(status_code=404, detail=f"Spiel '{game_id}' nicht gefunden (bekannt: {known}).")
    return games[game_id]


def catalog_locations(game_id: str) -> dict[str, dict[str, Any]]:
    games = load_games()
    if game_id not in games:
        return {}
    return {location["id"]: location for location in games[game_id]["locations"]}


def species_by_german_name(game_id: str) -> dict[str, str]:
    """Deutscher Pokémon-Name -> PokeAPI-Slug, für die Migration der Alt-Daten."""
    lookup: dict[str, str] = {}
    games = load_games()
    if game_id not in games:
        return lookup
    for location in games[game_id]["locations"]:
        for entry in location["encounters"]:
            lookup.setdefault(entry["name"].casefold(), entry["species"])
    return lookup


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
    note: str | None = Field(default=None, max_length=500)
    responsible_player: str | None = Field(default=None, max_length=40)
    outcome: Outcome = "pending"
    postgame: bool = False
    picks: dict[str, Pick] = Field(default_factory=dict)


class EncounterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encounter: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    responsible_player: str | None = Field(default=None, max_length=40)
    outcome: Outcome | None = None
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
    pending_count: int
    caught_count: int
    failed_count: int
    death_count: int


class RunsCollection(BaseModel):
    players: list[Player]
    current_run_id: str
    runs: list[RunSummary]
    updated_at: str


class GameSummary(BaseModel):
    id: str
    name: str
    location_count: int


class HistoryEntry(BaseModel):
    id: str
    at: str
    author: str | None
    action: str
    run_id: str
    row_id: str | None
    summary: str
    undone: bool


class HistoryCollection(BaseModel):
    entries: list[HistoryEntry]
    updated_at: str


# --------------------------------------------------------------------------- #
# Persistenz
# --------------------------------------------------------------------------- #


def data_path() -> Path:
    return Path(os.environ.get("ENCOUNTER_DATA_PATH", "/var/lib/encounter-table-api/encounters.json"))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    row.setdefault("note", None)
    row.setdefault("order", 0)
    row.setdefault("postgame", False)

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

    responsible = row.get("responsible_player")
    if responsible in LEGACY_PLAYER_LABELS:
        row["responsible_player"] = LEGACY_PLAYER_LABELS[responsible]

    picks = row["picks"]
    for player_id in player_ids:
        pick = dict(picks.get(player_id) or {})
        pick.setdefault("species", None)
        pick.setdefault("name", "")
        pick.setdefault("status", "alive")
        pick.pop("level", None)  # bis v3.0 erfasst, wird nicht mehr gefuehrt
        picks[player_id] = pick

    row["outcome"] = row.get("outcome") or derive_outcome(picks)
    if row["outcome"] not in ("pending", "caught", "dead", "failed"):
        row["outcome"] = derive_outcome(picks)

    return EncounterRow.model_validate(row).model_dump()


def normalize_run(raw: dict[str, Any], fallback_id: str, player_ids: list[str]) -> dict[str, Any]:
    run = dict(raw)
    run.setdefault("id", fallback_id)
    run.setdefault("name", f"Run {fallback_id.removeprefix('run-')}")
    run.setdefault("status", "active")
    run.setdefault("created_at", now_iso())
    run.setdefault("completed_at", None)
    run.setdefault("progress", 0)

    # v2 kannte nur einen freien Spielnamen, kein Spiel als Konzept.
    game_id = run.pop("game", None) if "game_id" not in run else run.get("game_id")
    run["game_id"] = game_id or DEFAULT_GAME_ID

    run["encounters"] = [normalize_encounter(row, player_ids, run["game_id"]) for row in run.get("encounters", [])]
    return RunRecord.model_validate(run).model_dump()


def normalize_state(raw: dict[str, Any]) -> dict[str, Any]:
    players = raw.get("players") or DEFAULT_PLAYERS
    if players and isinstance(players[0], str):
        # v2 fuehrte nur Anzeigenamen.
        players = [
            {"id": LEGACY_PLAYER_LABELS.get(name, re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")), "name": name}
            for name in players
        ]
        by_id = {player["id"]: player for player in players}
        for default in DEFAULT_PLAYERS:
            if default["id"] in by_id:
                by_id[default["id"]]["name"] = default["name"]
    players = [Player.model_validate(player).model_dump() for player in players]
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

    history = [entry for entry in raw.get("history", []) if isinstance(entry, dict)][-HISTORY_LIMIT:]
    # Fortlaufende Nummer, damit Historien-IDs nach dem Kuerzen nicht kollidieren.
    history_seq = int(raw.get("history_seq") or 0)
    for entry in history:
        match = re.fullmatch(r"h-(\d+)", str(entry.get("id", "")))
        if match:
            history_seq = max(history_seq, int(match.group(1)))

    return {
        "schema_version": SCHEMA_VERSION,
        "players": players,
        "current_run_id": current_run_id,
        "runs": runs,
        "history": history,
        "history_seq": history_seq,
        "updated_at": raw.get("updated_at") or now_iso(),
    }


def build_rows(game_id: str, include_postgame: bool, player_ids: list[str]) -> list[dict[str, Any]]:
    """Alle Orte eines Spiels als offene Zeilen anlegen."""
    games = load_games()
    if game_id not in games:
        return []
    rows = []
    for location in games[game_id]["locations"]:
        if location.get("postgame") and not include_postgame:
            continue
        rows.append(
            EncounterRow(
                id=location["id"],
                location_id=location["id"],
                order=location["order"],
                encounter=location["name"],
                note=location.get("note"),
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
        "history": [],
        "history_seq": 0,
        "updated_at": timestamp,
    }


def serialize_state(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, indent=2) + "\n"


def save_state(state: dict[str, Any]) -> None:
    target = data_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(serialize_state(state), encoding="utf-8")
    os.replace(temporary, target)


def load_state() -> dict[str, Any]:
    target = data_path()
    if not target.exists():
        state = initial_state()
        save_state(state)
        return state
    try:
        stored = target.read_text(encoding="utf-8")
        state = normalize_state(json.loads(stored))
        # Gegen den Dateitext vergleichen, nicht gegen das geparste Dict: die
        # normalize_*-Kette aendert verschachtelte Teile in-place, ein Vergleich
        # mit dem Eingabe-Dict wuerde Migrationen als "nichts geaendert" sehen.
        if serialize_state(state) != stored:
            save_state(state)
        return state
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise RuntimeError(f"Encounter data is invalid: {target}") from exc


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


def author_from_header(x_encounter_author: str | None = Header(default=None)) -> str | None:
    if not x_encounter_author:
        return None
    return x_encounter_author.strip()[:80] or None


@contextmanager
def mutate(if_match: str | None) -> Iterator[dict[str, Any]]:
    """Laden, pruefen, aendern, speichern - unter dem globalen Schreib-Lock."""
    with write_lock:
        state = load_state()
        if if_match and if_match.strip('"') != state["updated_at"]:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail="Die Tabelle wurde zwischenzeitlich geändert. Neu laden und erneut versuchen.",
            )
        yield state
        state["updated_at"] = now_iso()
        save_state(state)


def record_history(
    state: dict[str, Any],
    *,
    author: str | None,
    action: str,
    run_id: str,
    row_id: str | None,
    summary: str,
    before: Any = None,
    after: Any = None,
) -> dict[str, Any]:
    state["history_seq"] = int(state.get("history_seq", 0)) + 1
    entry = {
        "id": f"h-{state['history_seq']}",
        "at": now_iso(),
        "author": author,
        "action": action,
        "run_id": run_id,
        "row_id": row_id,
        "summary": summary,
        "before": before,
        "after": after,
        "undone": False,
    }
    state["history"].append(entry)
    del state["history"][:-HISTORY_LIMIT]
    return entry


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
    games = load_games()
    game = games.get(game_id)
    return game["name"] if game else None


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


def validate_species(run: dict[str, Any], row: dict[str, Any], picks: dict[str, Any], force: bool) -> None:
    """Nur Pokémon zulassen, die es an diesem Ort ueberhaupt gibt."""
    if force or not row.get("location_id"):
        return
    locations = catalog_locations(run["game_id"])
    location = locations.get(row["location_id"])
    if location is None:
        return
    allowed = {entry["species"] for entry in location["encounters"]}
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


def couple_deaths(row: dict[str, Any], responsible: str | None) -> bool:
    """Soullink: stirbt ein Pokémon der Reihe, sterben alle.

    Gibt True zurueck, wenn die Kopplung etwas veraendert hat.
    """
    picks = row["picks"]
    if not any(pick["status"] == "dead" for pick in picks.values()):
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

    row = find_row(run, row_id)
    before = json.loads(json.dumps(row))

    pick_updates = updates.pop("picks", None) or {}
    unknown = set(pick_updates) - set(player_ids)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unbekannte Spieler: {', '.join(sorted(unknown))}")

    merged_picks = {player_id: dict(row["picks"][player_id]) for player_id in player_ids}
    for player_id, pick_patch in pick_updates.items():
        merged_picks[player_id].update({key: value for key, value in pick_patch.items() if key in Pick.model_fields})

    # Nur pruefen, was dieser Patch anfasst - sonst blockiert ein einmal per force
    # gespeicherter Sonderfall jede spaetere Aenderung an derselben Zeile.
    validate_species(run, row, {player_id: merged_picks[player_id] for player_id in pick_updates}, force)

    row["picks"] = merged_picks
    row.update(updates)

    if couple:
        couple_deaths(row, updates.get("responsible_player") or row.get("responsible_player"))
        couple_failure(row, updates.get("outcome"))
    if "outcome" not in updates:
        row["outcome"] = derive_outcome(row["picks"], before.get("outcome"))

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
        "read": "GET /games, GET /runs, GET /encounters, GET /stats, GET /history",
        "write": "POST/PATCH/DELETE; Bearer-Token nur nötig, wenn ENCOUNTER_API_TOKEN gesetzt ist",
        "author_header": "X-Encounter-Author",
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
        "updated_at": state["updated_at"],
    }


@app.get("/runs/{run_id}", response_model=RunRecord, summary="Einen Run lesen")
def get_run(run_id: str) -> dict[str, Any]:
    return find_run(load_state(), run_id)


@app.get("/runs/{run_id}/encounters", response_model=EncounterCollection, summary="Encounter eines Runs")
def get_run_encounters(run_id: str) -> dict[str, Any]:
    state = load_state()
    return collection_for(state, find_run(state, run_id))


@app.get("/history", response_model=HistoryCollection, summary="Änderungshistorie")
def get_history(limit: int = Query(default=50, ge=1, le=HISTORY_LIMIT)) -> dict[str, Any]:
    state = load_state()
    entries = [
        {key: entry.get(key) for key in ("id", "at", "author", "action", "run_id", "row_id", "summary", "undone")}
        for entry in reversed(state["history"][-limit:])
    ]
    return {"entries": entries, "updated_at": state["updated_at"]}


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
    author: str | None = Depends(author_from_header),
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
        record_history(
            state,
            author=author,
            action="run-create",
            run_id=run_id,
            row_id=None,
            summary=f"Run '{run.name}' angelegt ({len(rows)} Orte)",
            after={"id": run_id, "name": run.name, "game_id": run.game_id},
        )
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
    author: str | None = Depends(author_from_header),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    updates = changes.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Mindestens ein Feld muss angegeben werden.")
    make_current = updates.pop("make_current", None)

    with mutate(if_match) as state:
        run = find_run(state, run_id)
        if make_current:
            state["current_run_id"] = run_id
        if updates.get("status") == "completed" and run["status"] != "completed":
            run["completed_at"] = now_iso()
        elif updates.get("status") == "active":
            run["completed_at"] = None
        run.update(updates)
        record_history(
            state,
            author=author,
            action="run-patch",
            run_id=run_id,
            row_id=None,
            summary=f"Run '{run['name']}' geändert: {', '.join(sorted(updates)) or 'aktiv gesetzt'}",
            after=updates,
        )
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
    author: str | None = Depends(author_from_header),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    with mutate(if_match) as state:
        run = find_run(state, run_id)
        return add_row(state, run, row, force=force, author=author)


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
    author: str | None = Depends(author_from_header),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    with mutate(if_match) as state:
        run = find_run(state, run_id)
        return patch_row(state, run, row_id, changes, couple=couple, force=force, author=author)


@app.delete(
    "/runs/{run_id}/encounters/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_write_token)],
    summary="Zeile eines Runs löschen",
)
def delete_run_encounter(
    run_id: str,
    row_id: str,
    author: str | None = Depends(author_from_header),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> Response:
    with mutate(if_match) as state:
        run = find_run(state, run_id)
        remove_row(state, run, row_id, author=author)
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
    author: str | None = Depends(author_from_header),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    with mutate(if_match) as state:
        return add_row(state, current_run(state), row, force=force, author=author)


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
    author: str | None = Depends(author_from_header),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    with mutate(if_match) as state:
        return patch_row(state, current_run(state), row_id, changes, couple=couple, force=force, author=author)


@app.delete(
    "/encounters/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_write_token)],
    summary="Zeile im aktuellen Run löschen",
)
def delete_encounter(
    row_id: str,
    author: str | None = Depends(author_from_header),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> Response:
    with mutate(if_match) as state:
        remove_row(state, current_run(state), row_id, author=author)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/history/{entry_id}/undo",
    response_model=HistoryEntry,
    dependencies=[Depends(require_write_token)],
    summary="Eine Änderung zurücknehmen",
)
def undo_history_entry(
    entry_id: str,
    author: str | None = Depends(author_from_header),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    with mutate(if_match) as state:
        entry = next((item for item in state["history"] if item["id"] == entry_id), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Historieneintrag '{entry_id}' nicht gefunden.")
        if entry["undone"]:
            raise HTTPException(status_code=409, detail="Dieser Eintrag wurde bereits zurückgenommen.")
        if entry["action"] not in ("row-create", "row-patch", "row-delete"):
            raise HTTPException(status_code=422, detail=f"'{entry['action']}' lässt sich nicht zurücknehmen.")

        run = find_run(state, entry["run_id"])
        row_id = entry["row_id"]
        if entry["action"] == "row-create":
            run["encounters"] = [row for row in run["encounters"] if row["id"] != row_id]
        elif entry["action"] == "row-delete":
            restored = EncounterRow.model_validate(entry["before"]).model_dump()
            run["encounters"].append(restored)
            run["encounters"].sort(key=lambda row: (row["order"], row["id"]))
        else:
            replace_row(run, EncounterRow.model_validate(entry["before"]).model_dump())

        entry["undone"] = True
        record_history(
            state,
            author=author,
            action="undo",
            run_id=entry["run_id"],
            row_id=row_id,
            summary=f"Zurückgenommen: {entry['summary']}",
        )
        return {key: entry.get(key) for key in ("id", "at", "author", "action", "run_id", "row_id", "summary", "undone")}


# --------------------------------------------------------------------------- #
# Gemeinsame Schreiblogik
# --------------------------------------------------------------------------- #


def add_row(
    state: dict[str, Any],
    run: dict[str, Any],
    row: EncounterRow,
    *,
    force: bool,
    author: str | None,
) -> dict[str, Any]:
    if any(existing["id"] == row.id for existing in run["encounters"]):
        raise HTTPException(status_code=409, detail=f"Encounter '{row.id}' existiert in Run '{run['id']}' bereits.")

    record = row.model_dump()
    for player_id in player_ids_of(state):
        record["picks"].setdefault(player_id, Pick().model_dump())
    validate_species(run, record, record["picks"], force)
    record["outcome"] = row.outcome if "outcome" in row.model_fields_set else derive_outcome(record["picks"])
    couple_deaths(record, record.get("responsible_player"))

    run["encounters"].append(record)
    record_history(
        state,
        author=author,
        action="row-create",
        run_id=run["id"],
        row_id=record["id"],
        summary=f"'{record['encounter']}' angelegt",
        after=record,
    )
    return record


def patch_row(
    state: dict[str, Any],
    run: dict[str, Any],
    row_id: str,
    changes: EncounterPatch,
    *,
    couple: bool,
    force: bool,
    author: str | None,
) -> dict[str, Any]:
    updated, before = apply_encounter_patch(
        run, row_id, changes, couple=couple, force=force, player_ids=player_ids_of(state)
    )
    replace_row(run, updated)
    record_history(
        state,
        author=author,
        action="row-patch",
        run_id=run["id"],
        row_id=row_id,
        summary=describe_patch(before, updated, state["players"]),
        before=before,
        after=updated,
    )
    return updated


def remove_row(state: dict[str, Any], run: dict[str, Any], row_id: str, *, author: str | None) -> None:
    row = find_row(run, row_id)
    before = json.loads(json.dumps(row))
    run["encounters"] = [entry for entry in run["encounters"] if entry["id"] != row_id]
    record_history(
        state,
        author=author,
        action="row-delete",
        run_id=run["id"],
        row_id=row_id,
        summary=f"'{row['encounter']}' gelöscht",
        before=before,
    )


def describe_patch(before: dict[str, Any], after: dict[str, Any], players: list[dict[str, Any]]) -> str:
    """Kurzer, lesbarer Text fuer die Historie."""
    names = {player["id"]: player["name"] for player in players}
    parts: list[str] = []
    for player_id, pick in after["picks"].items():
        old = before["picks"].get(player_id, {})
        label = names.get(player_id, player_id)
        if pick.get("name") != old.get("name"):
            parts.append(f"{label}: {old.get('name') or '–'} → {pick.get('name') or '–'}")
        elif pick.get("status") != old.get("status"):
            parts.append(f"{label}: {pick['status']}")
    if after["outcome"] != before["outcome"]:
        parts.append(f"Status {before['outcome']} → {after['outcome']}")
    if after.get("note") != before.get("note"):
        parts.append("Notiz geändert")
    return f"'{after['encounter']}': " + ("; ".join(parts) if parts else "aktualisiert")


# --------------------------------------------------------------------------- #
# Statistik
# --------------------------------------------------------------------------- #


@app.get("/stats", summary="Statistik über alle Runs oder einen Run")
def get_stats(
    run_id: str | None = Query(default=None),
    game_id: str | None = Query(default=None),
) -> dict[str, Any]:
    state = load_state()
    runs = state["runs"]
    if run_id is not None:
        runs = [find_run(state, run_id)]
    if game_id is not None:
        runs = [run for run in runs if run["game_id"] == game_id]

    player_ids = player_ids_of(state)
    responsibility = {player_id: 0 for player_id in player_ids}
    dead_pokemon = {player_id: 0 for player_id in player_ids}
    caught_pokemon = {player_id: 0 for player_id in player_ids}
    failed_encounters = {player_id: 0 for player_id in player_ids}
    totals = {"encounter_count": 0, "pending_count": 0, "caught_count": 0, "failed_count": 0, "death_count": 0}
    per_run = []

    for run in runs:
        counts = row_counts(run["encounters"])
        per_run.append(
            {
                "id": run["id"],
                "name": run["name"],
                "game_id": run["game_id"],
                "game_name": game_name_of(run["game_id"]),
                "status": run["status"],
                **counts,
            }
        )
        for key in totals:
            totals[key] += counts[key]

        for row in run["encounters"]:
            responsible = row.get("responsible_player")
            if responsible in responsibility:
                responsibility[responsible] += 1
                if row["outcome"] == "failed":
                    failed_encounters[responsible] += 1
            for player_id in player_ids:
                pick = row["picks"].get(player_id) or {}
                if pick.get("status") == "dead":
                    dead_pokemon[player_id] += 1
                elif row["outcome"] == "caught" and pick_is_filled(pick) and not is_placeholder(pick.get("name")):
                    caught_pokemon[player_id] += 1

    return {
        "scope": run_id or game_id or "all-time",
        "players": state["players"],
        "total_runs": len(runs),
        "total_encounter_rows": totals["encounter_count"],
        "total_pending_rows": totals["pending_count"],
        "total_caught_rows": totals["caught_count"],
        "total_failed_rows": totals["failed_count"],
        "total_death_rows": totals["death_count"],
        "responsibility_by_player": responsibility,
        "dead_pokemon_by_player": dead_pokemon,
        "caught_pokemon_by_player": caught_pokemon,
        "failed_encounters_by_player": failed_encounters,
        "runs": per_run,
        "updated_at": state["updated_at"],
    }
