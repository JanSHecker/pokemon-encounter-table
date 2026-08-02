import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module

# Mini-Katalog statt des echten Platin-Katalogs: die ID muss 'platinum' sein,
# weil Alt-Daten ohne Spielangabe genau darauf migriert werden.
CATALOG = {
    "id": "platinum",
    "name": "Testplatin",
    "versions": ["platinum"],
    "locations": [
        {
            "id": "sinnoh-route-201",
            "order": 1,
            "name": "Route 201",
            "encounters": [
                {"species": "starly", "name": "Staralili", "dex": 396, "methods": ["Grasland"]},
                {"species": "bidoof", "name": "Bidiza", "dex": 399, "methods": ["Grasland"]},
            ],
        },
        {
            "id": "sinnoh-route-202",
            "order": 2,
            "name": "Route 202",
            "encounters": [{"species": "shinx", "name": "Sheinux", "dex": 403, "methods": ["Grasland"]}],
        },
        {
            "id": "sinnoh-victory-road",
            "order": 3,
            "name": "Siegesstraße",
            "postgame": True,
            "encounters": [{"species": "zubat", "name": "Zubat", "dex": 41, "methods": ["Grasland"]}],
        },
    ],
    "level_caps": [{"order": 1, "kind": "gym", "leader": "Veit", "place": "Erzelingen", "cap": 14}],
}

# Datenstand im alten Schema: drei feste Spielerfelder, alte Namen, kein Spiel.
LEGACY_STATE = {
    "players": ["Mark", "Nikolai", "KNEV"],
    "current_run_id": "run-1",
    "runs": [
        {
            "id": "run-1",
            "name": "Run 1",
            "game": None,
            "status": "active",
            "created_at": "2026-01-01T00:00:00+00:00",
            "completed_at": None,
            "encounters": [
                {
                    "id": "route-201",
                    "encounter": "Route 201",
                    "note": "Bidiza war knapp - Altlast aus v3",
                    "responsible_player": "Mark",
                    "mark": "Staralili",
                    "nikolai": "Bidiza",
                    "knev": "Staralili",
                    "mark_status": "alive",
                    "nikolai_status": "alive",
                    "knev_status": "alive",
                    "outcome": "caught",
                },
                {
                    "id": "route-202",
                    "encounter": "Route 202",
                    "note": None,
                    "responsible_player": "Nikolai",
                    "mark": "Encounter verloren",
                    "nikolai": "Encounter verloren",
                    "knev": "Encounter verloren",
                    "mark_status": "alive",
                    "nikolai_status": "alive",
                    "knev_status": "alive",
                    "outcome": "failed",
                },
            ],
        }
    ],
    "updated_at": "2026-01-01T00:00:00+00:00",
}


@pytest.fixture
def data_file(tmp_path, monkeypatch):
    """Frischer Datenpfad plus Mini-Katalog fuer jeden Test."""
    games_dir = tmp_path / "games"
    games_dir.mkdir()
    (games_dir / "platinum.json").write_text(json.dumps(CATALOG, ensure_ascii=False), encoding="utf-8")

    target = tmp_path / "encounters.json"
    monkeypatch.setenv("ENCOUNTER_GAMES_PATH", str(games_dir))
    monkeypatch.setenv("ENCOUNTER_DATA_PATH", str(target))
    monkeypatch.delenv("ENCOUNTER_API_TOKEN", raising=False)
    app_module.reset_catalog_cache()
    yield target
    app_module.reset_catalog_cache()


@pytest.fixture
def client(data_file):
    return TestClient(app_module.app)


@pytest.fixture
def legacy_client(data_file):
    data_file.write_text(json.dumps(LEGACY_STATE, ensure_ascii=False), encoding="utf-8")
    return TestClient(app_module.app)


def test_writes_do_not_require_a_bearer_token(client, monkeypatch):
    monkeypatch.setenv("ENCOUNTER_API_TOKEN", "test-secret")
    payload = {"name": "Öffener Run", "game_id": "platinum"}

    assert client.post("/runs", json=payload).status_code == 201


# --------------------------------------------------------------- Katalog ---


def test_games_endpoint_lists_the_catalog(client):
    response = client.get("/games")

    assert response.status_code == 200
    assert response.json() == [{"id": "platinum", "name": "Testplatin", "location_count": 3}]


def test_unknown_game_is_reported(client):
    assert client.get("/games/smaragd").status_code == 404


def test_platinum_catalog_includes_cities_with_encounters():
    catalog_path = Path(__file__).resolve().parent.parent / "data" / "games" / "platinum.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    locations = {location["id"]: location for location in catalog["locations"]}
    expected_cities = {
        "twinleaf-town",
        "oreburgh-city",
        "eterna-city",
        "hearthome-city",
        "veilstone-city",
        "pastoria-city",
        "celestic-town",
        "canalave-city",
        "sunyshore-city",
    }

    assert expected_cities <= locations.keys()
    assert all(locations[location_id]["encounters"] for location_id in expected_cities)
    assert locations["ravaged-path"]["name"] == "Verwüsteter Pfad"


