from __future__ import annotations

import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

PLAYERS = ["Mark", "Nikolai", "KNEV"]
Outcome = Literal["caught", "dead", "failed"]
RunStatus = Literal["active", "completed"]
PLAYER_FIELDS = {"Mark": "mark", "Nikolai": "nikolai", "KNEV": "knev"}
STATUS_FIELDS = {"Mark": "mark_status", "Nikolai": "nikolai_status", "KNEV": "knev_status"}
PLACEHOLDER_PREFIXES = ("Encounter verloren", "Kein Encounter")

DEFAULT_ROWS = [
    {
        "id": "route-201-starter",
        "encounter": "Route 201 (Starter)",
        "mark": "Panflam",
        "nikolai": "Chelast",
        "knev": "Panflam",
    },
    {
        "id": "route-202",
        "encounter": "Route 202",
        "mark": "Bidiza",
        "nikolai": "Bidiza",
        "knev": "Staralili",
    },
    {
        "id": "route-203",
        "encounter": "Route 203",
        "mark": "Abra",
        "nikolai": "Sheinux",
        "knev": "Zubat",
    },
    {
        "id": "lake-verity",
        "encounter": "Lake Verity",
        "mark": "Staralili",
        "nikolai": "Staralili",
        "knev": "Bidiza",
    },
    {
        "id": "route-204",
        "encounter": "Route 204",
        "mark": "Wadribie",
        "nikolai": "Knospi",
        "knev": "Knospi",
    },
    {
        "id": "ravaged-path",
        "encounter": "Ravaged Path",
        "mark": "Zubat",
        "nikolai": "Zubat",
        "knev": "Enton",
    },
    {
        "id": "erzelinger-tunnel-oreburgh-gate",
        "encounter": "Erzelinger Tunnel (Oreburgh Gate)",
        "mark": "Enton",
        "nikolai": "Kleinstein",
        "knev": "Kleinstein",
    },
    {
        "id": "route-207",
        "encounter": "Route 207",
        "mark": "Kein Encounter – Ponita von Mark besiegt",
        "nikolai": "Kein Encounter – Ponita von Mark besiegt",
        "knev": "Kein Encounter – Ponita von Mark besiegt",
    },
]

app = FastAPI(
    title="Pokémon Encounter API",
    version="2.0.0",
    description="Read and update shared encounter tables across multiple Nuzlocke runs.",
    root_path="/encounter-table/api",
)
security = HTTPBearer(auto_error=False)
write_lock = threading.Lock()


class EncounterRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=80)
    encounter: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    responsible_player: str | None = Field(default=None, max_length=80)
    mark: str = Field(max_length=300)
    nikolai: str = Field(max_length=300)
    knev: str = Field(max_length=300)
    mark_status: Literal["alive", "dead"] = "alive"
    nikolai_status: Literal["alive", "dead"] = "alive"
    knev_status: Literal["alive", "dead"] = "alive"
    outcome: Outcome = "caught"


class EncounterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encounter: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    responsible_player: str | None = Field(default=None, max_length=80)
    mark: str | None = Field(default=None, max_length=300)
    nikolai: str | None = Field(default=None, max_length=300)
    knev: str | None = Field(default=None, max_length=300)
    mark_status: Literal["alive", "dead"] | None = None
    nikolai_status: Literal["alive", "dead"] | None = None
    knev_status: Literal["alive", "dead"] | None = None
    outcome: Outcome | None = None


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    game: str | None = Field(default=None, max_length=120)
    status: RunStatus = "active"
    created_at: str
    completed_at: str | None = None
    encounters: list[EncounterRow] = Field(default_factory=list)


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    game: str | None = Field(default=None, max_length=120)
    make_current: bool = True


class RunPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    game: str | None = Field(default=None, max_length=120)
    status: RunStatus | None = None
    make_current: bool | None = None


class EncounterCollection(BaseModel):
    players: list[str]
    run_id: str
    run_name: str
    game: str | None
    encounters: list[EncounterRow]
    updated_at: str


class RunSummary(BaseModel):
    id: str
    name: str
    game: str | None
    status: RunStatus
    created_at: str
    completed_at: str | None
    encounter_count: int
    caught_count: int
    failed_count: int
    death_count: int


class RunsCollection(BaseModel):
    players: list[str]
    current_run_id: str
    runs: list[RunSummary]
    updated_at: str


def data_path() -> Path:
    return Path(os.environ.get("ENCOUNTER_DATA_PATH", "/var/lib/encounter-table-api/encounters.json"))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def infer_outcome(row: dict[str, Any]) -> Outcome:
    if any(str(row.get(field, "")).startswith(PLACEHOLDER_PREFIXES) for field in PLAYER_FIELDS.values()):
        return "failed"
    if any(row.get(field) == "dead" for field in STATUS_FIELDS.values()):
        return "dead"
    return "caught"


