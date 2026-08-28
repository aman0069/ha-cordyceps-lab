"""Contract smoke coverage for the LDS."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ADDON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON))


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    os.environ["LDS_DATA_DIR"] = str(tmp_path)
    os.environ["LDS_TOKEN"] = "smoke-token"
    # db.py records the data location at import time, so isolate every test reload.
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    import app.main as main
    importlib.reload(main)
    with TestClient(main.app) as test_client:
        yield test_client


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer smoke-token"}


def test_contract_smoke(client: TestClient, tmp_path: Path) -> None:
    created = client.post("/batches", headers=auth(), json={
        "created_ts": "2026-08-21T21:39:00+05:30", "strain": "CM-Delhi",
        "recipe_version": "R-2026.3", "jar_count_planned": 20, "operator": "Aman",
        "client_event_id": "batch-create-001",
    })
    assert created.status_code == 200, created.text
    result = created.json()
    assert result["batch_id"] == "AC-20260821-01"
    assert result["jar_ids"] == [f"AC-20260821-01-J{i:03d}" for i in range(1, 21)]

    batch = client.get("/batches/AC-20260821-01", headers=auth()).json()
    tokens = [result["scan_token"], *[jar["scan_token"] for jar in batch["jars"]]]
    assert len(tokens) == len(set(tokens)) == 21
    assert all(len(token) == 22 for token in tokens)

    resolved = client.get("/resolve", headers=auth(), params={"t": batch["jars"][0]["scan_token"]})
    assert resolved.status_code == 200
    assert resolved.json()["kind"] == "jar"
    assert resolved.json()["jar_id"] == "AC-20260821-01-J001"

    illegal = client.post("/events", headers=auth(), json={
        "batch_id": "AC-20260821-01", "jar_id": "AC-20260821-01-J001", "to_stage": "fruiting",
        "operator": "Aman", "client_event_id": "illegal-001",
    })
    assert illegal.status_code == 409
    forced = client.post("/events", headers=auth(), json={
        "batch_id": "AC-20260821-01", "jar_id": "AC-20260821-01-J001", "to_stage": "fruiting",
        "operator": "Aman", "force": True, "client_event_id": "force-001",
    })
    assert forced.status_code == 200, forced.text
    assert forced.json()["forced"] == 1

    incomplete = client.post("/events/transfer", headers=auth(), json={"batch_id": "AC-20260821-01"})
    assert incomplete.status_code == 422

    jar_2 = "AC-20260821-01-J002"
    for stage, event_id in (("inoculated", "e-inoc"), ("dark_incubation", "e-dark")):
        response = client.post("/events", headers=auth(), json={
            "ts": "2026-08-22T09:00:00+05:30", "batch_id": "AC-20260821-01", "jar_id": jar_2,
            "to_stage": stage, "operator": "Aman", "client_event_id": event_id,
        })
        assert response.status_code == 200, response.text
    transfer = client.post("/events/transfer", headers=auth(), json={
        "jar_ids": [jar_2], "ts": "2026-08-23T09:00:00+05:30", "operator": "Aman",
        "source_location": "dark_room", "dest_chamber": "light_room", "rack_shelf": "F1-R2-S3",
        "reason": "scheduled transfer", "colonization_pct": 95, "moisture_level": "ideal",
        "env": {"temp_c": 20.0, "rh_pct": 80.0, "co2_ppm": 800}, "client_event_id": "transfer-001",
    })
    assert transfer.status_code == 200, transfer.text

    snapshot = client.post("/env/snapshot", headers=auth(), json={
        "ts": "2026-08-23T10:00:00+05:30", "batch_id": "AC-20260821-01", "jar_id": jar_2,
        "chamber": "light_room", "temp_c": "unknown", "rh_pct": 65, "client_event_id": "snapshot-001",
    })
    assert snapshot.status_code == 200, snapshot.text
    from app.db import get_db
    with get_db() as db:
        stored = dict(db.execute("SELECT temp_c, temp_c_src FROM env_snapshots WHERE id=?", (snapshot.json()["id"],)).fetchone())
    assert stored == {"temp_c": None, "temp_c_src": "missing"}

    harvest = client.post("/harvest", headers=auth(), json={
        "ts": "2026-09-01T12:00:00+05:30", "batch_id": "AC-20260821-01", "dry_weight_g": 25.0,
        "operator": "Aman", "client_event_id": "harvest-001",
    })
    assert harvest.status_code == 200, harvest.text
    with get_db() as db:
        be = db.execute("SELECT biological_efficiency_pct FROM harvest_yield WHERE id=?", (harvest.json()["id"],)).fetchone()[0]
    assert be is None

    for table in ("batch_master", "jar_master", "stage_events", "observations", "env_stage_summary", "harvest_yield", "photos", "interventions"):
        exported = client.get(f"/export/{table}.csv", headers=auth())
        assert exported.status_code == 200, (table, exported.text)
        assert exported.headers["content-type"].startswith("text/csv")
        assert exported.text.startswith("id,") or table in {"batch_master", "jar_master"}


def test_autoclave_defaults_and_lineage(client: TestClient) -> None:
    defaults = client.get("/autoclave/defaults", headers=auth())
    assert defaults.status_code == 200
    assert defaults.json()["jars"] == {"temperature_c": 121.0, "pressure_psi": 15.0, "duration_min": 120.0}
    assert defaults.json()["liquid_culture"]["duration_min"] == 30.0

    cycle = client.post("/autoclave", headers=auth(), json={
        "ts": "2026-08-28T10:00:00+05:30", "material_type": "jars", "quantity": 12,
        "material_name": "R-2026.3 jars", "operator": "Aman", "client_event_id": "auto-default-001",
    })
    assert cycle.status_code == 200, cycle.text
    assert cycle.json()["parameters"] == {"temperature_c": 121.0, "pressure_psi": 15.0, "duration_min": 120.0}
    assert cycle.json()["parameters_source"] == "default"
    assert set(cycle.json()["parameter_sources"].values()) == {"default"}

    override = client.post("/autoclave", headers=auth(), json={
        "ts": "2026-08-28T11:00:00+05:30", "material_type": "liquid_culture", "quantity": 3,
        "temperature_c": 118, "pressure_psi": 12, "duration_min": 45, "operator": "Aman",
    })
    assert override.status_code == 200, override.text
    assert override.json()["parameters_source"] == "manual"
    assert override.json()["parameters"]["duration_min"] == 45.0
    assert set(override.json()["parameter_sources"].values()) == {"manual"}

    culture = client.post("/cultures", headers=auth(), json={
        "culture_id": "LC-001", "created_ts": "2026-08-28T12:00:00+05:30", "volume_ml": 500,
        "operator": "Aman", "client_event_id": "culture-001",
    })
    assert culture.status_code == 200, culture.text
    linked = client.post("/lineage", headers=auth(), json={
        "ts": "2026-08-28T13:00:00+05:30", "source_type": "culture", "source_id": "LC-001",
        "destination_type": "batch", "destination_id": "AC-20260828-01", "relationship": "inoculated_jars",
        "quantity": 12, "unit": "jars", "operator": "Aman", "client_event_id": "lineage-001",
    })
    assert linked.status_code == 200, linked.text
    usage = client.get("/cultures/LC-001/usage", headers=auth())
    assert usage.status_code == 200
    assert usage.json()["usage"][0]["destination_id"] == "AC-20260828-01"

    summary = client.get("/dashboard/summary", headers=auth())
    assert summary.status_code == 200
    assert summary.json()["active_cultures"] == 1
    assert {row["event_type"] for row in summary.json()["recent_activity"]} >= {"autoclaved", "culture_created", "lineage_linked"}