def test_the_pokedex_carries_types_for_every_species():
    """Ohne Typen bleiben Typ-Badges und Typenrechner im Frontend leer."""
    catalog_path = Path(__file__).resolve().parent.parent / "data" / "games" / "platinum.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert all(1 <= len(entry["types"]) <= 2 for entry in catalog["pokedex"])
    # Die Typen sind die heutigen, nicht die der Edition - Piepi ist auch in Platin eine Fee.
    assert next(entry for entry in catalog["pokedex"] if entry["species"] == "clefairy")["types"] == ["fairy"]


def test_every_level_cap_names_its_battle_type():
    """Leer ist erlaubt (gemischt), fehlen darf das Feld nicht: es faerbt die Cap-Karte."""
    games_dir = Path(__file__).resolve().parent.parent / "data" / "games"
    for path in games_dir.glob("*.json"):
        catalog = json.loads(path.read_text(encoding="utf-8"))
        assert all("type" in cap for cap in catalog["level_caps"]), path.name


def test_empty_store_starts_prefilled_with_every_catalog_location(client):
    payload = client.get("/encounters").json()

    assert [row["id"] for row in payload["encounters"]] == [
        "sinnoh-route-201",
        "sinnoh-route-202",
        "sinnoh-victory-road",
    ]
    assert all(row["outcome"] == "pending" for row in payload["encounters"])
    assert payload["game_name"] == "Testplatin"


# ------------------------------------------------------------- Migration ---


def test_legacy_state_migrates_to_players_and_picks(legacy_client):
    payload = legacy_client.get("/encounters").json()

    # Die Farbe kommt aus der Palette, in der Reihenfolge der Spieler.
    assert payload["players"] == [
        {"id": "marc", "name": "Marc", "color": "#3f6fb5"},
        {"id": "nicolai", "name": "Nicolai", "color": "#3f8a52"},
        {"id": "knev", "name": "Knev", "color": "#c07a2c"},
    ]

    first = payload["encounters"][0]
    assert first["location_id"] == "sinnoh-route-201"
    assert first["responsible_player"] == "marc"
    assert first["picks"]["marc"] == {"species": "starly", "name": "Staralili", "status": "alive"}
    # Der Species-Slug wird ueber den deutschen Namen aus dem Katalog zurueckgewonnen.
    assert first["picks"]["nicolai"]["species"] == "bidoof"


def test_legacy_lost_encounter_keeps_its_outcome(legacy_client):
    rows = legacy_client.get("/encounters").json()["encounters"]
    lost = next(row for row in rows if row["id"] == "route-202")

    assert lost["outcome"] == "failed"
    assert lost["picks"]["knev"]["name"] == "Encounter verloren"
    assert lost["picks"]["knev"]["species"] is None


def test_player_names_are_normalized_to_configured_spelling(client, data_file):
    client.get("/encounters")  # legt den Store ueberhaupt erst an
    stored = json.loads(data_file.read_text(encoding="utf-8"))
    stored["players"] = [
        {"id": "marc", "name": "Marc"},
        {"id": "nicolai", "name": "Nicolai"},
        {"id": "knev", "name": "Knev"},
    ]
    data_file.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")

    names = [player["name"] for player in client.get("/runs").json()["players"]]

    assert names == ["Marc", "Nicolai", "Knev"]


def test_migration_is_written_back_once(legacy_client, data_file):
    legacy_client.get("/encounters")
    stored = json.loads(data_file.read_text(encoding="utf-8"))

    assert stored["schema_version"] == 6
    assert "mark" not in stored["runs"][0]["encounters"][0]


def test_the_note_field_is_removed_from_stored_rows(legacy_client, data_file):
    # v4 kennt kein Notizfeld mehr. Es genuegt nicht, es zu ignorieren: EncounterRow
    # verbietet unbekannte Felder, ein stehengebliebenes 'note' wuerde das Laden
    # jedes Endpoints mit 500 beantworten.
    legacy_client.get("/encounters")
    stored = json.loads(data_file.read_text(encoding="utf-8"))

    assert all("note" not in row for row in stored["runs"][0]["encounters"])
    assert "note" not in legacy_client.get("/encounters").json()["encounters"][0]


def test_a_note_can_no_longer_be_written(client):
    response = client.patch("/encounters/sinnoh-route-201", json={"note": "doch nicht"})

    assert response.status_code == 422


