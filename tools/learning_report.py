#!/usr/bin/env python3
"""Generate a Contract §7 correlation-only weekly learning report."""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import NormalDist, median
from typing import Any, Iterable


# The first six entries are Contract §7's exact prohibited phrases. The
# additions keep generated prose observational rather than directional.
FORBIDDEN_WORDS = [
    "causes",
    "caused by",
    "because of",
    "proves",
    "will increase",
    "guarantees",
    "leads to",
    "results in",
    "drives",
    "determines",
    "impacts",
    "influences",
    "improves",
    "worsens",
    "produces",
    "due to",
    "therefore",
    "thus",
]

META_COLUMNS = {
    "id", "batch_id", "jar_id", "scan_token", "ts", "created_ts", "start_ts",
    "end_ts", "computed_ts", "operator", "data_source", "raw_json", "file_path",
    "thumb_path", "notes", "caption",
}

CONFUNDER_LOOKUP = {
    ("dark_incubation_avg_temp_c", "dry_weight_g"): [
        "strain", "recipe version", "transfer timing", "dark-incubation RH"
    ],
    ("dark_incubation_avg_rh_pct", "dry_weight_g"): [
        "strain", "recipe version", "transfer timing", "sensor completeness"
    ],
    ("transfer_age_h", "dry_weight_g"): [
        "strain", "recipe version", "dark-incubation temperature", "colonization score"
    ],
    ("dark_incubation_avg_temp_c", "contamination_pct"): [
        "strain", "recipe version", "handling sequence", "sensor completeness"
    ],
    ("light_stage_avg_co2_ppm", "dry_weight_g"): [
        "strain", "recipe version", "transfer timing", "light-stage completeness"
    ],
}

VARIABLE_LABELS = {
    "dark_incubation_avg_temp_c": "dark-incubation average temperature (°C)",
    "dark_incubation_avg_rh_pct": "dark-incubation average RH (%)",
    "transfer_age_h": "inoculation-to-transfer duration (h)",
    "light_stage_avg_co2_ppm": "light-stage average CO₂ (ppm)",
    "dry_weight_g": "dry weight (g)",
    "contamination_pct": "contaminated jars (%)",
}


def clean_table_name(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    aliases = {
        "batch_master": "batch_master",
        "batch_master_export": "batch_master",
        "batch": "batch_master",
        "jar_master": "jar_master",
        "stage_events": "stage_events",
        "observations": "observations",
        "environmental_stage_summaries": "env_stage_summary",
        "env_stage_summary": "env_stage_summary",
        "harvest_yield": "harvest_yield",
        "harvest_yield_export": "harvest_yield",
        "photos": "photos",
        "interventions": "interventions",
    }
    return aliases.get(key, key)


def load_sqlite(path: Path) -> dict[str, list[dict[str, Any]]]:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        names = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            name: [dict(row) for row in con.execute(f'SELECT * FROM "{name}"')]
            for name in names
        }
    finally:
        con.close()


def load_csv_exports(path: Path) -> dict[str, list[dict[str, Any]]]:
    files = list(path.glob("*.csv")) if path.is_dir() else [path]
    if not files:
        raise ValueError("No CSV exports found.")
    result: dict[str, list[dict[str, Any]]] = {}
    for file in files:
        if file.suffix.lower() != ".csv":
            continue
        with file.open(newline="", encoding="utf-8-sig") as handle:
            result[clean_table_name(file.stem)] = list(csv.DictReader(handle))
    if not result:
        raise ValueError("No readable CSV exports found.")
    return result


def load_input(path: Path) -> dict[str, list[dict[str, Any]]]:
    if path.is_dir() or path.suffix.lower() == ".csv":
        return load_csv_exports(path)
    return load_sqlite(path)


def nonempty(value: Any) -> bool:
    return value is not None and str(value).strip().lower() not in {"", "unknown", "unavailable", "none", "null"}


