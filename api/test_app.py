import json

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
                    "note": None,
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

AUTHOR = {"X-Encounter-Author": "marc"}


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


# --------------------------------------------------------------- Katalog ---


def test_games_endpoint_lists_the_catalog(client):
    response = client.get("/games")

    assert response.status_code == 200
    assert response.json() == [{"id": "platinum", "name": "Testplatin", "location_count": 3}]


def test_unknown_game_is_reported(client):
    assert client.get("/games/smaragd").status_code == 404


def test_empty_store_starts_prefilled_without_postgame(client):
    payload = client.get("/encounters").json()

    assert [row["id"] for row in payload["encounters"]] == ["sinnoh-route-201", "sinnoh-route-202"]
    assert all(row["outcome"] == "pending" for row in payload["encounters"])
    assert payload["game_name"] == "Testplatin"


# ------------------------------------------------------------- Migration ---


def test_legacy_state_migrates_to_players_and_picks(legacy_client):
    payload = legacy_client.get("/encounters").json()

    assert payload["players"] == [
        {"id": "marc", "name": "Marc"},
        {"id": "nicolai", "name": "Nicolai"},
        {"id": "knev", "name": "Knev"},
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


def test_shouted_legacy_name_is_corrected_in_v3_data(client, data_file):
    client.get("/encounters")  # legt den Store ueberhaupt erst an
    stored = json.loads(data_file.read_text(encoding="utf-8"))
    stored["players"] = [
        {"id": "marc", "name": "Marc"},
        {"id": "nicolai", "name": "Nicolai"},
        {"id": "knev", "name": "KNEV"},
    ]
    data_file.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")

    names = [player["name"] for player in client.get("/runs").json()["players"]]

    assert names == ["Marc", "Nicolai", "Knev"]


def test_migration_is_written_back_once(legacy_client, data_file):
    legacy_client.get("/encounters")
    stored = json.loads(data_file.read_text(encoding="utf-8"))

    assert stored["schema_version"] == 3
    assert "mark" not in stored["runs"][0]["encounters"][0]


# ------------------------------------------------------------------ Runs ---


def test_run_can_be_created_with_prefilled_locations(client):
    created = client.post(
        "/runs",
        headers=AUTHOR,
        json={"id": "run-2", "name": "Run 2", "game_id": "platinum"},
    )

    assert created.status_code == 201
    assert [row["id"] for row in created.json()["encounters"]] == ["sinnoh-route-201", "sinnoh-route-202"]
    assert client.get("/encounters").json()["run_id"] == "run-2"


def test_postgame_locations_are_optional(client):
    created = client.post(
        "/runs",
        headers=AUTHOR,
        json={"id": "run-2", "name": "Run 2", "game_id": "platinum", "include_postgame": True},
    )

    assert [row["id"] for row in created.json()["encounters"]][-1] == "sinnoh-victory-road"


def test_run_for_unknown_game_is_rejected(client):
    response = client.post("/runs", headers=AUTHOR, json={"name": "Run X", "game_id": "smaragd"})

    assert response.status_code == 404


def test_progress_drives_the_level_cap(client):
    updated = client.patch("/runs/run-1", headers=AUTHOR, json={"progress": 1})

    assert updated.status_code == 200
    assert updated.json()["progress"] == 1


# -------------------------------------------------------------- Soullink ---


def test_a_single_death_kills_the_whole_row(client):
    client.patch(
        "/encounters/sinnoh-route-201",
        headers=AUTHOR,
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    response = client.patch(
        "/encounters/sinnoh-route-201",
        headers=AUTHOR,
        json={"picks": {"marc": {"status": "dead"}}, "responsible_player": "marc"},
    )

    row = response.json()
    assert row["outcome"] == "dead"
    assert [pick["status"] for pick in row["picks"].values()] == ["dead", "dead", "dead"]
    assert row["responsible_player"] == "marc"


def test_coupling_can_be_switched_off_to_revive(client):
    client.patch("/encounters/sinnoh-route-201", headers=AUTHOR, json={"picks": {"marc": {"status": "dead"}}})

    response = client.patch(
        "/encounters/sinnoh-route-201?couple=false",
        headers=AUTHOR,
        json={"picks": {"marc": {"status": "alive"}}},
    )

    statuses = {player: pick["status"] for player, pick in response.json()["picks"].items()}
    assert statuses["marc"] == "alive"
    assert statuses["nicolai"] == "dead"


def test_marking_a_row_lost_fills_every_player(client):
    response = client.patch("/encounters/sinnoh-route-201", headers=AUTHOR, json={"outcome": "failed"})

    picks = response.json()["picks"]
    assert [pick["name"] for pick in picks.values()] == ["Encounter verloren"] * 3
    assert all(pick["species"] is None for pick in picks.values())


def test_a_lost_row_overwrites_an_existing_pick(client):
    client.patch(
        "/encounters/sinnoh-route-201",
        headers=AUTHOR,
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    response = client.patch("/encounters/sinnoh-route-201", headers=AUTHOR, json={"outcome": "failed"})

    assert response.json()["picks"]["marc"]["name"] == "Encounter verloren"
    assert response.json()["picks"]["marc"]["species"] is None


def test_a_death_wins_over_a_lost_encounter(client):
    client.patch("/encounters/sinnoh-route-201", headers=AUTHOR, json={"picks": {"marc": {"status": "dead"}}})

    response = client.patch("/encounters/sinnoh-route-201", headers=AUTHOR, json={"outcome": "failed"})

    # Tote Reihe bleibt tot - der Platzhalter wuerde den Tod ueberschreiben.
    assert all(pick["name"] != "Encounter verloren" for pick in response.json()["picks"].values())


def test_outcome_follows_the_picks(client):
    empty = client.get("/encounters/sinnoh-route-202").json()
    assert empty["outcome"] == "pending"

    filled = client.patch(
        "/encounters/sinnoh-route-202",
        headers=AUTHOR,
        json={"picks": {"knev": {"species": "shinx", "name": "Sheinux"}}},
    )
    assert filled.json()["outcome"] == "caught"

    lost = client.patch(
        "/encounters/sinnoh-route-202",
        headers=AUTHOR,
        json={"picks": {"knev": {"species": None, "name": "Encounter verloren"}}},
    )
    assert lost.json()["outcome"] == "failed"


# ----------------------------------------------------------- Aktive Links ---


def catch_row(client, row_id, species="starly", name="Staralili"):
    """Reihe vollstaendig fuellen, damit sie ins Team darf."""
    return client.patch(
        f"/encounters/{row_id}?force=true",
        headers=AUTHOR,
        json={"picks": {player: {"species": species, "name": name} for player in ("marc", "nicolai", "knev")}},
    )


def test_a_caught_row_can_join_the_team(client):
    catch_row(client, "sinnoh-route-201")

    response = client.patch("/encounters/sinnoh-route-201", headers=AUTHOR, json={"in_team": True})

    assert response.status_code == 200
    assert response.json()["in_team"] is True
    assert client.get("/runs").json()["runs"][0]["team_count"] == 1


def test_an_unfinished_row_cannot_join_the_team(client):
    response = client.patch("/encounters/sinnoh-route-201", headers=AUTHOR, json={"in_team": True})

    assert response.status_code == 422


def test_the_team_holds_at_most_six_links(client):
    # Der Mini-Katalog hat zwei Orte, der Rest kommt als Freitext-Zeile dazu.
    for index in range(7):
        row_id = f"platz-{index}"
        client.post(
            "/encounters",
            headers=AUTHOR,
            json={
                "id": row_id,
                "encounter": f"Platz {index}",
                "picks": {player: {"name": "Irgendwas"} for player in ("marc", "nicolai", "knev")},
            },
        )
        response = client.patch(f"/encounters/{row_id}", headers=AUTHOR, json={"in_team": True})
        expected = 200 if index < 6 else 409
        assert response.status_code == expected, f"Platz {index}: {response.json()}"

    assert client.get("/runs").json()["runs"][0]["team_count"] == 6
    assert "voll" in response.json()["detail"]


def test_a_death_takes_the_link_out_of_the_team(client):
    catch_row(client, "sinnoh-route-201")
    client.patch("/encounters/sinnoh-route-201", headers=AUTHOR, json={"in_team": True})

    response = client.patch(
        "/encounters/sinnoh-route-201",
        headers=AUTHOR,
        json={"picks": {"marc": {"status": "dead"}}},
    )

    assert response.json()["outcome"] == "dead"
    assert response.json()["in_team"] is False


def test_a_lost_row_leaves_the_team_as_well(client):
    catch_row(client, "sinnoh-route-201")
    client.patch("/encounters/sinnoh-route-201", headers=AUTHOR, json={"in_team": True})

    response = client.patch("/encounters/sinnoh-route-201", headers=AUTHOR, json={"outcome": "failed"})

    assert response.json()["in_team"] is False


# ------------------------------------------------------------ Validierung ---


def test_species_must_be_catchable_at_that_location(client):
    response = client.patch(
        "/encounters/sinnoh-route-202",
        headers=AUTHOR,
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    assert response.status_code == 422
    assert "Route 202" in response.json()["detail"]


def test_force_overrides_the_species_check(client):
    response = client.patch(
        "/encounters/sinnoh-route-202?force=true",
        headers=AUTHOR,
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    assert response.status_code == 200
    assert response.json()["picks"]["marc"]["species"] == "starly"


def test_a_forced_entry_does_not_block_later_edits(client):
    client.patch(
        "/encounters/sinnoh-route-202?force=true",
        headers=AUTHOR,
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    response = client.patch(
        "/encounters/sinnoh-route-202",
        headers=AUTHOR,
        json={"picks": {"knev": {"species": "shinx", "name": "Sheinux"}}},
    )

    assert response.status_code == 200


def test_free_text_needs_no_species(client):
    response = client.patch(
        "/encounters/sinnoh-route-202",
        headers=AUTHOR,
        json={"picks": {"marc": {"species": None, "name": "Kein Encounter – verpennt"}}},
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "failed"


def test_unknown_player_is_rejected(client):
    response = client.patch(
        "/encounters/sinnoh-route-201",
        headers=AUTHOR,
        json={"picks": {"kevin": {"name": "Zubat"}}},
    )

    assert response.status_code == 422


# --------------------------------------------------------------- Historie ---


def test_history_records_author_and_can_be_undone(client):
    client.patch(
        "/encounters/sinnoh-route-201",
        headers=AUTHOR,
        json={"picks": {"marc": {"species": "starly", "name": "Staralili"}}},
    )

    entries = client.get("/history").json()["entries"]
    assert entries[0]["author"] == "marc"
    assert entries[0]["action"] == "row-patch"

    undone = client.post(f"/history/{entries[0]['id']}/undo", headers=AUTHOR)
    assert undone.status_code == 200

    row = client.get("/encounters/sinnoh-route-201").json()
    assert row["picks"]["marc"]["name"] == ""
    assert row["outcome"] == "pending"


def test_undo_is_refused_twice(client):
    client.patch("/encounters/sinnoh-route-201", headers=AUTHOR, json={"note": "erste Notiz"})
    entry_id = client.get("/history").json()["entries"][0]["id"]

    assert client.post(f"/history/{entry_id}/undo", headers=AUTHOR).status_code == 200
    assert client.post(f"/history/{entry_id}/undo", headers=AUTHOR).status_code == 409


def test_deleted_row_can_be_restored(client):
    assert client.delete("/encounters/sinnoh-route-202", headers=AUTHOR).status_code == 204
    assert len(client.get("/encounters").json()["encounters"]) == 1

    entry_id = client.get("/history").json()["entries"][0]["id"]
    assert client.post(f"/history/{entry_id}/undo", headers=AUTHOR).status_code == 200

    rows = [row["id"] for row in client.get("/encounters").json()["encounters"]]
    assert rows == ["sinnoh-route-201", "sinnoh-route-202"]


# ------------------------------------------------------------ Schreibrecht ---


def test_writes_are_open_when_no_token_is_configured(client):
    response = client.patch("/encounters/sinnoh-route-201", json={"note": "ohne Token"})

    assert response.status_code == 200


def test_configured_token_makes_writes_private(client, monkeypatch):
    monkeypatch.setenv("ENCOUNTER_API_TOKEN", "geheim")

    denied = client.patch("/encounters/sinnoh-route-201", json={"note": "nope"})
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"

    allowed = client.patch(
        "/encounters/sinnoh-route-201",
        headers={"Authorization": "Bearer geheim"},
        json={"note": "ok"},
    )
    assert allowed.status_code == 200


def test_stale_if_match_is_rejected(client):
    stale = client.patch(
        "/encounters/sinnoh-route-201",
        headers={**AUTHOR, "If-Match": "2020-01-01T00:00:00+00:00"},
        json={"note": "veraltet"},
    )
    assert stale.status_code == 412

    current = client.get("/encounters").json()["updated_at"]
    fresh = client.patch(
        "/encounters/sinnoh-route-201",
        headers={**AUTHOR, "If-Match": current},
        json={"note": "aktuell"},
    )
    assert fresh.status_code == 200


# -------------------------------------------------------------- Statistik ---


def test_stats_count_coupled_deaths_once_and_per_player(client):
    client.patch(
        "/encounters/sinnoh-route-201",
        headers=AUTHOR,
        json={
            "picks": {
                "marc": {"species": "starly", "name": "Staralili"},
                "nicolai": {"species": "bidoof", "name": "Bidiza"},
                "knev": {"species": "starly", "name": "Staralili"},
            }
        },
    )
    client.patch(
        "/encounters/sinnoh-route-201",
        headers=AUTHOR,
        json={"picks": {"knev": {"status": "dead"}}, "responsible_player": "knev"},
    )

    stats = client.get("/stats").json()

    assert stats["total_death_rows"] == 1
    assert stats["dead_pokemon_by_player"] == {"marc": 1, "nicolai": 1, "knev": 1}
    assert stats["responsibility_by_player"]["knev"] == 1
    assert stats["total_pending_rows"] == 1


def test_stats_can_be_limited_to_one_game(client):
    stats = client.get("/stats?game_id=platinum").json()
    assert stats["scope"] == "platinum"
    assert stats["total_runs"] == 1