def stored_state(data_file, rows):
    """Ein v4-Stand mit genau diesen Zeilen - Ausgangspunkt der v5-Migration."""
    state = {
        "schema_version": 4,
        "players": [
            {"id": "marc", "name": "Marc"},
            {"id": "nicolai", "name": "Nicolai"},
            {"id": "knev", "name": "Knev"},
        ],
        "current_run_id": "run-1",
        "runs": [
            {
                "id": "run-1",
                "name": "Run 1",
                "game_id": "platinum",
                "status": "active",
                "created_at": "2026-01-01T00:00:00+00:00",
                "completed_at": None,
                "progress": 0,
                "encounters": rows,
            }
        ],
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    data_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return TestClient(app_module.app)


def starter_row(**overrides):
    row = {
        "id": "starter",
        "location_id": "starter",
        "order": 1,
        "encounter": "Starter",
        "responsible_player": None,
        "outcome": "caught",
        "postgame": False,
        "in_team": True,
        "picks": {
            "marc": {"species": "starly", "name": "Staralili", "status": "alive"},
            "nicolai": {"species": "bidoof", "name": "Bidiza", "status": "alive"},
            "knev": {"species": "starly", "name": "Staralili", "status": "alive"},
        },
    }
    return row | overrides


def test_the_starter_row_moves_onto_its_location(data_file):
    # v5 kennt keinen eigenen Starter-Ort mehr - die Starter sind der Encounter
    # des Ortes, an dem man sie bekommt.
    client = stored_state(data_file, [starter_row()])

    rows = client.get("/encounters").json()["encounters"]
    route_201 = next(row for row in rows if row["id"] == "sinnoh-route-201")

    assert route_201["location_id"] == "sinnoh-route-201"
    assert route_201["encounter"] == "Route 201"
    assert route_201["picks"]["marc"]["name"] == "Staralili"
    assert route_201["in_team"] is True


def test_existing_runs_are_backfilled_with_every_catalog_location(data_file):
    # Ein älterer Run darf neue Orte nicht verlieren: fehlende Katalogzeilen
    # werden als offene Encounter ergänzt, inklusive postgame.
    client = stored_state(data_file, [starter_row()])

    rows = client.get("/encounters").json()["encounters"]

    assert [row["id"] for row in rows] == [
        "sinnoh-route-201",
        "sinnoh-route-202",
        "sinnoh-victory-road",
    ]
    assert rows[1]["outcome"] == "pending"
    assert rows[2]["postgame"] is True
    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert len(stored["runs"][0]["encounters"]) == 3


def test_the_starter_row_wins_against_an_empty_location_row(data_file):
    # Wer den Ort schon in der Tabelle stehen hatte, haette sonst zwei Zeilen -
    # und beim Zusammenlegen koennte die leere gewinnen.
    empty = {
        "id": "sinnoh-route-201",
        "location_id": "sinnoh-route-201",
        "order": 2,
        "encounter": "Route 201",
        "responsible_player": None,
        "outcome": "pending",
        "postgame": False,
        "in_team": False,
        "picks": {player: {"species": None, "name": "", "status": "alive"} for player in ("marc", "nicolai", "knev")},
    }
    client = stored_state(data_file, [starter_row(), empty])

    rows = client.get("/encounters").json()["encounters"]

    route_201 = next(row for row in rows if row["id"] == "sinnoh-route-201")
    assert len(rows) == 3
    assert route_201["picks"]["nicolai"] == {"species": "bidoof", "name": "Bidiza", "status": "alive"}
    assert route_201["outcome"] == "caught"


def test_order_follows_the_catalog_after_a_location_is_retired(data_file):
    # Faellt ein Ort weg, ruecken alle nachfolgenden auf. Bleiben Alt-Zeilen auf
    # ihrer alten Nummer, mischen sie sich falsch unter spaeter angelegte.
    later = {
        "id": "sinnoh-route-202",
        "location_id": "sinnoh-route-202",
        "order": 99,
        "encounter": "Route 202",
        "responsible_player": None,
        "outcome": "pending",
        "postgame": False,
        "in_team": False,
        "picks": {player: {"species": None, "name": "", "status": "alive"} for player in ("marc", "nicolai", "knev")},
    }
    client = stored_state(data_file, [starter_row(), later])

    rows = client.get("/encounters").json()["encounters"]

    assert {row["id"]: row["order"] for row in rows} == {
        "sinnoh-route-201": 1,
        "sinnoh-route-202": 2,
        "sinnoh-victory-road": 3,
    }


def test_legacy_game_name_becomes_a_catalog_id(data_file):
    # v2 liess hier Freitext zu. Bleibt der stehen, findet das Frontend zu dieser
    # game_id keinen Katalog und bricht beim Laden komplett ab.
    state = json.loads(json.dumps(LEGACY_STATE))
    state["runs"][0]["game"] = "Pokémon Platin"
    data_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    client = TestClient(app_module.app)

    assert client.get("/encounters").json()["game_id"] == "platinum"


def test_unknown_legacy_game_name_falls_back_instead_of_stranding_the_run(data_file):
    state = json.loads(json.dumps(LEGACY_STATE))
    state["runs"][0]["game"] = "Irgendein Spiel, das es nie gab"
    data_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    client = TestClient(app_module.app)

    response = client.get("/encounters")
    assert response.status_code == 200
    assert response.json()["game_id"] == "platinum"


def test_a_history_block_in_an_old_state_is_dropped(client, data_file):
    # Bis v4 lag in alten Staenden eine 'history'-Liste. Die Historie gibt es
    # nicht mehr; der Block darf das Laden trotzdem nicht stoeren.
    client.get("/encounters")
    stored = json.loads(data_file.read_text(encoding="utf-8"))
    stored["history"] = [{"id": "h-1", "summary": "aus dem alten Stand"}]
    data_file.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")

    assert client.get("/encounters").status_code == 200
    client.patch("/encounters/sinnoh-route-201", json={"encounter": "Route 201 (neu)"})
    assert "history" not in json.loads(data_file.read_text(encoding="utf-8"))


def test_a_long_legacy_culprit_does_not_brick_the_store(data_file):
    # v2 erlaubte hier Freitext; eine engere Grenze wuerde beim Laden jeden
    # Endpoint mit 500 beantworten statt nur diese eine Zeile zu betreffen.
    state = json.loads(json.dumps(LEGACY_STATE))
    state["runs"][0]["encounters"][0]["responsible_player"] = "Mark (hat den Ponita-Fight auf Route 207 verkackt)"
    data_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    client = TestClient(app_module.app)

    assert client.get("/encounters").status_code == 200


# ------------------------------------------------------------------ Runs ---


def test_run_can_be_created_with_prefilled_locations(client):
    created = client.post(
        "/runs",
        json={"id": "run-2", "name": "Run 2", "game_id": "platinum"},
    )

    assert created.status_code == 201
    assert [row["id"] for row in created.json()["encounters"]] == [
        "sinnoh-route-201",
        "sinnoh-route-202",
        "sinnoh-victory-road",
    ]
    assert client.get("/encounters").json()["run_id"] == "run-2"


def test_postgame_locations_are_optional(client):
    created = client.post(
        "/runs",
        json={"id": "run-2", "name": "Run 2", "game_id": "platinum", "include_postgame": True},
    )

    assert [row["id"] for row in created.json()["encounters"]][-1] == "sinnoh-victory-road"


def test_run_for_unknown_game_is_rejected(client):
    response = client.post("/runs", json={"name": "Run X", "game_id": "smaragd"})

    assert response.status_code == 404


def test_progress_drives_the_level_cap(client):
    updated = client.patch("/runs/run-1", json={"progress": 1})

    assert updated.status_code == 200
    assert updated.json()["progress"] == 1


def test_a_new_run_pauses_the_running_one(client):
    client.post("/runs", json={"id": "run-2", "name": "Run 2", "game_id": "platinum"})

    statuses = {run["id"]: run["status"] for run in client.get("/runs").json()["runs"]}

    assert statuses == {"run-1": "paused", "run-2": "active"}


def test_reactivating_a_run_pauses_the_other_and_becomes_current(client):
    client.post("/runs", json={"id": "run-2", "name": "Run 2", "game_id": "platinum"})

    client.patch("/runs/run-1", json={"status": "active"})

    payload = client.get("/runs").json()
    assert {run["id"]: run["status"] for run in payload["runs"]} == {"run-1": "active", "run-2": "paused"}
    assert payload["current_run_id"] == "run-1"


def test_a_botched_run_is_marked_as_ended(client):
    updated = client.patch("/runs/run-1", json={"status": "failed"})

    assert updated.status_code == 200
    assert updated.json()["status"] == "failed"
    assert updated.json()["completed_at"] is not None


def test_pausing_a_run_takes_its_end_date_back(client):
    client.patch("/runs/run-1", json={"status": "completed"})

    updated = client.patch("/runs/run-1", json={"status": "paused"})

    assert updated.json()["completed_at"] is None


def test_a_run_can_be_renamed(client):
    assert client.patch("/runs/run-1", json={"name": "Soullink mit Ansage"}).json()["name"] == "Soullink mit Ansage"


def test_deleting_a_run_hands_its_role_to_another(client):
    client.post("/runs", json={"id": "run-2", "name": "Run 2", "game_id": "platinum"})

    assert client.delete("/runs/run-2").status_code == 204

    payload = client.get("/runs").json()
    assert [run["id"] for run in payload["runs"]] == ["run-1"]
    # Der geloeschte war der aktive und der aktuelle - beides muss weiterwandern.
    assert payload["current_run_id"] == "run-1"
    assert payload["runs"][0]["status"] == "active"


def test_deleting_a_paused_run_leaves_the_active_one_alone(client):
    client.post("/runs", json={"id": "run-2", "name": "Run 2", "game_id": "platinum"})

    client.delete("/runs/run-1")

    payload = client.get("/runs").json()
    assert payload["current_run_id"] == "run-2"
    assert payload["runs"][0]["status"] == "active"


def test_deleting_the_running_run_does_not_reactivate_a_finished_one(client):
    client.post("/runs", json={"id": "run-2", "name": "Run 2", "game_id": "platinum"})
    client.patch("/runs/run-1", json={"status": "completed"})

    client.delete("/runs/run-2")

    payload = client.get("/runs").json()
    assert payload["runs"][0]["status"] == "completed"
    assert payload["current_run_id"] == "run-1"


def test_the_last_run_cannot_be_deleted(client):
    response = client.delete("/runs/run-1")

    assert response.status_code == 409
    assert "letzte Run" in response.json()["detail"]
    assert len(client.get("/runs").json()["runs"]) == 1


def test_deleting_an_unknown_run_is_a_404(client):
    assert client.delete("/runs/gibtsnicht").status_code == 404


def test_an_unknown_run_status_does_not_brick_the_store(data_file):
    stored = json.loads(json.dumps(LEGACY_STATE))
    stored["runs"][0]["status"] = "irgendwas"
    data_file.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")

    assert TestClient(app_module.app).get("/runs").json()["runs"][0]["status"] == "active"


# --------------------------------------------------------------- Spieler ---


def test_a_new_player_gets_the_next_free_colour_and_a_column(client):
    response = client.post("/players", json={"name": "Jan Hendrik"})

    assert response.status_code == 201
    added = response.json()[-1]
    assert added == {"id": "jan-hendrik", "name": "Jan Hendrik", "color": "#8a4bb0"}
    # Ohne Eintrag in jeder Zeile liefe der naechste Patch dort ins Leere.
    rows = client.get("/encounters").json()["encounters"]
    assert all("jan-hendrik" in row["picks"] for row in rows)
    assert client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"jan-hendrik": {"species": "starly", "name": "Staralili"}}},
    ).status_code == 200


