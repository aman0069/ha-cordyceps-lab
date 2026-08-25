"""FastAPI implementation of the Cordyceps Lab Data Service contract."""
from __future__ import annotations

import csv
import html
import io
import json
import math
import os
import sqlite3
import statistics
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from .db import DATA_DIR, get_db, get_sensor_db, init_db
from .ids import allocate_batch_id, is_valid_batch_id, is_valid_jar_id, mint_jar_id, mint_scan_token
from .nullsafe import coerce, vpd_kpa
from .stages import IllegalTransition, STAGES, allowed_actions, transition

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize persistent storage when the service starts."""
    init_db()
    yield


app = FastAPI(title="Cordyceps Lab Data Service", version="2.4.0", lifespan=lifespan)
security = HTTPBearer(auto_error=False)
SOURCE_VALUES = {"manual", "qr_scan", "sensor", "import", "system"}
EXPORT_TABLES = {
    "batch_master": "batch_master", "jar_master": "jar_master", "stage_events": "stage_events",
    "observations": "observations", "env_stage_summary": "env_stage_summary",
    "harvest_yield": "harvest_yield", "photos": "photos", "interventions": "interventions",
}


def now_iso() -> str:
    """Produce an ISO timestamp with an explicit offset."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def model_data(model: BaseModel, *, include_none: bool = False) -> dict[str, Any]:
    values = model.model_dump(exclude_none=not include_none)
    # Permit explicitly documented contract columns supplied as extra model fields.
    values.update(model.model_extra or {})
    return values