def normalize_encounter(raw: dict[str, Any]) -> dict[str, Any]:
    row = dict(raw)
    row.setdefault("note", None)
    row.setdefault("responsible_player", None)
    for field in STATUS_FIELDS.values():
        row.setdefault(field, "alive")
    row.setdefault("outcome", infer_outcome(row))
    return EncounterRow.model_validate(row).model_dump()


def normalize_run(raw: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    run = dict(raw)
    run.setdefault("id", fallback_id)
    run.setdefault("name", f"Run {fallback_id.removeprefix('run-')}")
    run.setdefault("game", None)
    run.setdefault("status", "active")
    run.setdefault("created_at", now_iso())
    run.setdefault("completed_at", None)
    run["encounters"] = [normalize_encounter(row) for row in run.get("encounters", [])]
    return RunRecord.model_validate(run).model_dump()


def initial_state() -> dict[str, Any]:
    rows = [normalize_encounter(row) for row in DEFAULT_ROWS]
    return {
        "players": PLAYERS,
        "current_run_id": "run-1",
        "runs": [
            {
                "id": "run-1",
                "name": "Run 1",
                "game": None,
                "status": "active",
                "created_at": now_iso(),
                "completed_at": None,
                "encounters": rows,
            }
        ],
        "updated_at": now_iso(),
    }


def save_state(state: dict[str, Any]) -> None:
    target = data_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def normalize_state(raw: dict[str, Any]) -> dict[str, Any]:
    if "runs" not in raw:
        legacy_rows = [normalize_encounter(row) for row in raw.get("encounters", [])]
        created_at = raw.get("updated_at") or now_iso()
        raw = {
            "players": PLAYERS,
            "current_run_id": "run-1",
            "runs": [
                {
                    "id": "run-1",
                    "name": "Run 1",
                    "game": None,
                    "status": "active",
                    "created_at": created_at,
                    "completed_at": None,
                    "encounters": legacy_rows,
                }
            ],
            "updated_at": raw.get("updated_at") or now_iso(),
        }
    runs = [normalize_run(run, f"run-{index}") for index, run in enumerate(raw.get("runs", []), start=1)]
    if not runs:
        return initial_state()
    current_run_id = raw.get("current_run_id") or runs[0]["id"]
    if not any(run["id"] == current_run_id for run in runs):
        current_run_id = runs[0]["id"]
    state = {
        "players": PLAYERS,
        "current_run_id": current_run_id,
        "runs": runs,
        "updated_at": raw.get("updated_at") or now_iso(),
    }
    return state


def load_state() -> dict[str, Any]:
    target = data_path()
    if not target.exists():
        state = initial_state()
        save_state(state)
        return state
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        state = normalize_state(raw)
        if state != raw:
            save_state(state)
        return state
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise RuntimeError(f"Encounter data is invalid: {target}") from exc


def require_write_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    configured_token = os.environ.get("ENCOUNTER_API_TOKEN", "")
    supplied_token = credentials.credentials if credentials else ""
    if not configured_token or not secrets.compare_digest(supplied_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid Bearer token is required for write operations.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def find_run(runs: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    for run in runs:
        if run["id"] == run_id:
            return run
    raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")


def current_run(state: dict[str, Any]) -> dict[str, Any]:
    return find_run(state["runs"], state["current_run_id"])


def find_row(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any]:
    for row in rows:
        if row["id"] == row_id:
            return row
    raise HTTPException(status_code=404, detail=f"Encounter '{row_id}' not found.")


def collection_for(run: dict[str, Any], updated_at: str) -> dict[str, Any]:
    return {
        "players": PLAYERS,
        "run_id": run["id"],
        "run_name": run["name"],
        "game": run["game"],
        "encounters": run["encounters"],
        "updated_at": updated_at,
    }


def row_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "encounter_count": len(rows),
        "caught_count": sum(row["outcome"] == "caught" for row in rows),
        "failed_count": sum(row["outcome"] == "failed" for row in rows),
        "death_count": sum(row["outcome"] == "dead" or any(row[field] == "dead" for field in STATUS_FIELDS.values()) for row in rows),
    }


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {key: run[key] for key in ("id", "name", "game", "status", "created_at", "completed_at")} | row_counts(run["encounters"])


def slugify_run_id(name: str, existing_ids: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "run"
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def add_encounter_to_run(state: dict[str, Any], run: dict[str, Any], row: EncounterRow) -> dict[str, Any]:
    if any(existing["id"] == row.id for existing in run["encounters"]):
        raise HTTPException(status_code=409, detail=f"Encounter '{row.id}' already exists in run '{run['id']}'.")
    record = row.model_dump()
    run["encounters"].append(record)
    state["updated_at"] = now_iso()
    save_state(state)
    return record


def apply_encounter_patch(run: dict[str, Any], row_id: str, changes: EncounterPatch) -> dict[str, Any]:
    updates = changes.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="At least one field must be provided.")
    existing = find_row(run["encounters"], row_id)
    existing.update(updates)
    if "outcome" not in updates:
        if any(existing[field] == "dead" for field in STATUS_FIELDS.values()):
            existing["outcome"] = "dead"
        elif any(str(existing.get(field, "")).startswith(PLACEHOLDER_PREFIXES) for field in PLAYER_FIELDS.values()):
            existing["outcome"] = "failed"
    return existing


@app.get("/", summary="API overview")
def api_overview() -> dict[str, Any]:
    return {
        "name": "Pokémon Encounter API",
        "read": "GET /encounters, GET /runs, GET /stats",
        "write": "Bearer token required for POST, PUT, PATCH and DELETE",
        "openapi": "/openapi.json",
    }


@app.get("/encounters", response_model=EncounterCollection, summary="Read the current run")
def get_encounters() -> dict[str, Any]:
    state = load_state()
    return collection_for(current_run(state), state["updated_at"])


@app.get("/encounters/{row_id}", response_model=EncounterRow, summary="Read one current-run row")
def get_encounter(row_id: str) -> dict[str, Any]:
    return find_row(current_run(load_state())["encounters"], row_id)


@app.get("/runs", response_model=RunsCollection, summary="List all runs")
def get_runs() -> dict[str, Any]:
    state = load_state()
    return {
        "players": PLAYERS,
        "current_run_id": state["current_run_id"],
        "runs": [run_summary(run) for run in state["runs"]],
        "updated_at": state["updated_at"],
    }


@app.get("/runs/{run_id}", response_model=RunRecord, summary="Read one run")
def get_run(run_id: str) -> dict[str, Any]:
    return find_run(load_state()["runs"], run_id)


@app.get("/runs/{run_id}/encounters", response_model=EncounterCollection, summary="Read one run's encounters")
def get_run_encounters(run_id: str) -> dict[str, Any]:
    state = load_state()
    return collection_for(find_run(state["runs"], run_id), state["updated_at"])


@app.post(
    "/runs",
    response_model=RunRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_token)],
    summary="Create a run",
)
def create_run(run: RunCreate) -> dict[str, Any]:
    with write_lock:
        state = load_state()
        existing_ids = {entry["id"] for entry in state["runs"]}
        run_id = run.id or slugify_run_id(run.name, existing_ids)
        if run_id in existing_ids:
            raise HTTPException(status_code=409, detail=f"Run '{run_id}' already exists.")
        created = RunRecord(
            id=run_id,
            name=run.name,
            game=run.game,
            created_at=now_iso(),
            encounters=[],
        ).model_dump()
        state["runs"].append(created)
        if run.make_current:
            state["current_run_id"] = run_id
        state["updated_at"] = now_iso()
        save_state(state)
        return created