def test_a_duplicate_player_name_gets_its_own_id(client):
    client.post("/players", json={"name": "Marc"})

    assert [player["id"] for player in client.get("/players").json()] == [
        "marc",
        "nicolai",
        "knev",
        "marc-2",
    ]


def test_removing_a_player_removes_their_picks_everywhere(client):
    catch_row(client, "sinnoh-route-201")
    client.patch("/encounters/sinnoh-route-201", json={"in_team": True})

    assert client.delete("/players/knev").status_code == 204

    row = client.get("/encounters/sinnoh-route-201").json()
    assert set(row["picks"]) == {"marc", "nicolai"}
    assert row["in_team"] is True
    assert [player["id"] for player in client.get("/players").json()] == ["marc", "nicolai"]


def test_removing_the_culprit_leaves_the_incident_with_nobody(client):
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"outcome": "failed", "responsible_player": "knev"},
    )

    client.delete("/players/knev")

    row = client.get("/encounters/sinnoh-route-201").json()
    assert row["outcome"] == "failed"
    assert row["responsible_player"] == "niemand"


def test_removing_the_only_dead_player_takes_the_death_with_them(client):
    catch_row(client, "sinnoh-route-201")
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"status": "dead"}}, "responsible_player": "marc"},
        params={"couple": "false"},
    )

    client.delete("/players/marc")

    row = client.get("/encounters/sinnoh-route-201").json()
    assert row["outcome"] == "caught"
    assert row["responsible_player"] is None


