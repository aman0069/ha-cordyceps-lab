"""SQLite setup for the Cordyceps Lab Data Service."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterator

DATA_DIR = Path(os.getenv("LDS_DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "cordyceps.db"
SENSOR_DB_PATH = DATA_DIR / "cordyceps_sensors.db"

MAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS batch_master (
    batch_id TEXT PRIMARY KEY, scan_token TEXT UNIQUE NOT NULL, created_ts TEXT NOT NULL,
    parent_batch_id TEXT REFERENCES batch_master(batch_id), strain TEXT NOT NULL,
    culture_generation TEXT, culture_source TEXT, inoculation_method TEXT,
    recipe_version TEXT NOT NULL, rice_g_per_jar REAL, broth_ml_per_jar REAL,
    water_source TEXT, fill_weight_g REAL, jar_type TEXT, lid_filter_type TEXT,
    sterilization_profile TEXT, autoclave_id TEXT, autoclave_temp_c REAL,
    autoclave_pressure_psi REAL, autoclave_hold_min INTEGER, autoclave_cycle_result TEXT,
    autoclave_deviations TEXT, jar_count_planned INTEGER, current_stage TEXT NOT NULL,
    current_location TEXT, notes TEXT, operator TEXT,
    data_source TEXT CHECK(data_source IN ('manual','qr_scan','sensor','import','system'))
);
CREATE TABLE IF NOT EXISTS jar_master (
    jar_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batch_master(batch_id),
    scan_token TEXT UNIQUE NOT NULL, jar_index INTEGER NOT NULL, current_stage TEXT NOT NULL,
    current_location TEXT, rack_shelf TEXT, fill_weight_g REAL, status TEXT,
    created_ts TEXT NOT NULL, notes TEXT
);
CREATE TABLE IF NOT EXISTS ingredient_lots (
    id INTEGER PRIMARY KEY, batch_id TEXT REFERENCES batch_master(batch_id), ingredient TEXT,
    lot_number TEXT, quantity REAL, unit TEXT, supplier TEXT, expiry TEXT, ts TEXT NOT NULL,
    operator TEXT, data_source TEXT CHECK(data_source IN ('manual','qr_scan','sensor','import','system'))
);
CREATE TABLE IF NOT EXISTS stage_events (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, batch_id TEXT REFERENCES batch_master(batch_id),
    jar_id TEXT REFERENCES jar_master(jar_id), from_stage TEXT, to_stage TEXT, action TEXT,
    source_location TEXT, dest_location TEXT, rack_shelf TEXT, reason TEXT,
    colonization_pct REAL, moisture_level TEXT,
    env_snapshot_id INTEGER REFERENCES env_snapshots(id), equipment_id TEXT, notes TEXT,
    operator TEXT, data_source TEXT CHECK(data_source IN ('manual','qr_scan','sensor','import','system')),
    forced INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS env_snapshots (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, batch_id TEXT REFERENCES batch_master(batch_id),
    jar_id TEXT REFERENCES jar_master(jar_id), chamber TEXT,
    temp_c REAL, temp_c_src TEXT, rh_pct REAL, rh_pct_src TEXT,
    co2_ppm REAL, co2_ppm_src TEXT, vpd_kpa REAL, vpd_kpa_src TEXT,
    light_state TEXT, light_state_src TEXT, lux REAL, lux_src TEXT,
    photoperiod TEXT, photoperiod_src TEXT, door_state TEXT, door_state_src TEXT,
    fan_state TEXT, fan_state_src TEXT, humidifier_state TEXT, humidifier_state_src TEXT,
    exhaust_state TEXT, exhaust_state_src TEXT, airflow_ms REAL, airflow_ms_src TEXT,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS env_stage_summary (
    id INTEGER PRIMARY KEY, batch_id TEXT REFERENCES batch_master(batch_id),
    jar_id TEXT REFERENCES jar_master(jar_id), stage TEXT, chamber TEXT, start_ts TEXT,
    end_ts TEXT, duration_h REAL, metric TEXT, min REAL, max REAL, avg REAL, stdev REAL,
    p10 REAL, p90 REAL, n_samples INTEGER, n_expected INTEGER, completeness REAL,
    computed_ts TEXT, data_source TEXT CHECK(data_source IN ('manual','qr_scan','sensor','import','system'))
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, batch_id TEXT REFERENCES batch_master(batch_id),
    jar_id TEXT REFERENCES jar_master(jar_id), stage TEXT, colonization_pct REAL,
    mycelial_density TEXT, mycelial_color TEXT, condensation_level TEXT,
    substrate_dryness TEXT, contamination_status TEXT, contamination_type TEXT,
    primordia_count INTEGER, fruiting_body_count INTEGER, avg_height_mm REAL,
    morphology_score INTEGER, photo_id INTEGER REFERENCES photos(id), notes TEXT, operator TEXT,
    data_source TEXT CHECK(data_source IN ('manual','qr_scan','sensor','import','system')),
    env_snapshot_id INTEGER REFERENCES env_snapshots(id)
);
CREATE TABLE IF NOT EXISTS interventions (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, batch_id TEXT REFERENCES batch_master(batch_id),
    jar_id TEXT REFERENCES jar_master(jar_id), intervention_type TEXT, detail TEXT,
    setpoint_before TEXT, setpoint_after TEXT, equipment_id TEXT, duration_min REAL,
    notes TEXT, operator TEXT,
    data_source TEXT CHECK(data_source IN ('manual','qr_scan','sensor','import','system')),
    env_snapshot_id INTEGER REFERENCES env_snapshots(id)
);
CREATE TABLE IF NOT EXISTS harvest_yield (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, batch_id TEXT REFERENCES batch_master(batch_id),
    jar_id TEXT REFERENCES jar_master(jar_id), fresh_weight_g REAL, dry_weight_g REAL,
    substrate_dry_g REAL, biological_efficiency_pct REAL, usable_jars INTEGER,
    rejected_jars INTEGER, contaminated_jars INTEGER, grade TEXT, drying_method TEXT,
    drying_temp_c REAL, drying_hours REAL, packaging_date TEXT, package_type TEXT,
    notes TEXT, operator TEXT,
    data_source TEXT CHECK(data_source IN ('manual','qr_scan','sensor','import','system'))
);
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, batch_id TEXT REFERENCES batch_master(batch_id),
    jar_id TEXT REFERENCES jar_master(jar_id), stage TEXT, file_path TEXT, thumb_path TEXT,
    caption TEXT, operator TEXT,
    data_source TEXT CHECK(data_source IN ('manual','qr_scan','sensor','import','system'))
);
CREATE TABLE IF NOT EXISTS costs (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, batch_id TEXT REFERENCES batch_master(batch_id),
    category TEXT, item TEXT, quantity REAL, unit TEXT, unit_cost_inr REAL, total_inr REAL,
    labor_minutes REAL, kwh REAL, equipment_id TEXT, notes TEXT, operator TEXT,
    data_source TEXT CHECK(data_source IN ('manual','qr_scan','sensor','import','system'))
);
CREATE TABLE IF NOT EXISTS client_event_dedupe (
    client_event_id TEXT PRIMARY KEY, endpoint TEXT NOT NULL, response_json TEXT NOT NULL,
    created_ts TEXT NOT NULL
);
DROP VIEW IF EXISTS stage_durations;
CREATE VIEW stage_durations AS
WITH events AS (
  SELECT batch_id, jar_id,
    MIN(CASE WHEN to_stage = 'autoclaved' THEN ts END) AS autoclaved_ts,
    MIN(CASE WHEN to_stage = 'inoculated' THEN ts END) AS inoculated_ts,
    MIN(CASE WHEN to_stage = 'transferred_to_light' THEN ts END) AS transferred_ts,
    MIN(CASE WHEN to_stage = 'primordia_observed' THEN ts END) AS primordia_ts,
    MIN(CASE WHEN to_stage = 'harvested' THEN ts END) AS harvested_ts
  FROM stage_events GROUP BY batch_id, jar_id
)
SELECT batch_id, jar_id,
  CASE WHEN autoclaved_ts IS NOT NULL AND inoculated_ts IS NOT NULL
       THEN (julianday(inoculated_ts)-julianday(autoclaved_ts))*24 END AS h_autoclave_to_inoculation,
  CASE WHEN inoculated_ts IS NOT NULL AND transferred_ts IS NOT NULL
       THEN (julianday(transferred_ts)-julianday(inoculated_ts))*24 END AS h_inoculation_to_transfer,
  CASE WHEN transferred_ts IS NOT NULL AND primordia_ts IS NOT NULL
       THEN (julianday(primordia_ts)-julianday(transferred_ts))*24 END AS h_transfer_to_primordia,
  CASE WHEN primordia_ts IS NOT NULL AND harvested_ts IS NOT NULL
       THEN (julianday(harvested_ts)-julianday(primordia_ts))*24 END AS h_primordia_to_harvest,
  CASE WHEN autoclaved_ts IS NOT NULL AND harvested_ts IS NOT NULL
       THEN (julianday(harvested_ts)-julianday(autoclaved_ts))*24 END AS h_total_cycle
FROM events;
"""

SENSOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_sensor_log (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, chamber TEXT, entity_id TEXT,
    metric TEXT, value REAL, unit TEXT
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def get_db() -> sqlite3.Connection:
    """Return a configured connection to the LDS transactional database."""
    return _connect(DB_PATH)


def get_sensor_db() -> sqlite3.Connection:
    """Return a configured connection to the separate high-volume sensor database."""
    return _connect(SENSOR_DB_PATH)


def init_db() -> None:
    """Create the contract schema without altering existing data."""
    with get_db() as connection:
        connection.executescript(MAIN_SCHEMA)
    with get_sensor_db() as connection:
        connection.executescript(SENSOR_SCHEMA)