@app.patch(
    "/runs/{run_id}",
    response_model=RunRecord,
    dependencies=[Depends(require_write_token)],
    summary="Update run metadata",
)
def patch_run(run_id: str, changes: RunPatch) -> dict[str, Any]:
    updates = changes.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="At least one field must be provided.")
    make_current = updates.pop("make_current", None)
    with write_lock:
        state = load_state()
        run = find_run(state["runs"], run_id)
        if make_current:
            state["current_run_id"] = run_id
        if updates.get("status") == "completed" and run["status"] != "completed":
            run["completed_at"] = now_iso()
        elif updates.get("status") == "active":
            run["completed_at"] = None
        run.update(updates)
        state["updated_at"] = now_iso()
        save_state(state)
        return run


@app.post(
    "/runs/{run_id}/encounters",
    response_model=EncounterRow,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_token)],
    summary="Add an encounter to a run",
)
def create_run_encounter(run_id: str, row: EncounterRow) -> dict[str, Any]:
    with write_lock:
        state = load_state()
        return add_encounter_to_run(state, find_run(state["runs"], run_id), row)


@app.patch(
    "/runs/{run_id}/encounters/{row_id}",
    response_model=EncounterRow,
    dependencies=[Depends(require_write_token)],
    summary="Update an encounter in a run",
)
def patch_run_encounter(run_id: str, row_id: str, changes: EncounterPatch) -> dict[str, Any]:
    with write_lock:
        state = load_state()
        run = find_run(state["runs"], run_id)
        updated = apply_encounter_patch(run, row_id, changes)
        state["updated_at"] = now_iso()
        save_state(state)
        return updated