def test_removing_an_unknown_player_is_a_404(client):
    assert client.delete("/players/gibtsnicht").status_code == 404


# ---------------------------------------------------------- Live-Updates ---


# Der Stream endet nie - ueber den TestClient gelesen haengt er den Testlauf auf.
# Geprueft wird deshalb der Generator selbst; die HTTP-Huelle drumherum ist eine
# StreamingResponse ohne eigene Logik.
async def read_events(count, between=None):
    response = await app_module.stream_events()
    assert response.media_type == "text/event-stream"
    # Ohne diesen Header puffert nginx den Stream, bis der Puffer voll ist.
    assert response.raw_headers is not None
    assert response.headers["x-accel-buffering"] == "no"

    events = []
    iterator = response.body_iterator
    while len(events) < count:
        chunk = await iterator.__anext__()
        if chunk.startswith("data: "):
            events.append(json.loads(chunk.removeprefix("data: ")))
            if between and len(events) == 1:
                between()
    await iterator.aclose()
    return events


def test_the_event_stream_starts_with_the_current_state(client):
    expected = client.get("/runs").json()["updated_at"]

    events = asyncio.run(read_events(1))

    assert events == [{"updated_at": expected}]


def test_the_event_stream_announces_a_change(client):
    def write():
        client.patch("/encounters/sinnoh-route-201", json={"picks": {"marc": {"name": "Bidiza"}}})

    events = asyncio.run(read_events(2, between=write))

    assert events[0]["updated_at"] != events[1]["updated_at"]
    assert events[1]["updated_at"] == client.get("/runs").json()["updated_at"]


def test_the_event_stream_ends_by_itself(client, monkeypatch):
    """Ein Stream ohne Ende haelt den Prozess fest: uvicorn wartet beim Beenden
    auf offene Verbindungen, und jeder Neustart bliebe stehen, solange auch nur
    ein Browser lauscht."""
    monkeypatch.setattr(app_module, "STREAM_MAX_SECONDS", 0.05)
    monkeypatch.setattr(app_module, "STREAM_TICK_SECONDS", 0.01)

    async def drain():
        response = await app_module.stream_events()
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(drain())

    # Der Browser verbindet sich selbst neu - dafuer steht die Wartezeit am Anfang.
    assert chunks[0] == f"retry: {app_module.STREAM_RETRY_MS}\n\n"
    assert any(chunk.startswith("data: ") for chunk in chunks)


# -------------------------------------------------------------- Soullink ---