def require_auth(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> None:
    expected = os.getenv("LDS_TOKEN", "")
    if not expected or credentials is None or credentials.scheme.lower() != "bearer" or credentials.credentials != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")


def ui_value(values: dict[str, list[str]], key: str) -> str | None:
    value = values.get(key, [""])[0].strip()
    return value or None


def ui_float(values: dict[str, list[str]], key: str) -> float | None:
    value = ui_value(values, key)
    return float(value) if value is not None else None


def ui_int(values: dict[str, list[str]], key: str) -> int | None:
    value = ui_value(values, key)
    return int(value) if value is not None else None


@app.post("/ui/{action}")
async def ui_action(action: str, request: Request) -> RedirectResponse:
    """Handle ingress forms with the existing server-side contract handlers."""
    values = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    try:
        if action == "batch":
            create_batch(BatchCreate(
                created_ts=ui_value(values, "created_ts"), strain=ui_value(values, "strain") or "",
                recipe_version=ui_value(values, "recipe_version") or "", jar_count_planned=ui_int(values, "jar_count_planned"),
                operator=ui_value(values, "operator"), data_source="manual",
            ))
            message = "Batch and autoclave record saved."
        elif action == "stage":
            create_event(EventCreate(
                ts=ui_value(values, "ts"), batch_id=ui_value(values, "batch_id") or "", jar_id=ui_value(values, "jar_id"),
                to_stage=ui_value(values, "to_stage") or "", operator=ui_value(values, "operator"),
                dest_location=ui_value(values, "location"), notes=ui_value(values, "notes"),
                force="force" in values, data_source="manual",
            ))
            message = "Stage update recorded."
        elif action == "transfer":
            env = {key: ui_float(values, key) for key in ("temp_c", "rh_pct", "co2_ppm", "lux")}
            env["light_state"] = ui_value(values, "light_state")
            transfer_event(TransferCreate(
                batch_id=ui_value(values, "batch_id"), jar_ids=[ui_value(values, "jar_id")] if ui_value(values, "jar_id") else None,
                ts=ui_value(values, "ts") or now_iso(), operator=ui_value(values, "operator") or "",
                source_location=ui_value(values, "source_location") or "", dest_chamber=ui_value(values, "dest_chamber") or "",
                rack_shelf=ui_value(values, "rack_shelf") or "", reason=ui_value(values, "reason") or "",
                colonization_pct=ui_float(values, "colonization_pct") or 0, moisture_level=ui_value(values, "moisture_level") or "",
                env={key: value for key, value in env.items() if value is not None}, notes=ui_value(values, "notes"), data_source="manual",
                force="force" in values,
            ))
            message = "Transfer and environment snapshot recorded."
        elif action in {"observation", "harvest"}:
            common: dict[str, Any] = {
                "ts": ui_value(values, "ts") or now_iso(), "batch_id": ui_value(values, "batch_id") or "",
                "jar_id": ui_value(values, "jar_id"), "operator": ui_value(values, "operator"), "notes": ui_value(values, "notes"),
                "data_source": "manual",
            }
            if action == "observation":
                common.update({key: ui_value(values, key) for key in ("stage", "mycelial_density", "mycelial_color", "condensation_level", "substrate_dryness", "contamination_status", "contamination_type")})
                common.update({key: ui_float(values, key) for key in ("colonization_pct", "avg_height_mm")})
                common.update({key: ui_int(values, key) for key in ("primordia_count", "fruiting_body_count", "morphology_score")})
                create_observation(TableRecord(**common))
                message = "Observation recorded."
            else:
                common.update({key: ui_float(values, key) for key in ("fresh_weight_g", "dry_weight_g", "substrate_dry_g", "biological_efficiency_pct", "drying_temp_c", "drying_hours")})
                common.update({key: ui_int(values, key) for key in ("usable_jars", "rejected_jars", "contaminated_jars")})
                common.update({key: ui_value(values, key) for key in ("grade", "drying_method", "packaging_date", "package_type")})
                create_harvest(TableRecord(**common))
                message = "Harvest record saved."
        elif action == "lookup":
            lookup = ui_value(values, "lookup") or ""
            with get_db() as connection:
                found = one(connection, "SELECT * FROM batch_master WHERE batch_id=?", (lookup,))
                if not found:
                    found = one(connection, "SELECT j.*, b.strain FROM jar_master j JOIN batch_master b ON b.batch_id=j.batch_id WHERE j.jar_id=?", (lookup,))
            if not found:
                raise HTTPException(404, detail="batch or jar not found")
            message = f"Found {found['batch_id']}: {found.get('current_stage', 'record')}"
        else:
            raise HTTPException(404, detail="unknown workbench action")
        query = urlencode({"notice": message})
    except (HTTPException, ValueError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        query = urlencode({"error": str(detail)})
    return RedirectResponse(url=f"../?{query}", status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    with get_db() as connection:
        batch_count = connection.execute("SELECT COUNT(*) FROM batch_master").fetchone()[0]
        jar_count = connection.execute("SELECT COUNT(*) FROM jar_master").fetchone()[0]
        event_count = connection.execute("SELECT COUNT(*) FROM stage_events").fetchone()[0]
        observation_count = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        batches = rows(connection, "SELECT batch_id, strain, current_stage FROM batch_master ORDER BY created_ts DESC LIMIT 30")
        recent = connection.execute(
            "SELECT batch_id, jar_id, to_stage, ts, operator FROM stage_events ORDER BY ts DESC, id DESC LIMIT 8"
        ).fetchall()
    recent_rows = "".join(
        f"<tr><td>{html.escape(str(row['batch_id']))}</td>"
        f"<td>{html.escape(str(row['jar_id'] or '-'))}</td>"
        f"<td>{html.escape(str(row['to_stage'] or '-'))}</td>"
        f"<td>{html.escape(str(row['ts']))}</td>"
        f"<td>{html.escape(str(row['operator'] or '-'))}</td></tr>"
        for row in recent
    ) or '<tr><td colspan="5" class="muted">No events recorded yet.</td></tr>'
    batch_options = "".join(
        f'<option value="{html.escape(batch["batch_id"], quote=True)}">{html.escape(batch["batch_id"])} · {html.escape(batch["strain"])} · {html.escape(batch["current_stage"])}</option>'
        for batch in batches
    ) or '<option value="">No batches yet</option>'
    params = request.query_params
    notice = html.escape(params.get("notice", ""))
    error = html.escape(params.get("error", ""))
    feedback = f'<div class="flash success" role="status">{notice}</div>' if notice else ""
    feedback += f'<div class="flash error" role="alert">{error}</div>' if error else ""
    page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cordyceps Lab Workbench</title><style>
:root{--paper:#f4efe4;--paper-deep:#e7dece;--ink:#20251e;--muted:#687064;--fern:#315c43;--fern-dark:#214331;--saffron:#c87822;--red:#a64532;--line:#cfc5b3;--white:#fffdf8;--shadow:0 8px 24px #51402a16}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 "Trebuchet MS",Verdana,sans-serif;background-image:radial-gradient(#315c4310 .7px,transparent .7px);background-size:13px 13px}header{position:sticky;top:0;z-index:2;background:var(--paper);border-bottom:1px solid var(--line);padding:14px max(20px,calc((100% - 1200px)/2));display:flex;align-items:center;justify-content:space-between;gap:18px}.brand{display:flex;align-items:center;gap:12px}.mark{width:34px;height:34px;background:var(--fern);color:var(--paper);display:grid;place-items:center;border-radius:8px;font:700 20px Georgia,serif}.kicker{text-transform:uppercase;letter-spacing:.13em;font-size:11px;color:var(--fern);font-weight:700}h1,h2,h3{font-family:Georgia,"Times New Roman",serif;letter-spacing:0}h1{font-size:clamp(24px,4vw,38px);line-height:1;margin:0}h2{font-size:23px;margin:0 0 4px}h3{font-size:18px;margin:0}.wrap{max-width:1200px;margin:0 auto;padding:30px 20px 56px}.intro{display:flex;justify-content:space-between;align-items:end;gap:30px;margin-bottom:24px}.intro p{max-width:500px;color:var(--muted);margin:8px 0 0}.quick{display:flex;gap:8px;flex-wrap:wrap}.quick a{color:var(--fern);font-weight:700;border-bottom:2px solid var(--saffron);text-decoration:none;padding:4px 0}.stats{display:grid;grid-template-columns:repeat(4,1fr);border-block:1px solid var(--line);margin-bottom:28px}.stat{padding:15px 17px;border-right:1px solid var(--line)}.stat:last-child{border:0}.stat b{display:block;font:700 30px Georgia,serif;color:var(--fern)}.stat span{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.forms{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.panel{background:var(--white);border:1px solid var(--line);border-radius:8px;padding:20px;box-shadow:var(--shadow);animation:rise .45s both}.panel:nth-child(2){animation-delay:.06s}.panel:nth-child(3){animation-delay:.12s}.panel:nth-child(4){animation-delay:.18s}.panel.wide{grid-column:1/-1}.panel-head{display:flex;align-items:start;justify-content:space-between;gap:12px;margin-bottom:16px}.index{color:var(--saffron);font:700 20px Georgia,serif}.hint{color:var(--muted);font-size:12px;margin:2px 0 0}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px 13px}.field{display:flex;flex-direction:column;gap:4px}.field.full{grid-column:1/-1}label{font-size:12px;font-weight:700;color:var(--muted)}input,select,textarea{width:100%;border:1px solid #bdb4a4;background:#fffefb;color:var(--ink);border-radius:5px;padding:10px;font:inherit}textarea{min-height:64px;resize:vertical}input:focus,select:focus,textarea:focus{outline:3px solid #c8782250;border-color:var(--saffron)}.actions{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:16px}.button{border:0;border-radius:5px;background:var(--fern);color:white;padding:11px 16px;font:700 14px inherit;cursor:pointer}.button:hover{background:var(--fern-dark)}.button:disabled{opacity:.55;cursor:wait}.check{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px}.check input{width:auto}.flash{padding:12px 15px;border-radius:5px;margin-bottom:18px;font-weight:700}.success{background:#dceadd;color:var(--fern-dark);border-left:4px solid var(--fern)}.error{background:#f5dcd4;color:#7e3026;border-left:4px solid var(--red)}.recent{margin-top:30px}.table-wrap{overflow:auto;background:var(--white);border:1px solid var(--line);border-radius:8px}.recent table{width:100%;border-collapse:collapse;min-width:650px}.recent th,.recent td{text-align:left;padding:11px 13px;border-bottom:1px solid var(--line);font-size:13px}.recent th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.07em}.recent tr:last-child td{border:0}.muted{text-align:center;color:var(--muted);padding:22px!important}@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}@media(max-width:760px){.intro{display:block}.quick{margin-top:14px}.stats{grid-template-columns:repeat(2,1fr)}.stat:nth-child(2){border-right:0}.stat:nth-child(-n+2){border-bottom:1px solid var(--line)}.forms{grid-template-columns:1fr}.panel.wide{grid-column:auto}}@media(max-width:480px){.wrap{padding-inline:14px}header{padding-inline:14px}.fields{grid-template-columns:1fr}.field.full{grid-column:auto}.actions{align-items:stretch;flex-direction:column}.button{width:100%}}
</style></head><body><header><div class="brand"><div class="mark">C</div><div><div class="kicker">Controlled cultivation</div><h1>Daily workbench</h1></div></div><nav class="quick"><a href="./docs">API docs</a><a href="/lovelace/lab-scan">Scan dashboard</a></nav></header><main class="wrap">__FEEDBACK__<section class="intro"><div><div class="kicker">Field notebook / 26 Aug 2026</div><p>Record the next physical action while the batch is in your hands. Every entry becomes part of the traceable lab history.</p></div></section><section class="stats"><div class="stat"><b>__BATCHES__</b><span>Batches</span></div><div class="stat"><b>__JARS__</b><span>Jars in ledger</span></div><div class="stat"><b>__EVENTS__</b><span>Stage events</span></div><div class="stat"><b>__OBSERVATIONS__</b><span>Observations</span></div></section><section class="forms">
<form class="panel" action="./ui/batch" method="post"><div class="panel-head"><div><div class="kicker">01 / intake</div><h2>New batch / autoclave</h2><p class="hint">Creates the batch, planned jars, and autoclave event.</p></div><span class="index">01</span></div><div class="fields"><div class="field"><label for="created_ts">Date and time</label><input id="created_ts" name="created_ts" type="datetime-local" required></div><div class="field"><label for="strain">Strain</label><input id="strain" name="strain" placeholder="CM-Delhi" required></div><div class="field"><label for="recipe_version">Recipe version</label><input id="recipe_version" name="recipe_version" placeholder="R-2026.3" required></div><div class="field"><label for="jar_count_planned">Planned jar count</label><input id="jar_count_planned" name="jar_count_planned" type="number" min="0" max="999" required></div><div class="field full"><label for="batch_operator">Operator</label><input id="batch_operator" name="operator" required></div></div><div class="actions"><span class="hint">Stage starts at autoclaved.</span><button class="button" type="submit">Save batch</button></div></form>
<form class="panel" action="./ui/stage" method="post"><div class="panel-head"><div><div class="kicker">02 / movement</div><h2>Stage update</h2><p class="hint">Use a batch ID or a specific jar ID.</p></div><span class="index">02</span></div><div class="fields"><div class="field"><label for="stage_batch">Batch ID</label><input id="stage_batch" name="batch_id" list="batch-list" required></div><div class="field"><label for="stage_jar">Jar ID <span class="hint">optional</span></label><input id="stage_jar" name="jar_id" placeholder="...-J001"></div><div class="field"><label for="to_stage">Target stage</label><select id="to_stage" name="to_stage" required><option value="">Choose stage</option>__STAGE_OPTIONS__</select></div><div class="field"><label for="location">Location</label><input id="location" name="location" placeholder="dark_room"></div><div class="field"><label for="stage_operator">Operator</label><input id="stage_operator" name="operator" required></div><div class="field full"><label for="stage_notes">Notes</label><textarea id="stage_notes" name="notes"></textarea></div></div><div class="actions"><label class="check"><input name="force" type="checkbox"> Force transition (audited)</label><button class="button" type="submit">Record stage</button></div></form>
<form class="panel" action="./ui/transfer" method="post"><div class="panel-head"><div><div class="kicker">03 / environment</div><h2>Transfer to light</h2><p class="hint">Moves one batch or jar and captures the environment snapshot.</p></div><span class="index">03</span></div><div class="fields"><div class="field"><label for="transfer_batch">Batch ID</label><input id="transfer_batch" name="batch_id" list="batch-list"></div><div class="field"><label for="transfer_jar">Jar ID <span class="hint">optional</span></label><input id="transfer_jar" name="jar_id"></div><div class="field"><label for="transfer_ts">Timestamp</label><input id="transfer_ts" name="ts" type="datetime-local" required></div><div class="field"><label for="transfer_operator">Operator</label><input id="transfer_operator" name="operator" required></div><div class="field"><label for="source_location">Source</label><input id="source_location" name="source_location" placeholder="dark_room" required></div><div class="field"><label for="dest_chamber">Destination</label><input id="dest_chamber" name="dest_chamber" placeholder="light_room" required></div><div class="field"><label for="rack_shelf">Rack / shelf</label><input id="rack_shelf" name="rack_shelf" placeholder="F1-R2-S3" required></div><div class="field"><label for="reason">Reason</label><input id="reason" name="reason" value="scheduled transfer" required></div><div class="field"><label for="colonization_pct">Colonization %</label><input id="colonization_pct" name="colonization_pct" type="number" min="0" max="100" step="0.1" required></div><div class="field"><label for="moisture_level">Moisture</label><input id="moisture_level" name="moisture_level" placeholder="ideal" required></div><div class="field"><label for="temp_c">Temperature C</label><input id="temp_c" name="temp_c" type="number" step="0.1"></div><div class="field"><label for="rh_pct">RH %</label><input id="rh_pct" name="rh_pct" type="number" step="0.1"></div><div class="field"><label for="co2_ppm">CO2 ppm</label><input id="co2_ppm" name="co2_ppm" type="number"></div><div class="field"><label for="lux">Lux</label><input id="lux" name="lux" type="number"></div></div><div class="actions"><label class="check"><input name="force" type="checkbox"> Force transition (audited)</label><button class="button" type="submit">Transfer to light</button></div></form>
<form class="panel" action="./ui/observation" method="post"><div class="panel-head"><div><div class="kicker">04 / inspection</div><h2>Observation / harvest</h2><p class="hint">Log inspection details now; harvest fields are available below.</p></div><span class="index">04</span></div><div class="fields"><div class="field"><label for="obs_batch">Batch ID</label><input id="obs_batch" name="batch_id" list="batch-list" required></div><div class="field"><label for="obs_jar">Jar ID</label><input id="obs_jar" name="jar_id"></div><div class="field"><label for="obs_stage">Stage</label><select id="obs_stage" name="stage"><option value="">Select stage</option>__STAGE_OPTIONS__</select></div><div class="field"><label for="obs_operator">Operator</label><input id="obs_operator" name="operator" required></div><div class="field"><label for="colonization_obs">Colonization %</label><input id="colonization_obs" name="colonization_pct" type="number" min="0" max="100" step="0.1"></div><div class="field"><label for="density">Mycelial density</label><input id="density" name="mycelial_density" placeholder="even / patchy"></div><div class="field"><label for="contamination">Contamination</label><select id="contamination" name="contamination_status"><option value="">Select status</option><option>clear</option><option>suspect</option><option>confirmed</option></select></div><div class="field"><label for="primordia">Primordia count</label><input id="primordia" name="primordia_count" type="number" min="0"></div><div class="field full"><label for="obs_notes">Notes</label><textarea id="obs_notes" name="notes" placeholder="Color, condensation, morphology, or contamination detail"></textarea></div></div><div class="actions"><span class="hint">Raw fields are stored only when supported by the schema.</span><button class="button" type="submit">Save observation</button></div></form>
<form class="panel wide" action="./ui/harvest" method="post"><div class="panel-head"><div><div class="kicker">05 / close-out</div><h2>Harvest record</h2><p class="hint">Weights and packaging details feed the yield ledger. Biological efficiency is derived when substrate dry weight is supplied.</p></div><span class="index">05</span></div><div class="fields"><div class="field"><label for="harvest_batch">Batch ID</label><input id="harvest_batch" name="batch_id" list="batch-list" required></div><div class="field"><label for="harvest_jar">Jar ID</label><input id="harvest_jar" name="jar_id"></div><div class="field"><label for="harvest_ts">Timestamp</label><input id="harvest_ts" name="ts" type="datetime-local" required></div><div class="field"><label for="harvest_operator">Operator</label><input id="harvest_operator" name="operator" required></div><div class="field"><label for="fresh_weight_g">Fresh weight (g)</label><input id="fresh_weight_g" name="fresh_weight_g" type="number" step="0.1"></div><div class="field"><label for="dry_weight_g">Dry weight (g)</label><input id="dry_weight_g" name="dry_weight_g" type="number" step="0.1"></div><div class="field"><label for="substrate_dry_g">Substrate dry (g)</label><input id="substrate_dry_g" name="substrate_dry_g" type="number" step="0.1"></div><div class="field"><label for="grade">Grade</label><input id="grade" name="grade" placeholder="A"></div><div class="field"><label for="drying_method">Drying method</label><input id="drying_method" name="drying_method"></div><div class="field"><label for="package_type">Package type</label><input id="package_type" name="package_type"></div><div class="field full"><label for="harvest_notes">Notes</label><textarea id="harvest_notes" name="notes"></textarea></div></div><div class="actions"><span class="hint">Use the same form for batch or jar-level harvest.</span><button class="button" type="submit">Save harvest</button></div></form></section>
<form class="panel wide" action="./ui/lookup" method="post"><div class="panel-head"><div><div class="kicker">06 / lookup</div><h2>Find a record</h2><p class="hint">Search a batch or jar ID in the ledger.</p></div><span class="index">06</span></div><div class="actions"><input name="lookup" list="batch-list" placeholder="AC-20260821-01 or ...-J001" required><button class="button" type="submit">Look up</button></div></form><datalist id="batch-list">__BATCH_OPTIONS__</datalist><section class="recent"><div class="kicker">Ledger / latest movement</div><h2>Recent events</h2><div class="table-wrap"><table><thead><tr><th>Batch</th><th>Jar</th><th>Stage</th><th>Time</th><th>Operator</th></tr></thead><tbody>__RECENT_ROWS__</tbody></table></div></section></main><script>document.querySelectorAll("form").forEach(function(form){form.addEventListener("submit",function(){var button=form.querySelector("button[type=submit]");if(button){button.disabled=true;button.textContent="Saving...";}});});</script></body></html>"""
    stage_options = "".join(f'<option value="{html.escape(stage, quote=True)}">{html.escape(stage.replace("_", " "))}</option>' for stage in sorted(STAGES))
    return HTMLResponse(page.replace("__FEEDBACK__", feedback).replace("__BATCHES__", str(batch_count)).replace("__JARS__", str(jar_count)).replace("__EVENTS__", str(event_count)).replace("__OBSERVATIONS__", str(observation_count)).replace("__STAGE_OPTIONS__", stage_options).replace("__BATCH_OPTIONS__", batch_options).replace("__RECENT_ROWS__", recent_rows))


def rows(connection: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


def one(connection: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    row = connection.execute(sql, parameters).fetchone()
    return dict(row) if row else None


def columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def insert_row(connection: sqlite3.Connection, table: str, values: dict[str, Any]) -> int:
    usable = {key: value for key, value in values.items() if key in columns(connection, table)}
    if not usable:
        raise HTTPException(status_code=422, detail=f"no valid fields supplied for {table}")
    names = list(usable)
    cursor = connection.execute(
        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
        tuple(usable[name] for name in names),
    )
    return int(cursor.lastrowid)


def dedupe_response(connection: sqlite3.Connection, client_event_id: str | None) -> dict[str, Any] | None:
    if not client_event_id:
        return None
    row = one(connection, "SELECT response_json FROM client_event_dedupe WHERE client_event_id = ?", (client_event_id,))
    return json.loads(row["response_json"]) if row else None


def remember_response(connection: sqlite3.Connection, client_event_id: str | None, endpoint: str, payload: dict[str, Any]) -> None:
    if client_event_id:
        connection.execute(
            "INSERT INTO client_event_dedupe(client_event_id, endpoint, response_json, created_ts) VALUES (?, ?, ?, ?)",
            (client_event_id, endpoint, json.dumps(payload, default=str), now_iso()),
        )


def ensure_source(value: str | None) -> str | None:
    if value is not None and value not in SOURCE_VALUES:
        raise HTTPException(422, detail="data_source must be manual, qr_scan, sensor, import, or system")
    return value


def unique_token(connection: sqlite3.Connection) -> str:
    while True:
        token = mint_scan_token()
        if not connection.execute("SELECT 1 FROM batch_master WHERE scan_token = ? UNION SELECT 1 FROM jar_master WHERE scan_token = ?", (token, token)).fetchone():
            return token


def record_env_snapshot(connection: sqlite3.Connection, payload: dict[str, Any]) -> int:
    """Store a snapshot while applying the contract's NULL/missing-source rule."""
    result: dict[str, Any] = {
        "ts": payload.get("ts") or now_iso(), "batch_id": payload.get("batch_id"),
        "jar_id": payload.get("jar_id"), "chamber": payload.get("chamber"),
        "raw_json": payload.get("raw_json", json.dumps(payload, default=str)),
    }
    sensor_fields = ("temp_c", "rh_pct", "co2_ppm", "light_state", "lux", "photoperiod", "door_state",
                     "fan_state", "humidifier_state", "exhaust_state", "airflow_ms")
    for field in sensor_fields:
        value, derived_source = coerce(payload.get(field))
        result[field] = value
        result[f"{field}_src"] = "missing" if derived_source == "missing" else payload.get(f"{field}_src", derived_source)
    result["vpd_kpa"] = vpd_kpa(result["temp_c"], result["rh_pct"])
    result["vpd_kpa_src"] = "missing" if result["vpd_kpa"] is None else "sensor"
    return insert_row(connection, "env_snapshots", result)


def stage_target(connection: sqlite3.Connection, batch_id: str, jar_id: str | None) -> dict[str, Any]:
    record = one(connection, "SELECT * FROM jar_master WHERE jar_id=?", (jar_id,)) if jar_id else one(connection, "SELECT * FROM batch_master WHERE batch_id=?", (batch_id,))
    if not record:
        raise HTTPException(404, detail="jar or batch not found")
    if jar_id and record["batch_id"] != batch_id:
        raise HTTPException(422, detail="jar_id does not belong to batch_id")
    return record


def apply_stage_event(connection: sqlite3.Connection, payload: dict[str, Any], *, env_snapshot_id: int | None = None) -> dict[str, Any]:
    batch_id = payload.get("batch_id")
    jar_id = payload.get("jar_id")
    if not batch_id:
        raise HTTPException(422, detail="batch_id is required")
    target = stage_target(connection, batch_id, jar_id)
    to_stage = payload.get("to_stage")
    if not to_stage:
        raise HTTPException(422, detail="to_stage is required")
    try:
        checked = transition(target["current_stage"], to_stage, force=bool(payload.get("force", False)))
    except IllegalTransition as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    event = {
        "ts": payload.get("ts") or now_iso(), "batch_id": batch_id, "jar_id": jar_id,
        "from_stage": checked.from_stage, "to_stage": checked.to_stage, "action": payload.get("action"),
        "source_location": payload.get("source_location"), "dest_location": payload.get("dest_location"),
        "rack_shelf": payload.get("rack_shelf"), "reason": payload.get("reason"),
        "colonization_pct": payload.get("colonization_pct"), "moisture_level": payload.get("moisture_level"),
        "env_snapshot_id": env_snapshot_id if env_snapshot_id is not None else payload.get("env_snapshot_id"),
        "equipment_id": payload.get("equipment_id"), "notes": payload.get("notes"),
        "operator": payload.get("operator"), "data_source": payload.get("data_source") or "manual",
        "forced": checked.forced,
    }
    event_id = insert_row(connection, "stage_events", event)
    destination = payload.get("dest_location")
    if jar_id:
        connection.execute("UPDATE jar_master SET current_stage=?, current_location=COALESCE(?, current_location), rack_shelf=COALESCE(?, rack_shelf) WHERE jar_id=?", (to_stage, destination, payload.get("rack_shelf"), jar_id))
    else:
        connection.execute("UPDATE batch_master SET current_stage=?, current_location=COALESCE(?, current_location) WHERE batch_id=?", (to_stage, destination, batch_id))
        connection.execute("UPDATE jar_master SET current_stage=?, current_location=COALESCE(?, current_location), rack_shelf=COALESCE(?, rack_shelf) WHERE batch_id=?", (to_stage, destination, payload.get("rack_shelf"), batch_id))
    return {"id": event_id, "batch_id": batch_id, "jar_id": jar_id, "from_stage": checked.from_stage, "to_stage": to_stage, "forced": checked.forced}


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    client_event_id: str | None = None


class BatchCreate(ContractModel):
    batch_id: str | None = None
    created_ts: str | None = None
    strain: str
    recipe_version: str
    jar_count_planned: int | None = None
    current_stage: Literal["autoclaved"] = "autoclaved"
    operator: str | None = None
    data_source: str | None = None


class BatchPatch(ContractModel):
    strain: str | None = None
    culture_generation: str | None = None
    culture_source: str | None = None
    inoculation_method: str | None = None
    recipe_version: str | None = None
    rice_g_per_jar: float | None = None
    broth_ml_per_jar: float | None = None
    water_source: str | None = None
    fill_weight_g: float | None = None
    jar_type: str | None = None
    lid_filter_type: str | None = None
    sterilization_profile: str | None = None
    autoclave_id: str | None = None
    autoclave_temp_c: float | None = None
    autoclave_pressure_psi: float | None = None
    autoclave_hold_min: int | None = None
    autoclave_cycle_result: str | None = None
    autoclave_deviations: str | None = None
    jar_count_planned: int | None = None
    current_location: str | None = None
    notes: str | None = None
    operator: str | None = None
    data_source: str | None = None


class EventCreate(ContractModel):
    ts: str | None = None
    batch_id: str
    jar_id: str | None = None
    to_stage: str
    action: str | None = None
    source_location: str | None = None
    dest_location: str | None = None
    rack_shelf: str | None = None
    reason: str | None = None
    colonization_pct: float | None = None
    moisture_level: str | None = None
    env_snapshot_id: int | None = None
    equipment_id: str | None = None
    notes: str | None = None
    operator: str | None = None
    data_source: str | None = None
    force: bool = False


class TransferCreate(ContractModel):
    batch_id: str | None = None
    jar_ids: list[str] | None = None
    ts: str
    operator: str
    source_location: str
    dest_chamber: str
    rack_shelf: str
    reason: str
    colonization_pct: float
    moisture_level: str
    env: dict[str, Any]
    notes: str | None = None
    data_source: str | None = None
    force: bool = False


class TableRecord(ContractModel):
    ts: str
    batch_id: str
    jar_id: str | None = None
    operator: str | None = None
    data_source: str | None = None


class EnvSnapshot(ContractModel):
    ts: str
    batch_id: str | None = None
    jar_id: str | None = None
    chamber: str | None = None


class EnvSummary(ContractModel):
    batch_id: str
    # stage omitted => summarise EVERY stage present for the batch.
    stage: str | None = None
    chamber: str | None = None


class LabelsRequest(ContractModel):
    batch_id: str
    jar_ids: list[str] | None = None


# /health is intentionally UNauthenticated: the add-on watchdog, docker HEALTHCHECK
# and HA's rest sensor must be able to poll liveness without holding the token.
# It exposes no lab data.
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "2.4.0"}


# ---------------------------------------------------------------------------
# Printed-label indirection.
#
# WHY THIS EXISTS: QR codes on jars are physical and permanent. If the payload
# embedded Home Assistant's own host:port, then changing the HA web server port
# (HA 2026.8 moves new HAOS installs off :8123, and the port is now editable in
# the UI) would silently invalidate every label already stuck to a jar.
#
# So labels point at THIS service instead, which owns a stable port, and we
# redirect to whatever HA URL is currently configured. Changing the HA address
# becomes a one-line app option change instead of a reprint of hundreds of jars.
#
# UNauthenticated by design: the tablet's camera/browser follows this before any
# HA login. It leaks nothing — the token is opaque and the redirect target is a
# dashboard path. Resolving the token to actual lab data still requires the
# bearer token via /resolve.
# ---------------------------------------------------------------------------
@app.get("/s/{scan_token}")
def scan_redirect(scan_token: str) -> RedirectResponse:
    ha_base = os.getenv("HA_BASE_URL", "http://homeassistant.local:8123").rstrip("/")
    # Deliberately NOT validated against the database: an unknown token still
    # redirects, and the dashboard shows "unknown label". Probing this endpoint
    # therefore reveals nothing about which tokens are real.
    return RedirectResponse(url=f"{ha_base}/lab-scan?t={scan_token}", status_code=302)


@app.post("/batches", dependencies=[Depends(require_auth)])
def create_batch(body: BatchCreate) -> dict[str, Any]:
    values = model_data(body)
    with get_db() as connection:
        duplicate = dedupe_response(connection, body.client_event_id)
        if duplicate is not None:
            return duplicate
        try:
            connection.execute("BEGIN IMMEDIATE")
            created_ts = values.get("created_ts") or now_iso()
            if values.get("batch_id"):
                batch_id = values["batch_id"]
                if not is_valid_batch_id(batch_id):
                    raise HTTPException(422, detail="batch_id does not match ^AC-\\d{8}-\\d{2}$")
            else:
                batch_id = allocate_batch_id(connection, created_ts)
            ensure_source(values.get("data_source"))
            batch = {key: value for key, value in values.items() if key not in {"client_event_id", "batch_id", "created_ts"}}
            batch.update({"batch_id": batch_id, "scan_token": unique_token(connection), "created_ts": created_ts, "current_stage": "autoclaved"})
            insert_row(connection, "batch_master", batch)
            insert_row(connection, "stage_events", {"ts": created_ts, "batch_id": batch_id, "to_stage": "autoclaved", "action": "autoclave_logging", "operator": values.get("operator"), "data_source": values.get("data_source") or "manual", "forced": 0})
            jar_ids: list[str] = []
            planned = values.get("jar_count_planned") or 0
            if planned < 0 or planned > 999:
                raise HTTPException(422, detail="jar_count_planned must be between 0 and 999")
            for index in range(1, planned + 1):
                jar_id = mint_jar_id(batch_id, index)
                jar_ids.append(jar_id)
                insert_row(connection, "jar_master", {"jar_id": jar_id, "batch_id": batch_id, "scan_token": unique_token(connection), "jar_index": index, "current_stage": "autoclaved", "current_location": values.get("current_location"), "fill_weight_g": values.get("fill_weight_g"), "created_ts": created_ts, "notes": values.get("notes")})
            response = {"batch_id": batch_id, "scan_token": batch["scan_token"], "jar_ids": jar_ids}
            remember_response(connection, body.client_event_id, "/batches", response)
            connection.commit()
            return response
        except Exception:
            connection.rollback()
            raise


@app.get("/batches", dependencies=[Depends(require_auth)])
def list_batches(stage: str | None = None, strain: str | None = None, chamber: str | None = None, limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    terms, parameters = [], []
    if stage: terms.append("current_stage=?"); parameters.append(stage)
    if strain: terms.append("strain=?"); parameters.append(strain)
    if chamber: terms.append("current_location=?"); parameters.append(chamber)
    where = f" WHERE {' AND '.join(terms)}" if terms else ""
    with get_db() as connection:
        return {"batches": rows(connection, f"SELECT * FROM batch_master{where} ORDER BY created_ts DESC LIMIT ?", tuple(parameters + [limit]))}


@app.get("/batches/{batch_id}", dependencies=[Depends(require_auth)])
def get_batch(batch_id: str) -> dict[str, Any]:
    with get_db() as connection:
        batch = one(connection, "SELECT * FROM batch_master WHERE batch_id=?", (batch_id,))
        if not batch: raise HTTPException(404, detail="batch not found")
        batch["jars"] = rows(connection, "SELECT * FROM jar_master WHERE batch_id=? ORDER BY jar_index", (batch_id,))
        return batch


@app.patch("/batches/{batch_id}", dependencies=[Depends(require_auth)])
def patch_batch(batch_id: str, body: BatchPatch) -> dict[str, Any]:
    values = model_data(body)
    values.pop("client_event_id", None)
    with get_db() as connection:
        duplicate = dedupe_response(connection, body.client_event_id)
        if duplicate is not None: return duplicate
        if not one(connection, "SELECT 1 AS found FROM batch_master WHERE batch_id=?", (batch_id,)):
            raise HTTPException(404, detail="batch not found")
        ensure_source(values.get("data_source"))
        valid = columns(connection, "batch_master") - {"batch_id", "scan_token", "created_ts", "current_stage"}
        updates = {key: value for key, value in values.items() if key in valid}
        if not updates: raise HTTPException(422, detail="no updatable fields supplied")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(f"UPDATE batch_master SET {', '.join(f'{key}=?' for key in updates)} WHERE batch_id=?", (*updates.values(), batch_id))
        response = one(connection, "SELECT * FROM batch_master WHERE batch_id=?", (batch_id,)) or {}
        remember_response(connection, body.client_event_id, f"/batches/{batch_id}", response)
        connection.commit()
        return response


@app.get("/batches/{batch_id}/timeline", dependencies=[Depends(require_auth)])
def batch_timeline(batch_id: str) -> dict[str, Any]:
    with get_db() as connection:
        if not one(connection, "SELECT 1 AS found FROM batch_master WHERE batch_id=?", (batch_id,)): raise HTTPException(404, detail="batch not found")
        return {"batch_id": batch_id, "stages": rows(connection, "SELECT * FROM stage_events WHERE batch_id=? ORDER BY ts, id", (batch_id,)), "events": rows(connection, "SELECT * FROM stage_events WHERE batch_id=? ORDER BY ts, id", (batch_id,)), "durations": rows(connection, "SELECT * FROM stage_durations WHERE batch_id=?", (batch_id,)), "latest_photo": one(connection, "SELECT * FROM photos WHERE batch_id=? ORDER BY ts DESC, id DESC LIMIT 1", (batch_id,)), "env_history": rows(connection, "SELECT * FROM env_snapshots WHERE batch_id=? ORDER BY ts, id", (batch_id,))}


@app.get("/jars/{jar_id}", dependencies=[Depends(require_auth)])
def get_jar(jar_id: str) -> dict[str, Any]:
    with get_db() as connection:
        jar = one(connection, "SELECT * FROM jar_master WHERE jar_id=?", (jar_id,))
        if not jar: raise HTTPException(404, detail="jar not found")
        return jar


@app.get("/resolve", dependencies=[Depends(require_auth)])
def resolve(t: str) -> dict[str, Any]:
    with get_db() as connection:
        batch = one(connection, "SELECT * FROM batch_master WHERE scan_token=?", (t,))
        if batch:
            return {"kind": "batch", "batch_id": batch["batch_id"], "jar_id": None, "strain": batch["strain"], "current_stage": batch["current_stage"], "current_location": batch["current_location"], "display_name": batch["batch_id"], "allowed_actions": allowed_actions(batch["current_stage"])}
        jar = one(connection, "SELECT j.*, b.strain FROM jar_master j JOIN batch_master b ON b.batch_id=j.batch_id WHERE j.scan_token=?", (t,))
        if not jar: raise HTTPException(404, detail="scan token not found")
        return {"kind": "jar", "batch_id": jar["batch_id"], "jar_id": jar["jar_id"], "strain": jar["strain"], "current_stage": jar["current_stage"], "current_location": jar["current_location"], "display_name": jar["jar_id"], "allowed_actions": allowed_actions(jar["current_stage"])}


@app.post("/events", dependencies=[Depends(require_auth)])
def create_event(body: EventCreate) -> dict[str, Any]:
    values = model_data(body)
    ensure_source(values.get("data_source"))
    with get_db() as connection:
        duplicate = dedupe_response(connection, body.client_event_id)
        if duplicate is not None: return duplicate
        connection.execute("BEGIN IMMEDIATE")
        try:
            response = apply_stage_event(connection, values)
            remember_response(connection, body.client_event_id, "/events", response)
            connection.commit(); return response
        except Exception:
            connection.rollback(); raise


@app.post("/events/transfer", dependencies=[Depends(require_auth)])
def transfer_event(body: TransferCreate) -> dict[str, Any]:
    if not body.batch_id and not body.jar_ids:
        raise HTTPException(422, detail="one of batch_id or jar_ids is required")
    values = model_data(body)
    ensure_source(values.get("data_source"))
    with get_db() as connection:
        duplicate = dedupe_response(connection, body.client_event_id)
        if duplicate is not None: return duplicate
        connection.execute("BEGIN IMMEDIATE")
        try:
            target_pairs: list[tuple[str, str | None]]
            if body.jar_ids:
                jar_rows = rows(connection, f"SELECT jar_id, batch_id FROM jar_master WHERE jar_id IN ({','.join('?' for _ in body.jar_ids)})", tuple(body.jar_ids))
                if len(jar_rows) != len(set(body.jar_ids)): raise HTTPException(404, detail="one or more jars not found")
                target_pairs = [(item["batch_id"], item["jar_id"]) for item in jar_rows]
                if body.batch_id and any(batch != body.batch_id for batch, _ in target_pairs): raise HTTPException(422, detail="jar_ids do not all belong to batch_id")
            else:
                target_pairs = [(body.batch_id or "", None)]
            responses = []
            for batch_id, jar_id in target_pairs:
                env = dict(body.env)
                env.update({"ts": body.ts, "batch_id": batch_id, "jar_id": jar_id, "chamber": body.dest_chamber})
                snapshot_id = record_env_snapshot(connection, env)
                event = {"ts": body.ts, "batch_id": batch_id, "jar_id": jar_id, "to_stage": "transferred_to_light", "action": "transfer_dark_to_light", "source_location": body.source_location, "dest_location": body.dest_chamber, "rack_shelf": body.rack_shelf, "reason": body.reason, "colonization_pct": body.colonization_pct, "moisture_level": body.moisture_level, "operator": body.operator, "notes": body.notes, "data_source": body.data_source or "manual", "force": body.force}
                responses.append(apply_stage_event(connection, event, env_snapshot_id=snapshot_id))
            response = {"events": responses}
            remember_response(connection, body.client_event_id, "/events/transfer", response)
            connection.commit(); return response
        except Exception:
            connection.rollback(); raise


def create_table_record(table: str, body: TableRecord, endpoint: str, derive: callable | None = None) -> dict[str, Any]:
    values = model_data(body)
    ensure_source(values.get("data_source"))
    values.pop("client_event_id", None)
    if derive: derive(values)
    with get_db() as connection:
        duplicate = dedupe_response(connection, body.client_event_id)
        if duplicate is not None: return duplicate
        connection.execute("BEGIN IMMEDIATE")
        try:
            record_id = insert_row(connection, table, values)
            response = {"id": record_id}
            remember_response(connection, body.client_event_id, endpoint, response)
            connection.commit(); return response
        except Exception:
            connection.rollback(); raise


@app.post("/observations", dependencies=[Depends(require_auth)])
def create_observation(body: TableRecord) -> dict[str, Any]: return create_table_record("observations", body, "/observations")

@app.post("/interventions", dependencies=[Depends(require_auth)])
def create_intervention(body: TableRecord) -> dict[str, Any]: return create_table_record("interventions", body, "/interventions")


def derive_harvest(values: dict[str, Any]) -> None:
    dry, substrate = values.get("dry_weight_g"), values.get("substrate_dry_g")
    values["biological_efficiency_pct"] = (100 * float(dry) / float(substrate)) if dry is not None and substrate is not None else None

@app.post("/harvest", dependencies=[Depends(require_auth)])
def create_harvest(body: TableRecord) -> dict[str, Any]: return create_table_record("harvest_yield", body, "/harvest", derive_harvest)

@app.post("/costs", dependencies=[Depends(require_auth)])
def create_cost(body: TableRecord) -> dict[str, Any]: return create_table_record("costs", body, "/costs")

@app.post("/photos", dependencies=[Depends(require_auth)])
def create_photo(body: TableRecord) -> dict[str, Any]: return create_table_record("photos", body, "/photos")


@app.post("/env/snapshot", dependencies=[Depends(require_auth)])
def create_snapshot(body: EnvSnapshot) -> dict[str, Any]:
    values = model_data(body)
    with get_db() as connection:
        duplicate = dedupe_response(connection, body.client_event_id)
        if duplicate is not None: return duplicate
        connection.execute("BEGIN IMMEDIATE")
        try:
            response = {"id": record_env_snapshot(connection, values)}
            remember_response(connection, body.client_event_id, "/env/snapshot", response)
            connection.commit(); return response
        except Exception:
            connection.rollback(); raise


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] if lower == upper else ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


@app.post("/env/summarize", dependencies=[Depends(require_auth)])
def summarize_env(body: EnvSummary) -> dict[str, Any]:
    if body.stage is not None and body.stage not in STAGES:
        raise HTTPException(422, detail="stage is outside the closed vocabulary")
    if body.stage is None:
        # Fan out over every distinct stage recorded for this batch.
        with get_db() as connection:
            present = [r["to_stage"] for r in rows(connection, "SELECT DISTINCT to_stage FROM stage_events WHERE batch_id=?", (body.batch_id,))]
        totals: dict[str, Any] = {"batch_id": body.batch_id, "stages": {}}
        for stage_name in present:
            sub = EnvSummary(batch_id=body.batch_id, stage=stage_name, chamber=body.chamber,
                             client_event_id=(f"{body.client_event_id}:{stage_name}" if body.client_event_id else None))
            totals["stages"][stage_name] = summarize_env(sub)
        return totals
    with get_db() as connection:
        duplicate = dedupe_response(connection, body.client_event_id)
        if duplicate is not None: return duplicate
        event_rows = rows(connection, "SELECT id, ts, batch_id, jar_id, dest_location, LEAD(ts) OVER (PARTITION BY batch_id, COALESCE(jar_id, '') ORDER BY ts, id) AS end_ts FROM stage_events WHERE batch_id=?", (body.batch_id,))
        selected = [event for event in event_rows if one(connection, "SELECT to_stage FROM stage_events WHERE id=?", (event["id"],))["to_stage"] == body.stage]
        connection.execute("BEGIN IMMEDIATE")
        try:
            created = 0
            for event in selected:
                chamber = body.chamber or event["dest_location"]
                if not chamber: continue
                end_ts = event["end_ts"] or now_iso()
                duration_h = (datetime.fromisoformat(end_ts).timestamp() - datetime.fromisoformat(event["ts"]).timestamp()) / 3600
                connection.execute("DELETE FROM env_stage_summary WHERE batch_id=? AND jar_id IS ? AND stage=? AND chamber=?", (body.batch_id, event["jar_id"], body.stage, chamber))
                with get_sensor_db() as sensors:
                    raw = rows(sensors, "SELECT metric, value FROM raw_sensor_log WHERE chamber=? AND ts>=? AND ts<=? AND metric IN ('temp_c','rh_pct','co2_ppm','lux','vpd_kpa','airflow_ms')", (chamber, event["ts"], end_ts))
                by_metric: dict[str, list[float | None]] = {}
                for item in raw: by_metric.setdefault(item["metric"], []).append(item["value"])
                for metric, samples in by_metric.items():
                    present = [float(value) for value in samples if value is not None]
                    payload = {"batch_id": body.batch_id, "jar_id": event["jar_id"], "stage": body.stage, "chamber": chamber, "start_ts": event["ts"], "end_ts": end_ts, "duration_h": duration_h, "metric": metric, "min": min(present) if present else None, "max": max(present) if present else None, "avg": statistics.mean(present) if present else None, "stdev": statistics.stdev(present) if len(present) > 1 else None, "p10": percentile(present, .10) if present else None, "p90": percentile(present, .90) if present else None, "n_samples": len(present), "n_expected": len(samples), "completeness": len(present) / len(samples) if samples else None, "computed_ts": now_iso(), "data_source": "system"}
                    insert_row(connection, "env_stage_summary", payload); created += 1
            response = {"batch_id": body.batch_id, "stage": body.stage, "summaries_created": created}
            remember_response(connection, body.client_event_id, "/env/summarize", response)
            connection.commit(); return response
        except Exception:
            connection.rollback(); raise


@app.get("/compare", dependencies=[Depends(require_auth)])
def compare(strain: str | None = None, recipe_version: str | None = None, chamber: str | None = None, shelf: str | None = None, transfer_age_h_min: float | None = None, transfer_age_h_max: float | None = None, temp_avg_min: float | None = None, temp_avg_max: float | None = None, yield_min: float | None = None, yield_max: float | None = None) -> dict[str, Any]:
    sql = """SELECT b.*, d.h_inoculation_to_transfer AS transfer_age_h, y.dry_weight_g, y.biological_efficiency_pct,
             (SELECT avg FROM env_stage_summary e WHERE e.batch_id=b.batch_id AND e.metric='temp_c' ORDER BY computed_ts DESC LIMIT 1) AS temp_avg,
             (SELECT chamber FROM env_stage_summary e WHERE e.batch_id=b.batch_id ORDER BY computed_ts DESC LIMIT 1) AS summary_chamber
             FROM batch_master b LEFT JOIN stage_durations d ON d.batch_id=b.batch_id AND d.jar_id IS NULL
             LEFT JOIN harvest_yield y ON y.batch_id=b.batch_id AND y.jar_id IS NULL"""
    clauses, params = [], []
    for column, value in (("b.strain", strain), ("b.recipe_version", recipe_version)):
        if value is not None: clauses.append(f"{column}=?"); params.append(value)
    if chamber is not None: clauses.append("(b.current_location=? OR summary_chamber=?)"); params.extend([chamber, chamber])
    if shelf is not None: clauses.append("EXISTS (SELECT 1 FROM jar_master j WHERE j.batch_id=b.batch_id AND j.rack_shelf=?)"); params.append(shelf)
    for column, op, value in (("transfer_age_h", ">=", transfer_age_h_min), ("transfer_age_h", "<=", transfer_age_h_max), ("temp_avg", ">=", temp_avg_min), ("temp_avg", "<=", temp_avg_max), ("y.dry_weight_g", ">=", yield_min), ("y.dry_weight_g", "<=", yield_max)):
        if value is not None: clauses.append(f"{column} {op} ?"); params.append(value)
    if clauses: sql += " WHERE " + " AND ".join(clauses)
    with get_db() as connection: return {"results": rows(connection, sql, tuple(params))}


@app.get("/completeness/{batch_id}", dependencies=[Depends(require_auth)])
def completeness(batch_id: str) -> dict[str, Any]:
    tables = ["batch_master", "jar_master", "ingredient_lots", "stage_events", "env_snapshots", "env_stage_summary", "observations", "interventions", "harvest_yield", "photos", "costs"]
    outcome: dict[str, Any] = {}
    with get_db() as connection:
        if not one(connection, "SELECT 1 AS found FROM batch_master WHERE batch_id=?", (batch_id,)): raise HTTPException(404, detail="batch not found")
        for table in tables:
            table_columns = [item["name"] for item in connection.execute(f"PRAGMA table_info({table})") if item["name"] != "id"]
            data = rows(connection, f"SELECT * FROM {table} WHERE batch_id=?", (batch_id,))
            total = len(data) * len(table_columns)
            filled = sum(1 for item in data for column in table_columns if item.get(column) is not None and item.get(column) != "")
            outcome[table] = {"filled": filled, "total": total, "score": round(100 * filled / total, 2) if total else 0.0}
    return {"batch_id": batch_id, "tables": outcome}


def rank(values: list[float]) -> list[float]:
    sorted_pairs = sorted(enumerate(values), key=lambda item: item[1]); result = [0.0] * len(values); i = 0
    while i < len(sorted_pairs):
        j = i
        while j + 1 < len(sorted_pairs) and sorted_pairs[j + 1][1] == sorted_pairs[i][1]: j += 1
        average = (i + j + 2) / 2
        for k in range(i, j + 1): result[sorted_pairs[k][0]] = average
        i = j + 1
    return result


@app.get("/report/weekly", dependencies=[Depends(require_auth)])
def weekly_report(weeks: int = Query(1, ge=1, le=52)) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc).timestamp() - weeks * 7 * 86400
    with get_db() as connection:
        all_rows = rows(connection, "SELECT y.dry_weight_g AS yield_g, (SELECT avg FROM env_stage_summary e WHERE e.batch_id=y.batch_id AND e.metric='temp_c' ORDER BY computed_ts DESC LIMIT 1) AS temp_avg, y.ts FROM harvest_yield y")
    data = [item for item in all_rows if datetime.fromisoformat(item["ts"]).timestamp() >= cutoff]
    complete = [item for item in data if item["yield_g"] is not None and item["temp_avg"] is not None]
    correlations: list[dict[str, Any]] = []
    if len(complete) >= 5:
        x, y = [float(i["temp_avg"]) for i in complete], [float(i["yield_g"]) for i in complete]
        rx, ry = rank(x), rank(y); mx, my = statistics.mean(rx), statistics.mean(ry)
        rho = sum((a-mx)*(b-my) for a,b in zip(rx,ry)) / math.sqrt(sum((a-mx)**2 for a in rx)*sum((b-my)**2 for b in ry)) if len(set(rx)) > 1 and len(set(ry)) > 1 else 0.0
        correlations.append({"variables": ["temp_avg", "dry_weight_g"], "n": len(complete), "spearman_rho": rho, "p_value": None, "missing_data_pct": {"temp_avg": round(100*(len(data)-sum(i["temp_avg"] is not None for i in data))/len(data),2) if data else None, "dry_weight_g": round(100*(len(data)-sum(i["yield_g"] is not None for i in data))/len(data),2) if data else None}, "possible_confounders": ["strain", "recipe_version"], "inference": "insufficient for inference" if len(complete) < 12 else "hypothesis only; not established"})
    markdown = "# Weekly learning report\n\nCorrelation-only learning summary. " + ("No correlations met the minimum n of 5." if not correlations else "Results are hypotheses; association is not established.")
    return {"weeks": weeks, "correlations": correlations, "markdown": markdown}


@app.get("/export/{table}.csv", dependencies=[Depends(require_auth)])
def export_csv(table: str) -> Response:
    if table not in EXPORT_TABLES: raise HTTPException(404, detail="export is available only for the 8 named tables")
    with get_db() as connection:
        fieldnames = [item["name"] for item in connection.execute(f"PRAGMA table_info({EXPORT_TABLES[table]})")]
        values = rows(connection, f"SELECT * FROM {EXPORT_TABLES[table]}")
    stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
    writer.writeheader(); writer.writerows(values)
    return Response(stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{table}.csv"'})


@app.post("/labels", dependencies=[Depends(require_auth)])
def labels(body: LabelsRequest) -> dict[str, Any]:
    with get_db() as connection:
        duplicate = dedupe_response(connection, body.client_event_id)
        if duplicate is not None: return duplicate
        batch = one(connection, "SELECT batch_id FROM batch_master WHERE batch_id=?", (body.batch_id,))
        if not batch: raise HTTPException(404, detail="batch not found")
        queue = DATA_DIR / "label_queue"; queue.mkdir(parents=True, exist_ok=True)
        path = queue / f"{body.batch_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
        path.write_text(json.dumps({"batch_id": body.batch_id, "jar_ids": body.jar_ids}, indent=2), encoding="utf-8")
        response = {"file_path": str(path)}
        connection.execute("BEGIN IMMEDIATE"); remember_response(connection, body.client_event_id, "/labels", response); connection.commit()
        return response
