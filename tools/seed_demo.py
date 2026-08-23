#!/usr/bin/env python3
"""Create a clearly synthetic Cordyceps Lab v2 SQLite database for tool tests."""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


IST = timezone(timedelta(hours=5, minutes=30))


def iso(value: datetime) -> str:
    return value.astimezone(IST).isoformat(timespec="seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/home/user/workspace/cordyceps-lab-v2/samples/cordyceps_demo.db"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(args.output)
    cur = connection.cursor()
    cur.executescript(
        """
        DROP TABLE IF EXISTS batch_master;
        DROP TABLE IF EXISTS jar_master;
        DROP TABLE IF EXISTS stage_events;
        DROP TABLE IF EXISTS env_stage_summary;
        DROP TABLE IF EXISTS observations;
        DROP TABLE IF EXISTS harvest_yield;
        DROP TABLE IF EXISTS photos;
        DROP TABLE IF EXISTS interventions;

        CREATE TABLE batch_master (
          batch_id TEXT PRIMARY KEY, scan_token TEXT, created_ts TEXT, strain TEXT,
          culture_generation TEXT, recipe_version TEXT, rice_g_per_jar REAL,
          broth_ml_per_jar REAL, jar_count_planned INTEGER, current_stage TEXT,
          current_location TEXT, notes TEXT, operator TEXT, data_source TEXT
        );
        CREATE TABLE jar_master (
          jar_id TEXT PRIMARY KEY, batch_id TEXT, scan_token TEXT, jar_index INTEGER,
          current_stage TEXT, current_location TEXT, rack_shelf TEXT, status TEXT,
          created_ts TEXT, notes TEXT
        );
        CREATE TABLE stage_events (
          id INTEGER PRIMARY KEY, ts TEXT, batch_id TEXT, jar_id TEXT, from_stage TEXT,
          to_stage TEXT, action TEXT, source_location TEXT, dest_location TEXT,
          rack_shelf TEXT, reason TEXT, colonization_pct REAL, moisture_level TEXT,
          operator TEXT, data_source TEXT
        );
        CREATE TABLE env_stage_summary (
          id INTEGER PRIMARY KEY, batch_id TEXT, jar_id TEXT, stage TEXT, chamber TEXT,
          start_ts TEXT, end_ts TEXT, duration_h REAL, metric TEXT, min REAL, max REAL,
          avg REAL, stdev REAL, p10 REAL, p90 REAL, n_samples INTEGER, n_expected INTEGER,
          completeness REAL, computed_ts TEXT, data_source TEXT
        );
        CREATE TABLE observations (
          id INTEGER PRIMARY KEY, ts TEXT, batch_id TEXT, jar_id TEXT, stage TEXT,
          colonization_pct REAL, contamination_status TEXT, contamination_type TEXT,
          moisture_level TEXT, notes TEXT, operator TEXT, data_source TEXT
        );
        CREATE TABLE harvest_yield (
          id INTEGER PRIMARY KEY, ts TEXT, batch_id TEXT, jar_id TEXT, fresh_weight_g REAL,
          dry_weight_g REAL, substrate_dry_g REAL, biological_efficiency_pct REAL,
          usable_jars INTEGER, rejected_jars INTEGER, contaminated_jars INTEGER,
          grade TEXT, notes TEXT, operator TEXT, data_source TEXT
        );
        CREATE TABLE photos (
          id INTEGER PRIMARY KEY, ts TEXT, batch_id TEXT, jar_id TEXT, stage TEXT,
          file_path TEXT, thumb_path TEXT, caption TEXT, operator TEXT, data_source TEXT
        );
        CREATE TABLE interventions (
          id INTEGER PRIMARY KEY, ts TEXT, batch_id TEXT, jar_id TEXT,
          intervention_type TEXT, detail TEXT, notes TEXT, operator TEXT, data_source TEXT
        );
        """
    )

    rng = random.Random(20260821)
    event_id = env_id = obs_id = yield_id = photo_id = intervention_id = 1
    base = datetime(2026, 3, 1, 9, 0, tzinfo=IST)
    for idx in range(12):
        autoclave = base + timedelta(days=idx * 6)
        batch_id = f"AC-{autoclave:%Y%m%d}-01"
        strain = "CM-Comm-A" if idx % 3 else "CM-Delhi-B"
        recipe = "R-2026.3" if idx < 8 else "R-2026.4"
        chamber = "dark_room" if idx % 2 else "fruit_1"
        planned = 20
        cur.execute(
            "INSERT INTO batch_master VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                f"demo_batch_token_{idx:02d}",
                iso(autoclave),
                strain,
                "G2",
                recipe,
                None if idx == 10 else 40.0,
                22.0,
                planned,
                "harvested" if idx != 11 else "fruiting",
                chamber,
                "" if idx in (2, 7) else "Synthetic demo record",
                "demo",
                "import",
            ),
        )
        for jar in range(1, planned + 1):
            cur.execute(
                "INSERT INTO jar_master VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    f"{batch_id}-J{jar:03d}",
                    batch_id,
                    f"demo_jar_{idx:02d}_{jar:03d}",
                    jar,
                    "harvested" if idx != 11 else "fruiting",
                    chamber,
                    f"F1-R{idx % 3 + 1}-S{jar % 4 + 1}",
                    "active" if idx == 11 else "harvested",
                    iso(autoclave),
                    None,
                ),
            )
        inoc = autoclave + timedelta(days=1)
        transfer_days = 13 + (idx % 6) + rng.uniform(-0.4, 0.4)
        transfer = inoc + timedelta(days=transfer_days)
        primordia = transfer + timedelta(days=8 + idx % 3)
        harvest = primordia + timedelta(days=15 + idx % 4)
        events = [
            (autoclave, None, "autoclaved", "autoclave_logging", None),
            (inoc, "autoclaved", "inoculated", "inoculation", 0.0),
        ]
        # Deliberate missing endpoints for transfer-age completeness testing.
        if idx != 10:
            events.append((transfer, "dark_incubation", "transferred_to_light", "transfer_dark_to_light", 80.0))
        if idx not in (9, 10):
            events.append((primordia, "transferred_to_light", "primordia_observed", "visual_inspection", 90.0))
        if idx != 11:
            events.append((harvest, "fruiting", "harvested", "harvest", 100.0))
        for moment, before, after, action, colonization in events:
            cur.execute(
                "INSERT INTO stage_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    iso(moment),
                    batch_id,
                    None,
                    before,
                    after,
                    action,
                    "dark_room" if action == "transfer_dark_to_light" else "lab",
                    chamber if action == "transfer_dark_to_light" else None,
                    f"F1-R{idx % 3 + 1}-S1",
                    "scheduled review" if action == "transfer_dark_to_light" else None,
                    colonization,
                    "ideal" if colonization else None,
                    "demo",
                    "import",
                ),
            )
            event_id += 1

        temp = 19.0 + idx * 0.32 + rng.uniform(-0.2, 0.2)
        rh = 69.0 + (idx % 5) * 2.1 + rng.uniform(-0.8, 0.8)
        for metric, value, skip in (
            ("temp_c", temp, idx in (1, 8)),
            ("rh_pct", rh, idx in (3, 9, 11)),
            # Exactly four complete observations make this pair suppressed.
            ("co2_ppm", 750 + idx * 45, idx not in (0, 2, 5, 7)),
        ):
            if skip:
                continue
            stage = "transferred_to_light" if metric == "co2_ppm" else "dark_incubation"
            cur.execute(
                "INSERT INTO env_stage_summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    env_id,
                    batch_id,
                    None,
                    stage,
                    chamber,
                    iso(inoc),
                    iso(transfer),
                    transfer_days * 24,
                    metric,
                    value - 0.7,
                    value + 0.7,
                    value,
                    0.28,
                    value - 0.4,
                    value + 0.4,
                    112 if idx != 6 else 35,
                    120,
                    112 / 120 if idx != 6 else 35 / 120,
                    iso(harvest),
                    "system",
                ),
            )
            env_id += 1

        confirmed = idx in (2, 7, 9)
        cur.execute(
            "INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                obs_id,
                iso(transfer + timedelta(days=5)),
                batch_id,
                None,
                "dark_incubation",
                70.0 if idx != 4 else None,
                "confirmed" if confirmed else ("suspected" if idx == 5 else "none"),
                "trichoderma" if confirmed else "none",
                "ideal",
                None if idx in (6, 8) else "Synthetic visual observation",
                "demo",
                "import",
            ),
        )
        obs_id += 1

        if idx not in (6, 11):
            dry = round(12.5 + temp * 0.85 - transfer_days * 0.32 - (3.0 if confirmed else 0) + rng.uniform(-0.7, 0.7), 2)
            contam_jars = 3 if confirmed else (1 if idx == 5 else 0)
            substrate = 20 * 40.0
            cur.execute(
                "INSERT INTO harvest_yield VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    yield_id,
                    iso(harvest),
                    batch_id,
                    None,
                    dry * 3.5,
                    dry,
                    substrate,
                    100 * dry / substrate,
                    planned - contam_jars,
                    0,
                    contam_jars,
                    "A" if dry > 26 else "B",
                    None if idx == 4 else "Synthetic harvest",
                    "demo",
                    "import",
                ),
            )
            yield_id += 1
        if idx % 2 == 0:
            cur.execute(
                "INSERT INTO photos VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    photo_id,
                    iso(primordia),
                    batch_id,
                    None,
                    "primordia_observed",
                    f"/demo/{batch_id}.jpg",
                    f"/demo/{batch_id}_thumb.jpg",
                    "Synthetic photo",
                    "demo",
                    "import",
                ),
            )
            photo_id += 1
        if idx in (3, 8):
            cur.execute(
                "INSERT INTO interventions VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    intervention_id,
                    iso(transfer + timedelta(days=3)),
                    batch_id,
                    None,
                    "cleaning",
                    "Synthetic logging entry",
                    None,
                    "demo",
                    "import",
                ),
            )
            intervention_id += 1
    connection.commit()
    connection.close()
    print(f"Created synthetic demo database with 12 batches: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