def test_a_single_death_kills_the_whole_row(client):
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"status": "dead"}}, "responsible_player": "marc"},
    )

    row = response.json()
    assert row["outcome"] == "dead"
    assert [pick["status"] for pick in row["picks"].values()] == ["dead", "dead", "dead"]
    assert row["responsible_player"] == "marc"


def test_coupling_can_be_switched_off_to_revive(client):
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"status": "dead"}}, "responsible_player": "marc"},
    )

    response = client.patch(
        "/encounters/sinnoh-route-201?couple=false",
        json={"picks": {"marc": {"status": "alive"}}},
    )

    statuses = {player: pick["status"] for player, pick in response.json()["picks"].items()}
    assert statuses["marc"] == "alive"
    assert statuses["nicolai"] == "dead"


def test_marking_a_row_lost_fills_every_player(client):
    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"outcome": "failed", "responsible_player": "marc"},
    )

    picks = response.json()["picks"]
    assert [pick["name"] for pick in picks.values()] == ["Encounter verloren"] * 3
    assert all(pick["species"] is None for pick in picks.values())


def test_a_lost_row_overwrites_an_existing_pick(client):
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"outcome": "failed", "responsible_player": "marc"},
    )

    assert response.json()["picks"]["marc"]["name"] == "Encounter verloren"
    assert response.json()["picks"]["marc"]["species"] is None


def test_setting_the_row_dead_kills_every_pick(client):
    # Das Frontend meldet den Tod ueber das Status-Feld der Zeile. Ohne Kopplung
    # stuende dort ein Tod, den kein Pick traegt.
    catch_row(client, "sinnoh-route-201")

    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"outcome": "dead", "responsible_player": "marc"},
    )

    assert response.status_code == 200
    assert [pick["status"] for pick in response.json()["picks"].values()] == ["dead"] * 3


def test_a_death_survives_an_unrelated_edit(client):
    catch_row(client, "sinnoh-route-201")
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"outcome": "dead", "responsible_player": "marc"},
    )

    response = client.patch("/encounters/sinnoh-route-201", json={"encounter": "Route 201 (Nordausgang)"})

    assert response.json()["outcome"] == "dead"
    assert client.get("/stats").json()["total_deaths"] == 1


def test_a_death_without_coupling_needs_a_dead_pick(client):
    catch_row(client, "sinnoh-route-201")

    response = client.patch(
        "/encounters/sinnoh-route-201?couple=false",
        json={"outcome": "dead", "responsible_player": "marc"},
    )

    assert response.status_code == 422


def test_a_death_wins_over_a_lost_encounter(client):
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"status": "dead"}}, "responsible_player": "marc"},
    )

    response = client.patch("/encounters/sinnoh-route-201", json={"outcome": "failed"})

    # Tote Reihe bleibt tot - der Platzhalter wuerde den Tod ueberschreiben.
    assert all(pick["name"] != "Encounter verloren" for pick in response.json()["picks"].values())


def test_outcome_follows_the_picks(client):
    empty = client.get("/encounters/sinnoh-route-202").json()
    assert empty["outcome"] == "pending"

    filled = client.patch(
        "/encounters/sinnoh-route-202",
        json={"picks": {"knev": {"species": "shinx", "name": "Sheinux"}}},
    )
    assert filled.json()["outcome"] == "caught"

    lost = client.patch(
        "/encounters/sinnoh-route-202",
        json={"picks": {"knev": {"species": None, "name": "Encounter verloren"}}, "responsible_player": "knev"},
    )
    assert lost.json()["outcome"] == "failed"


# ----------------------------------------------------------- Aktive Links ---


def catch_row(client, row_id, species="starly", name="Staralili"):
    """Reihe vollstaendig fuellen, damit sie ins Team darf."""
    return client.patch(
        f"/encounters/{row_id}?force=true",
        json={"picks": {player: {"species": species, "name": name} for player in ("marc", "nicolai", "knev")}},
    )


def test_a_caught_row_can_join_the_team(client):
    catch_row(client, "sinnoh-route-201")

    response = client.patch("/encounters/sinnoh-route-201", json={"in_team": True})

    assert response.status_code == 200
    assert response.json()["in_team"] is True
    assert client.get("/runs").json()["runs"][0]["team_count"] == 1


def test_an_unfinished_row_cannot_join_the_team(client):
    response = client.patch("/encounters/sinnoh-route-201", json={"in_team": True})

    assert response.status_code == 422


def test_the_team_holds_at_most_six_links(client):
    # Der Mini-Katalog hat zwei Orte, der Rest kommt als Freitext-Zeile dazu.
    for index in range(7):
        row_id = f"platz-{index}"
        client.post(
            "/encounters",
                json={
                "id": row_id,
                "encounter": f"Platz {index}",
                "picks": {player: {"name": "Irgendwas"} for player in ("marc", "nicolai", "knev")},
            },
        )
        response = client.patch(f"/encounters/{row_id}", json={"in_team": True})
        expected = 200 if index < 6 else 409
        assert response.status_code == expected, f"Platz {index}: {response.json()}"

    assert client.get("/runs").json()["runs"][0]["team_count"] == 6
    assert "voll" in response.json()["detail"]