def number(value: Any) -> float | None:
    if not nonempty(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_ts(value: Any) -> datetime | None:
    if not nonempty(value):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def table_date_range(rows: list[dict[str, Any]]) -> tuple[str, str] | None:
    candidates: list[str] = []
    for row in rows:
        for key in ("ts", "created_ts", "start_ts", "end_ts", "computed_ts"):
            if nonempty(row.get(key)):
                candidates.append(str(row[key]))
    if not candidates:
        return None
    return min(candidates), max(candidates)


def data_inventory(tables: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines = ["## Data inventory", "", "| Table | Rows | Date range |", "|---|---:|---|"]
    for name, rows in sorted(tables.items()):
        dates = table_date_range(rows)
        date_text = f"{dates[0]} → {dates[1]}" if dates else "No timestamp field/value available"
        lines.append(f"| `{name}` | {len(rows)} | {date_text} |")
    return lines


def batch_ids(tables: dict[str, list[dict[str, Any]]]) -> list[str]:
    ids = {
        str(row["batch_id"])
        for rows in tables.values()
        for row in rows
        if nonempty(row.get("batch_id"))
    }
    return sorted(ids)


def completeness_by_batch(tables: dict[str, list[dict[str, Any]]]) -> dict[str, tuple[int, int, float | None]]:
    results: dict[str, tuple[int, int, float | None]] = {}
    for batch_id in batch_ids(tables):
        present = total = 0
        for table_name, rows in tables.items():
            matched = [r for r in rows if str(r.get("batch_id", "")) == batch_id]
            for row in matched:
                for key, value in row.items():
                    if key.lower() in META_COLUMNS or key.lower().endswith("_src"):
                        continue
                    total += 1
                    present += int(nonempty(value))
        results[batch_id] = (present, total, (100 * present / total if total else None))
    return results


def stage_event_map(rows: list[dict[str, Any]], batch_id: str) -> dict[str, datetime]:
    wanted = {
        "inoculated": {"inoculation"},
        "transferred_to_light": {"transfer_dark_to_light"},
        "primordia_observed": {"visual_inspection"},
        "harvested": {"harvest"},
    }
    found: dict[str, datetime] = {}
    for row in rows:
        if str(row.get("batch_id", "")) != batch_id:
            continue
        stage = str(row.get("to_stage") or "")
        action = str(row.get("action") or "")
        ts = parse_ts(row.get("ts"))
        for name, actions in wanted.items():
            if ts and (stage == name or action in actions):
                if name not in found or ts < found[name]:
                    found[name] = ts
    return found


def average_env(rows: list[dict[str, Any]], batch_id: str, stage: str, metric: str) -> float | None:
    values = [
        number(row.get("avg"))
        for row in rows
        if str(row.get("batch_id", "")) == batch_id
        and str(row.get("stage", "")) == stage
        and str(row.get("metric", "")) == metric
        and number(row.get("avg")) is not None
    ]
    return sum(values) / len(values) if values else None


def batch_metrics(tables: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, float | None]]:
    metrics: dict[str, dict[str, float | None]] = {}
    yields = tables.get("harvest_yield", [])
    batches = tables.get("batch_master", [])
    events = tables.get("stage_events", [])
    env = tables.get("env_stage_summary", [])
    for batch_id in batch_ids(tables):
        event_map = stage_event_map(events, batch_id)
        transfer_age = None
        if event_map.get("inoculated") and event_map.get("transferred_to_light"):
            transfer_age = (event_map["transferred_to_light"] - event_map["inoculated"]).total_seconds() / 3600
        dry_values = [
            number(row.get("dry_weight_g"))
            for row in yields
            if str(row.get("batch_id", "")) == batch_id and number(row.get("dry_weight_g")) is not None
        ]
        batch_row = next((r for r in batches if str(r.get("batch_id", "")) == batch_id), {})
        planned = number(batch_row.get("jar_count_planned"))
        contam_values = [
            number(row.get("contaminated_jars"))
            for row in yields
            if str(row.get("batch_id", "")) == batch_id and number(row.get("contaminated_jars")) is not None
        ]
        contamination = None
        if planned and contam_values:
            contamination = 100 * sum(contam_values) / planned
        metrics[batch_id] = {
            "dark_incubation_avg_temp_c": average_env(env, batch_id, "dark_incubation", "temp_c"),
            "dark_incubation_avg_rh_pct": average_env(env, batch_id, "dark_incubation", "rh_pct"),
            "light_stage_avg_co2_ppm": average_env(env, batch_id, "transferred_to_light", "co2_ppm"),
            "transfer_age_h": transfer_age,
            "dry_weight_g": sum(dry_values) if dry_values else None,
            "contamination_pct": contamination,
        }
    return metrics


def rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    output = [0.0] * len(values)
    position = 0
    while position < len(indexed):
        end = position + 1
        while end < len(indexed) and indexed[end][1] == indexed[position][1]:
            end += 1
        average_rank = (position + 1 + end) / 2
        for original_index, _ in indexed[position:end]:
            output[original_index] = average_rank
        position = end
    return output


def pearson(x: list[float], y: list[float]) -> float:
    x_mean, y_mean = sum(x) / len(x), sum(y) / len(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
    x_ss = sum((a - x_mean) ** 2 for a in x)
    y_ss = sum((b - y_mean) ** 2 for b in y)
    if x_ss == 0 or y_ss == 0:
        return float("nan")
    return numerator / math.sqrt(x_ss * y_ss)


def spearman_with_p(x: list[float], y: list[float]) -> tuple[float, float]:
    try:
        from scipy.stats import spearmanr  # type: ignore

        statistic = spearmanr(x, y)
        return float(statistic.statistic), float(statistic.pvalue)
    except ImportError:
        rho = pearson(rank(x), rank(y))
        if math.isnan(rho):
            return rho, float("nan")
        rng = random.Random(20260821)
        observed = abs(rho)
        count = 0
        shuffled = list(y)
        rounds = 9999
        for _ in range(rounds):
            rng.shuffle(shuffled)
            if abs(pearson(rank(x), rank(shuffled))) >= observed:
                count += 1
        return rho, (count + 1) / (rounds + 1)


def correlation_rows(metrics: dict[str, dict[str, float | None]]) -> list[dict[str, Any]]:
    pairs = list(CONFUNDER_LOOKUP)
    rows = []
    total = len(metrics)
    for x_name, y_name in pairs:
        x_values = [m[x_name] for m in metrics.values()]
        y_values = [m[y_name] for m in metrics.values()]
        paired = [(m[x_name], m[y_name]) for m in metrics.values() if m[x_name] is not None and m[y_name] is not None]
        x = [float(pair[0]) for pair in paired]
        y = [float(pair[1]) for pair in paired]
        rho, p_value = spearman_with_p(x, y) if len(x) >= 2 else (float("nan"), float("nan"))
        rows.append(
            {
                "x": x_name,
                "y": y_name,
                "n": len(paired),
                "rho": rho,
                "p": p_value,
                "x_missing": 100 * sum(value is None for value in x_values) / total if total else float("nan"),
                "y_missing": 100 * sum(value is None for value in y_values) / total if total else float("nan"),
                "confounders": CONFUNDER_LOOKUP[(x_name, y_name)],
            }
        )
    return rows


def format_p(value: float) -> str:
    return "not estimable" if math.isnan(value) else f"{value:.4f}"


def power_per_arm(alpha: float = 0.05, power: float = 0.80, standardized_difference: float = 0.80) -> int:
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1 - alpha / 2)
    z_power = normal.inv_cdf(power)
    return math.ceil(2 * ((z_alpha + z_power) / standardized_difference) ** 2)


def observed_cycle_days(tables: dict[str, list[dict[str, Any]]]) -> float | None:
    values = []
    for batch_id in batch_ids(tables):
        events = stage_event_map(tables.get("stage_events", []), batch_id)
        if events.get("inoculated") and events.get("harvested"):
            values.append((events["harvested"] - events["inoculated"]).total_seconds() / 86400)
    return median(values) if values else None


def experiment_card(candidate: dict[str, Any], tables: dict[str, list[dict[str, Any]]]) -> list[str]:
    variable = VARIABLE_LABELS[candidate["x"]]
    outcome = VARIABLE_LABELS[candidate["y"]]
    sample = power_per_arm()
    duration = observed_cycle_days(tables)
    duration_text = (
        f"{math.ceil(duration / 7)} weeks per arm, based on the median observed inoculation-to-harvest duration."
        if duration is not None
        else "Set after reviewing a complete observed cycle; no duration can be estimated from available records."
    )
    return [
        "### Proposed experiment card — association follow-up",
        f"- **Hypothesis:** The observed association between {variable} and {outcome} merits a controlled test; it is not established.",
        f"- **one_variable_changed:** {variable}",
        "- **control_batch_requirement:** Concurrent control batches with the same strain, recipe version, jar type, planned jar count, and chamber allocation.",
        f"- **minimum_sample_size:** {sample} batches per arm ({sample * 2} total), simple two-arm estimate with α=0.05, 80% power, and standardized difference=0.80.",
        f"- **success_metric:** Batch-level {outcome}, recorded without zero-filling missing values.",
        f"- **duration_estimate:** {duration_text}",
        "- **risks:** Between-batch variation, contamination, incomplete sensor coverage, and unbalanced chamber allocation.",
        "- **approved_by_aman:** false",
        "- **Requires Aman's approval:** false",
    ]


def self_check(text: str) -> None:
    sentences = re.split(r"(?<=[.!?])(?:\s+|$)", text.lower())
    for sentence in sentences:
        for phrase in FORBIDDEN_WORDS:
            pattern = r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])"
            if re.search(pattern, sentence):
                raise RuntimeError(f"Forbidden causal language in generated sentence: {phrase!r}")


