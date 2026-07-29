import json

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_read_encounters_returns_public_table(monkeypatch, tmp_path):
    monkeypatch.setenv("ENCOUNTER_DATA_PATH", str(tmp_path / "encounters.json"))
    response = client.get("/encounters")

    assert response.status_code == 200
    payload = response.json()
    assert payload["players"] == ["Mark", "Nikolai", "KNEV"]
    assert len(payload["encounters"]) == 8
    assert payload["encounters"][0]["encounter"] == "Route 201 (Starter)"


def test_writes_require_bearer_token(monkeypatch, tmp_path):
    monkeypatch.setenv("ENCOUNTER_DATA_PATH", str(tmp_path / "encounters.json"))
    monkeypatch.setenv("ENCOUNTER_API_TOKEN", "test-token")

    response = client.patch(
        "/encounters/route-207",
        json={"mark": "Ponita besiegt"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_patch_updates_and_persists_a_row(monkeypatch, tmp_path):
    data_path = tmp_path / "encounters.json"
    monkeypatch.setenv("ENCOUNTER_DATA_PATH", str(data_path))
    monkeypatch.setenv("ENCOUNTER_API_TOKEN", "test-token")

    response = client.patch(
        "/encounters/route-207",
        headers={"Authorization": "Bearer test-token"},
        json={"mark": "Kein Encounter – neues Ergebnis"},
    )

    assert response.status_code == 200
    assert response.json()["mark"] == "Kein Encounter – neues Ergebnis"
    stored = json.loads(data_path.read_text())
    assert stored["runs"][0]["encounters"][-1]["mark"] == "Kein Encounter – neues Ergebnis"


def test_death_status_can_be_set_for_individual_players(monkeypatch, tmp_path):
    monkeypatch.setenv("ENCOUNTER_DATA_PATH", str(tmp_path / "encounters.json"))
    monkeypatch.setenv("ENCOUNTER_API_TOKEN", "test-token")

    response = client.patch(
        "/encounters/erzelinger-tunnel-oreburgh-gate",
        headers={"Authorization": "Bearer test-token"},
        json={"nikolai_status": "dead", "knev_status": "dead"},
    )

    assert response.status_code == 200
    assert response.json()["nikolai_status"] == "dead"
    assert response.json()["knev_status"] == "dead"


def test_authenticated_agent_can_add_and_delete_a_row(monkeypatch, tmp_path):
    monkeypatch.setenv("ENCOUNTER_DATA_PATH", str(tmp_path / "encounters.json"))
    monkeypatch.setenv("ENCOUNTER_API_TOKEN", "test-token")
    headers = {"Authorization": "Bearer test-token"}

    created = client.post(
        "/encounters",
        headers=headers,
        json={
            "id": "route-209",
            "encounter": "Route 209",
            "mark": "Karpador",
            "nikolai": "Garados",
            "knev": "Tentacha",
        },
    )
    assert created.status_code == 201
    assert created.json()["id"] == "route-209"

    deleted = client.delete("/encounters/route-209", headers=headers)
    assert deleted.status_code == 204
    assert all(row["id"] != "route-209" for row in client.get("/encounters").json()["encounters"])


def test_legacy_table_is_exposed_as_the_first_run(monkeypatch, tmp_path):
    monkeypatch.setenv("ENCOUNTER_DATA_PATH", str(tmp_path / "encounters.json"))

    runs = client.get("/runs")

    assert runs.status_code == 200
    payload = runs.json()
    assert payload["current_run_id"] == "run-1"
    assert payload["runs"][0]["id"] == "run-1"
    assert payload["runs"][0]["name"] == "Run 1"
    assert payload["runs"][0]["encounter_count"] == 8


def test_authenticated_user_can_create_run_and_add_encounter(monkeypatch, tmp_path):
    monkeypatch.setenv("ENCOUNTER_DATA_PATH", str(tmp_path / "encounters.json"))
    monkeypatch.setenv("ENCOUNTER_API_TOKEN", "test-token")
    headers = {"Authorization": "Bearer test-token"}

    created = client.post(
        "/runs",
        headers=headers,
        json={"id": "run-2", "name": "Run 2", "game": "Pokémon Platin"},
    )
    assert created.status_code == 201
    assert created.json()["id"] == "run-2"
    assert client.get("/encounters").json()["run_id"] == "run-2"

    encounter = client.post(
        "/runs/run-2/encounters",
        headers=headers,
        json={
            "id": "route-202",
            "encounter": "Route 202",
            "mark": "Sheinux",
            "nikolai": "Bidiza",
            "knev": "Sheinux",
        },
    )
    assert encounter.status_code == 201
    assert encounter.json()["outcome"] == "caught"
    assert len(client.get("/runs/run-2/encounters").json()["encounters"]) == 1
    assert len(client.get("/runs/run-1/encounters").json()["encounters"]) == 8


def test_all_time_stats_include_deaths_and_responsibility_across_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("ENCOUNTER_DATA_PATH", str(tmp_path / "encounters.json"))
    monkeypatch.setenv("ENCOUNTER_API_TOKEN", "test-token")
    headers = {"Authorization": "Bearer test-token"}

    death = client.patch(
        "/encounters/route-204",
        headers=headers,
        json={"mark_status": "dead", "nikolai_status": "dead", "knev_status": "dead", "responsible_player": "Nikolai"},
    )
    assert death.status_code == 200

    client.post("/runs", headers=headers, json={"id": "run-2", "name": "Run 2"})
    failed = client.post(
        "/runs/run-2/encounters",
        headers=headers,
        json={
            "id": "route-203",
            "encounter": "Route 203",
            "mark": "Encounter verloren",
            "nikolai": "Encounter verloren",
            "knev": "Encounter verloren",
            "responsible_player": "Mark",
            "outcome": "failed",
        },
    )
    assert failed.status_code == 201

    stats = client.get("/stats")

    assert stats.status_code == 200
    payload = stats.json()
    assert payload["total_runs"] == 2
    assert payload["total_encounter_rows"] == 9
    assert payload["total_death_rows"] == 1
    assert payload["total_failed_rows"] == 2
    assert payload["responsibility_by_player"]["Nikolai"] == 1
    assert payload["responsibility_by_player"]["Mark"] == 1
    assert payload["dead_pokemon_by_player"]["Mark"] == 1
    assert payload["dead_pokemon_by_player"]["Nikolai"] == 1
    assert payload["dead_pokemon_by_player"]["KNEV"] == 1
    assert payload["failed_encounters_by_player"]["Mark"] == 1
    assert payload["failed_encounters_by_player"]["Nikolai"] == 0