def test_a_row_with_only_one_pick_can_join_the_team(client):
    # Dass ein Spieler an einem Ort leer ausgeht, ist im Soullink der Normalfall -
    # die Reihe belegt trotzdem bei allen denselben Platz.
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    response = client.patch("/encounters/sinnoh-route-201", json={"in_team": True})

    assert response.status_code == 200
    assert response.json()["in_team"] is True


def test_a_death_takes_the_link_out_of_the_team(client):
    catch_row(client, "sinnoh-route-201")
    client.patch("/encounters/sinnoh-route-201", json={"in_team": True})

    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"status": "dead"}}, "responsible_player": "marc"},
    )

    assert response.json()["outcome"] == "dead"
    assert response.json()["in_team"] is False


def test_a_lost_row_leaves_the_team_as_well(client):
    catch_row(client, "sinnoh-route-201")
    client.patch("/encounters/sinnoh-route-201", json={"in_team": True})

    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"outcome": "failed", "responsible_player": "marc"},
    )

    assert response.json()["in_team"] is False


# ------------------------------------------------------------ Validierung ---


def test_species_must_be_catchable_at_that_location(client):
    response = client.patch(
        "/encounters/sinnoh-route-202",
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    assert response.status_code == 422
    assert "Route 202" in response.json()["detail"]


def test_force_overrides_the_species_check(client):
    response = client.patch(
        "/encounters/sinnoh-route-202?force=true",
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    assert response.status_code == 200
    assert response.json()["picks"]["marc"]["species"] == "starly"


def test_a_forced_entry_does_not_block_later_edits(client):
    client.patch(
        "/encounters/sinnoh-route-202?force=true",
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    response = client.patch(
        "/encounters/sinnoh-route-202",
        json={"picks": {"knev": {"species": "shinx", "name": "Sheinux"}}},
    )

    assert response.status_code == 200


def test_a_forced_entry_does_not_block_the_kill_button(client):
    # Derselbe Spieler, nur der Status: der Patch fasst die Art nicht an, also
    # darf die Artpruefung hier auch nicht zuschlagen.
    client.patch(
        "/encounters/sinnoh-route-202?force=true",
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    response = client.patch(
        "/encounters/sinnoh-route-202",
        json={"picks": {"marc": {"status": "dead"}}, "responsible_player": "marc"},
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "dead"


def test_null_for_a_required_field_is_a_client_error(client):
    # Ohne Pruefung landet das None in der Zeile und erst die Modellpruefung am
    # Ende schlaegt fehl - der Aufrufer saehe einen 500er.
    for body in ({"outcome": None}, {"encounter": None}, {"in_team": None}):
        response = client.patch("/encounters/sinnoh-route-201", json=body)
        assert response.status_code == 422, body


def test_null_clears_the_fields_that_may_be_empty(client):
    client.patch("/encounters/sinnoh-route-201", json={"responsible_player": "marc"})

    response = client.patch("/encounters/sinnoh-route-201", json={"responsible_player": None})

    assert response.status_code == 200
    assert response.json()["responsible_player"] is None


def test_progress_cannot_run_past_the_level_caps(client):
    # Der Mini-Katalog kennt genau einen Cap.
    response = client.patch("/runs/run-1", json={"progress": 99})

    assert response.status_code == 200
    assert response.json()["progress"] == 1


def test_unknown_player_is_rejected_when_creating_a_row(client):
    response = client.post(
        "/encounters",
        json={"id": "extra", "encounter": "Extra", "picks": {"kevin": {"name": "Bidiza"}}},
    )

    assert response.status_code == 422


def test_free_text_needs_no_species(client):
    response = client.patch(
        "/encounters/sinnoh-route-202",
        json={
            "picks": {"marc": {"species": None, "name": "Kein Encounter – verpennt"}},
            "responsible_player": "marc",
        },
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "failed"


def test_unknown_player_is_rejected(client):
    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"kevin": {"name": "Zubat"}}},
    )

    assert response.status_code == 422


# --------------------------------------------------------------- Schuldiger ---


def test_a_death_without_a_culprit_is_refused(client):
    catch_row(client, "sinnoh-route-201")

    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"status": "dead"}}},
    )

    assert response.status_code == 422
    assert "Schuldige" in response.json()["detail"]
    # Die Zeile darf davon unberuehrt bleiben.
    assert client.get("/encounters/sinnoh-route-201").json()["outcome"] == "caught"


def test_a_lost_encounter_without_a_culprit_is_refused(client):
    response = client.patch("/encounters/sinnoh-route-201", json={"outcome": "failed"})

    assert response.status_code == 422


def test_nobody_can_be_named_explicitly(client):
    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"outcome": "failed", "responsible_player": "niemand"},
    )

    assert response.status_code == 200
    assert response.json()["responsible_player"] == "niemand"


def test_an_unknown_culprit_is_rejected(client):
    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"outcome": "failed", "responsible_player": "kevin"},
    )

    assert response.status_code == 422


def test_the_culprit_cannot_be_removed_from_a_death(client):
    catch_row(client, "sinnoh-route-201")
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"status": "dead"}}, "responsible_player": "marc"},
    )

    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"responsible_player": None},
    )

    assert response.status_code == 422