def build_report(tables: dict[str, list[dict[str, Any]],], source: Path) -> str:
    completeness = completeness_by_batch(tables)
    metrics = batch_metrics(tables)
    correlations = correlation_rows(metrics)
    lines = [
        "# Cordyceps Lab v2 — Weekly Learning Report",
        "",
        f"Input: `{source}`",
        "",
        "This report describes associations only. Hypotheses are unconfirmed, and missing values remain missing.",
        "",
    ]
    lines.extend(data_inventory(tables))
    lines.extend(["", "## Data completeness per batch", "", "| Batch ID | Observed / assessed fields | Completeness |", "|---|---:|---:|"])
    for batch_id, (present, total, score) in completeness.items():
        score_text = f"{score:.1f}%" if score is not None else "not assessed"
        lines.append(f"| `{batch_id}` | {present} / {total} | {score_text} |")

    lines.extend(["", "## Correlation scan", "", "All scan p-values are unadjusted. Each row is observational."])
    displayed = [row for row in correlations if row["n"] >= 5]
    if displayed:
        for row in displayed:
            label_x, label_y = VARIABLE_LABELS[row["x"]], VARIABLE_LABELS[row["y"]]
            confounders = "; ".join(row["confounders"])
            lines.extend(
                [
                    "",
                    f"### {label_x} ↔ {label_y}",
                    f"`n={row['n']}`; Spearman rho = {row['rho']:+.3f}; p = {format_p(row['p'])}; missing {label_x}: {row['x_missing']:.1f}%; missing {label_y}: {row['y_missing']:.1f}%.",
                    f"Possible confounders: {confounders}. The association is not established beyond these records.",
                ]
            )
    else:
        lines.append("No variable pair met the minimum n=5 display threshold.")

    lines.extend(["", "## Suppressed findings (n<5)", ""])
    suppressed = [row for row in correlations if row["n"] < 5]
    if suppressed:
        for row in suppressed:
            lines.append(
                f"- {VARIABLE_LABELS[row['x']]} ↔ {VARIABLE_LABELS[row['y']]}: `n={row['n']}`; suppressed and not presented as a correlation."
            )
    else:
        lines.append("- None.")

    lines.extend(["", "## Low-confidence findings", ""])
    low = [row for row in correlations if 5 <= row["n"] < 12]
    if low:
        for row in low:
            lines.append(
                f"- {VARIABLE_LABELS[row['x']]} ↔ {VARIABLE_LABELS[row['y']]} (`n={row['n']}`): **insufficient for inference**."
            )
    else:
        lines.append("- No displayed pair has n<12.")

    lines.extend(["", "## Hypotheses", ""])
    candidates = sorted(displayed, key=lambda row: abs(row["rho"]) if not math.isnan(row["rho"]) else -1, reverse=True)
    if candidates:
        for row in candidates[:3]:
            lines.append(
                f"- **Hypothesis:** {VARIABLE_LABELS[row['x']]} may be associated with {VARIABLE_LABELS[row['y']]} in a controlled follow-up; this is not established."
            )
    else:
        lines.append("- **Hypothesis:** Additional complete records may support a future controlled comparison; no association is presented now.")

    lines.extend(["", "## Proposed experiments", ""])
    if candidates:
        lines.extend(experiment_card(candidates[0], tables))
    else:
        lines.extend(
            [
                "### Proposed experiment card — data capture pilot",
                "- **Hypothesis:** A complete measurement protocol may support a future controlled comparison; this is not established.",
                "- **one_variable_changed:** Measurement protocol completeness",
                "- **control_batch_requirement:** Concurrent batches with unchanged strain, recipe version, jar type, chamber allocation, and planned jar count.",
                f"- **minimum_sample_size:** {power_per_arm()} batches per arm ({power_per_arm() * 2} total), simple two-arm estimate with α=0.05, 80% power, and standardized difference=0.80.",
                "- **success_metric:** Percentage of expected environmental samples present, with unavailable readings retained as missing.",
                "- **duration_estimate:** Set after reviewing a complete observed cycle; no duration can be estimated from available records.",
                "- **risks:** Missing readings, chamber allocation imbalance, data-entry variation, and contamination.",
                "- **approved_by_aman:** false",
                "- **Requires Aman's approval:** false",
            ]
        )
    lines.extend(["", "No setpoints have been changed. Nothing in this report is applied automatically.", ""])
    report = "\n".join(lines)
    self_check(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="LDS SQLite database path or a CSV export/file directory")
    parser.add_argument("--output", type=Path, required=True, help="Markdown report destination")
    args = parser.parse_args()
    tables = load_input(args.input)
    report = build_report(tables, args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Created {args.output}; self-check passed ({len(FORBIDDEN_WORDS)} forbidden phrases).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