@app.delete(
    "/runs/{run_id}/encounters/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_write_token)],
    summary="Delete an encounter from a run",
)
def delete_run_encounter(run_id: str, row_id: str) -> Response:
    with write_lock:
        state = load_state()
        run = find_run(state["runs"], run_id)
        find_row(run["encounters"], row_id)
        run["encounters"] = [row for row in run["encounters"] if row["id"] != row_id]
        state["updated_at"] = now_iso()
        save_state(state)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/stats", summary="Read all-time or one-run statistics")
def get_stats(run_id: str | None = Query(default=None)) -> dict[str, Any]:
    state = load_state()
    runs = state["runs"] if run_id is None else [find_run(state["runs"], run_id)]
    responsibility = {player: 0 for player in PLAYERS}
    dead_pokemon = {player: 0 for player in PLAYERS}
    caught_pokemon = {player: 0 for player in PLAYERS}
    failed_encounters = {player: 0 for player in PLAYERS}
    total_rows = total_caught = total_failed = total_deaths = 0
    per_run = []

    for run in runs:
        counts = row_counts(run["encounters"])
        per_run.append({
            "id": run["id"],
            "name": run["name"],
            "game": run["game"],
            "status": run["status"],
            **counts,
        })
        total_rows += counts["encounter_count"]
        total_caught += counts["caught_count"]
        total_failed += counts["failed_count"]
        total_deaths += counts["death_count"]
        for row in run["encounters"]:
            responsible = row.get("responsible_player")
            if responsible in responsibility:
                responsibility[responsible] += 1
            if row["outcome"] == "failed" and responsible in failed_encounters:
                failed_encounters[responsible] += 1
            for player in PLAYERS:
                if row[STATUS_FIELDS[player]] == "dead":
                    dead_pokemon[player] += 1
                elif row["outcome"] == "caught" and not str(row[PLAYER_FIELDS[player]]).startswith(PLACEHOLDER_PREFIXES):
                    caught_pokemon[player] += 1

    return {
        "scope": "all-time" if run_id is None else run_id,
        "total_runs": len(runs),
        "total_encounter_rows": total_rows,
        "total_caught_rows": total_caught,
        "total_failed_rows": total_failed,
        "total_death_rows": total_deaths,
        "responsibility_by_player": responsibility,
        "dead_pokemon_by_player": dead_pokemon,
        "caught_pokemon_by_player": caught_pokemon,
        "failed_encounters_by_player": failed_encounters,
        "runs": per_run,
        "updated_at": state["updated_at"],
    }


@app.post(
    "/encounters",
    response_model=EncounterRow,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_token)],
    summary="Add a row to the current run",
)
def create_encounter(row: EncounterRow) -> dict[str, Any]:
    with write_lock:
        state = load_state()
        return add_encounter_to_run(state, current_run(state), row)


@app.put(
    "/encounters/{row_id}",
    response_model=EncounterRow,
    dependencies=[Depends(require_write_token)],
    summary="Replace one current-run row",
)
def replace_encounter(row_id: str, row: EncounterRow) -> dict[str, Any]:
    if row.id != row_id:
        raise HTTPException(status_code=422, detail="The body id must match the URL id.")
    with write_lock:
        state = load_state()
        existing = find_row(current_run(state)["encounters"], row_id)
        existing.update(row.model_dump())
        state["updated_at"] = now_iso()
        save_state(state)
        return existing


@app.patch(
    "/encounters/{row_id}",
    response_model=EncounterRow,
    dependencies=[Depends(require_write_token)],
    summary="Change selected fields in one current-run row",
)
def patch_encounter(row_id: str, changes: EncounterPatch) -> dict[str, Any]:
    with write_lock:
        state = load_state()
        run = current_run(state)
        updated = apply_encounter_patch(run, row_id, changes)
        state["updated_at"] = now_iso()
        save_state(state)
        return updated


@app.delete(
    "/encounters/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_write_token)],
    summary="Delete one current-run row",
)
def delete_encounter(row_id: str) -> Response:
    with write_lock:
        state = load_state()
        run = current_run(state)
        find_row(run["encounters"], row_id)
        run["encounters"] = [row for row in run["encounters"] if row["id"] != row_id]
        state["updated_at"] = now_iso()
        save_state(state)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