# --------------------------------------------------------------- Backups ---


def test_a_daily_backup_is_kept_before_overwriting(client, data_file):
    client.get("/encounters")  # legt den Store an
    client.patch("/encounters/sinnoh-route-201", json={"encounter": "Route 201 (irgendwas)"})

    backups = list((data_file.parent / "backups").glob(f"{data_file.stem}-*.json"))

    assert len(backups) == 1


def test_a_schema_migration_backs_the_old_state_up_first(legacy_client, data_file):
    legacy_client.get("/encounters")

    migration = list((data_file.parent / "backups").glob("migration-*.json"))

    assert len(migration) == 1
    # Die Kopie muss den Stand VOR der Migration enthalten.
    assert "mark" in json.loads(migration[0].read_text(encoding="utf-8"))["runs"][0]["encounters"][0]


# ------------------------------------------------------------ Schreibrecht ---


def test_writes_are_open_when_no_token_is_configured(client):
    response = client.patch("/encounters/sinnoh-route-201", json={"encounter": "Route 201 (ohne Token)"})

    assert response.status_code == 200


def test_configured_token_does_not_make_writes_private(client, monkeypatch):
    monkeypatch.setenv("ENCOUNTER_API_TOKEN", "geheim")

    response = client.patch(
        "/encounters/sinnoh-route-201",
        json={"encounter": "Route 201 (ok)"},
    )
    assert response.status_code == 200


def test_stale_if_match_is_rejected(client):
    stale = client.patch(
        "/encounters/sinnoh-route-201",
        headers={"If-Match": "2020-01-01T00:00:00+00:00"},
        json={"encounter": "Route 201 (veraltet)"},
    )
    assert stale.status_code == 412

    current = client.get("/encounters").json()["updated_at"]
    fresh = client.patch(
        "/encounters/sinnoh-route-201",
        headers={"If-Match": current},
        json={"encounter": "Route 201 (aktuell)"},
    )
    assert fresh.status_code == 200


# -------------------------------------------------------------- Statistik ---


def test_a_coupled_death_counts_once_and_only_for_the_culprit(client):
    catch_row(client, "sinnoh-route-201")
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"knev": {"status": "dead"}}, "responsible_player": "knev"},
    )

    stats = client.get("/stats").json()

    # Die Reihe verliert drei Pokémon, es zaehlt aber nur der Tod des Verursachers.
    assert stats["total_deaths"] == 1
    assert stats["deaths_by_player"] == {"marc": 0, "nicolai": 0, "knev": 1}
    assert stats["blame_by_player"] == {"marc": 0, "nicolai": 0, "knev": 1}


def test_a_botched_encounter_only_blames_its_culprit(client):
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"outcome": "failed", "responsible_player": "marc"},
    )

    stats = client.get("/stats").json()

    assert stats["total_failed_encounters"] == 1
    assert stats["failed_encounters_by_player"] == {"marc": 1, "nicolai": 0, "knev": 0}
    assert stats["blame_by_player"]["marc"] == 1


def test_blame_adds_deaths_and_botched_encounters_per_player(client):
    catch_row(client, "sinnoh-route-201")
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"status": "dead"}}, "responsible_player": "marc"},
    )
    client.patch(
        "/encounters/sinnoh-route-202",
        json={"outcome": "failed", "responsible_player": "marc"},
    )

    stats = client.get("/stats").json()

    assert stats["deaths_by_player"]["marc"] == 1
    assert stats["failed_encounters_by_player"]["marc"] == 1
    assert stats["blame_by_player"]["marc"] == 2
    assert stats["total_blame"] == 2


def test_every_lost_pokemon_of_one_player_adds_blame(client):
    for row_id in ("platz-1", "platz-2", "platz-3"):
        client.post(
            "/encounters",
                json={
                "id": row_id,
                "encounter": row_id,
                "picks": {player: {"name": "Irgendwas"} for player in ("marc", "nicolai", "knev")},
            },
        )
        client.patch(
            f"/encounters/{row_id}",
                json={"picks": {"marc": {"status": "dead"}}, "responsible_player": "marc"},
        )

    stats = client.get("/stats").json()

    assert stats["total_deaths"] == 3
    assert stats["deaths_by_player"]["marc"] == 3
    assert stats["blame_by_player"]["marc"] == 3


def test_rows_without_a_culprit_are_reported_separately(client):
    catch_row(client, "sinnoh-route-201")
    client.patch(
        "/encounters/sinnoh-route-201",
        json={"picks": {"marc": {"status": "dead"}}, "responsible_player": "niemand"},
    )

    stats = client.get("/stats").json()

    assert stats["total_deaths"] == 1
    assert stats["unassigned_deaths"] == 1
    assert stats["blame_by_player"] == {"marc": 0, "nicolai": 0, "knev": 0}


def test_stats_can_be_limited_to_one_game(client):
    stats = client.get("/stats?game_id=platinum").json()
    assert stats["scope"] == "platinum"
    assert stats["total_runs"] == 1
