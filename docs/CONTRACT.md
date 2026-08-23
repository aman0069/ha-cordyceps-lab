# Cordyceps Lab v2 — Data & Interface Contract (AUTHORITATIVE)

Everything built for this system MUST conform to this file. Do not rename fields,
endpoints, or entities. If something is missing, add it here in a comment first.

Author context: Cordyceps militaris lab, New Delhi. Home Assistant OS + HACS
(Mushroom, ApexCharts, plus we will add `qrcode` via custom card or camera scan).
Existing v1 CSV logger writes `/config/lab_logs/cordyceps_activity_log.csv` and
must keep working untouched.

---

## 0. Components

| Component | Path | Role |
|---|---|---|
| Lab Data Service (LDS) | `addon/` | FastAPI + SQLite. Owns all records. REST API. CSV export. |
| HA package v2 | `ha/packages/cordyceps_batch_v2.yaml` | Helpers, scripts, automations, rest_commands, template sensors |
| Dashboards | `ha/dashboards/*.yaml` | Batch Timeline, Transfer to Light queue, AI & Analysis |
| Label generator | `tools/make_labels.py` | Print-ready PDF + PNG label sheets |
| Weekly learning report | `tools/learning_report.py` | Correlation-only report, no causal claims |

LDS base URL used by HA: `http://a0d7b954-cordyceps-lds:8099` (add-on) or
`http://192.168.1.50:8099` (docker). Configurable in HA via
`input_text.lds_base_url` is NOT used — it is a single `secrets.yaml` key:
`lds_base_url`. Auth: static bearer token from `secrets.yaml` key `lds_token`.

---

## 1. Identifiers

- **Batch ID**: `AC-YYYYMMDD-NN`
  - `AC` = autoclave-origin. `YYYYMMDD` = autoclave date (lab local, Asia/Kolkata).
  - `NN` = zero-padded sequence of autoclave loads that day, starting `01`.
  - Created at **autoclave logging time**, not at inoculation.
  - Regex: `^AC-\d{8}-\d{2}$`
- **Jar ID**: `<BatchID>-J###`, e.g. `AC-20260821-01-J001`, 1-based, zero-padded 3.
  - Regex: `^AC-\d{8}-\d{2}-J\d{3}$`
- **Opaque scan token**: 22-char URL-safe base64 (`secrets.token_urlsafe(16)`).
  - One token per Batch and per Jar. Stored in `scan_token` column.
  - This is the ONLY thing encoded in the QR payload.

### QR payload (revised in v2.1 — see rationale)
```
http://<LDS_HOST>:8099/s/<scan_token>
```
Default: `http://homeassistant.local:8099/s/<token>`
- Contains **no** strain, recipe, dates, weights, operator, or any lab data.
- Token is opaque and resolvable to real data only by LDS, and only with the
  bearer token via `/resolve`.
- `GET /s/<token>` is unauthenticated and 302-redirects to
  `<ha_base_url>/lab-scan?t=<token>`, where `ha_base_url` is an LDS app option.
- **Why the indirection:** printed labels are permanent. HA 2026.8 makes the
  Home Assistant web server port user-editable and moved new HAOS installs off
  `:8123`. Embedding HA's host:port in the QR would mean that changing the HA
  address silently invalidates every label already stuck to a jar. Pointing at
  the LDS (stable port 8099) turns an HA address change into a one-line option
  edit instead of a reprint.
- Unknown tokens still redirect, so probing `/s/` reveals nothing about which
  tokens exist.
- Legacy direct form `<HA>/lab-scan?t=<token>` is still available via
  `make_labels.py --link-mode direct`. Not recommended.

---

## 2. Stages (closed vocabulary — never free text)

`autoclaved`, `inoculated`, `dark_incubation`, `transferred_to_light`,
`primordia_observed`, `fruiting`, `harvested`, `dried`, `packaged`,
`discarded`, `contaminated`

Legal transitions (LDS enforces, warns but allows override with `force=true`):
```
autoclaved          -> inoculated | discarded | contaminated
inoculated          -> dark_incubation | contaminated | discarded
dark_incubation     -> transferred_to_light | contaminated | discarded
transferred_to_light-> primordia_observed | contaminated | discarded
primordia_observed  -> fruiting | contaminated | discarded
fruiting            -> harvested | contaminated | discarded
harvested           -> dried | discarded
dried               -> packaged | discarded
packaged            -> (terminal)
discarded           -> (terminal)
contaminated        -> discarded | (terminal)
```

### Scan-loggable actions (tablet)
`inoculation`, `transfer_dark_to_light`, `visual_inspection`, `contamination`,
`harvest`, `cleaning`, `discard`, `final_yield`

---

## 3. Missing data rule (HARD REQUIREMENT)

- Never invent, interpolate, default, or zero-fill a missing value.
- Unavailable sensor readings are written as SQL `NULL` and CSV empty string `""`.
- Every sensor-derived field has a sibling `*_src` column with one of:
  `sensor`, `manual`, `qr_scan`, `missing`.
- If HA reports `unknown` / `unavailable` / `none` / `""`, LDS stores `NULL` and
  sets `*_src = 'missing'`. LDS never substitutes a last-known value.
- Aggregations (min/max/avg/stdev) exclude NULLs and record `n_samples` and
  `n_expected`; `completeness = n_samples / n_expected` (NULL if `n_expected` unknown).

---

## 4. SQLite schema (file: `/data/cordyceps.db`)

All timestamps: ISO-8601 with offset, Asia/Kolkata, e.g. `2026-08-21T21:39:00+05:30`.
Every table carries: `id INTEGER PK`, `ts TEXT NOT NULL`, `operator TEXT`,
`data_source TEXT CHECK(data_source IN ('manual','qr_scan','sensor','import','system'))`.

### 4.1 `batch_master`
```
batch_id TEXT PRIMARY KEY            -- AC-YYYYMMDD-NN
scan_token TEXT UNIQUE NOT NULL
created_ts TEXT NOT NULL
parent_batch_id TEXT                 -- FK batch_master, nullable
strain TEXT NOT NULL                 -- dropdown
culture_generation TEXT              -- G0..G6 dropdown
culture_source TEXT                  -- dropdown: agar_slant|LC_master|LC_working|G2G|spore_syringe|purchased
inoculation_method TEXT              -- dropdown: LC_syringe|agar_wedge|grain_to_grain|spore_syringe
recipe_version TEXT NOT NULL         -- e.g. R-2026.3
rice_g_per_jar REAL
broth_ml_per_jar REAL
water_source TEXT                    -- RO|distilled|municipal_boiled|municipal
fill_weight_g REAL
jar_type TEXT                        -- PP400|glass_500|glass_1000|bag_...
lid_filter_type TEXT                 -- synthetic_filter_disc|micropore_tape|tyvek|breather_lid
sterilization_profile TEXT           -- e.g. 121C_15psi_120min
autoclave_id TEXT
autoclave_temp_c REAL
autoclave_pressure_psi REAL
autoclave_hold_min INTEGER
autoclave_cycle_result TEXT          -- normal|under_pressure|leak_vent|aborted
autoclave_deviations TEXT
jar_count_planned INTEGER
current_stage TEXT NOT NULL
current_location TEXT
notes TEXT
operator TEXT
data_source TEXT
```

### 4.2 `jar_master`
```
jar_id TEXT PRIMARY KEY              -- AC-...-J###
batch_id TEXT NOT NULL REFERENCES batch_master
scan_token TEXT UNIQUE NOT NULL
jar_index INTEGER NOT NULL
current_stage TEXT NOT NULL
current_location TEXT                -- chamber
rack_shelf TEXT                      -- e.g. F1-R2-S3
fill_weight_g REAL
status TEXT                          -- active|contaminated|discarded|harvested|packaged
created_ts TEXT NOT NULL
notes TEXT
```

### 4.3 `ingredient_lots`  (many per batch — lot numbers are per-ingredient)
```
id, batch_id, ingredient TEXT, lot_number TEXT, quantity REAL, unit TEXT,
supplier TEXT, expiry TEXT, ts, operator, data_source
```
Ingredient dropdown: `brown_rice`, `dextrose`, `yeast_extract`, `peptone`,
`MgSO4`, `K2HPO4`, `KH2PO4`, `Tween80`, `water`, `other`.

### 4.4 `stage_events`   (the timeline spine)
```
id, ts, batch_id, jar_id (nullable = whole batch), from_stage, to_stage,
action TEXT,                          -- see scan-loggable actions
source_location TEXT, dest_location TEXT, rack_shelf TEXT,
reason TEXT, colonization_pct REAL, moisture_level TEXT,
env_snapshot_id INTEGER REFERENCES env_snapshots,
equipment_id TEXT, notes TEXT, operator, data_source, forced INTEGER DEFAULT 0
```

### 4.5 `env_snapshots`  (point-in-time, captured at event moment)
```
id, ts, batch_id, jar_id, chamber TEXT,
temp_c REAL, temp_c_src TEXT,
rh_pct REAL, rh_pct_src TEXT,
co2_ppm REAL, co2_ppm_src TEXT,
vpd_kpa REAL, vpd_kpa_src TEXT,          -- computed from temp+rh ONLY if both present
light_state TEXT, light_state_src TEXT,  -- on|off
lux REAL, lux_src TEXT,
photoperiod TEXT, photoperiod_src TEXT,  -- e.g. "12/12"
door_state TEXT, door_state_src TEXT,    -- open|closed
fan_state TEXT, fan_state_src TEXT,
humidifier_state TEXT, humidifier_state_src TEXT,
exhaust_state TEXT, exhaust_state_src TEXT,
airflow_ms REAL, airflow_ms_src TEXT,
raw_json TEXT                            -- verbatim HA payload for audit
```

### 4.6 `env_stage_summary`  (min/max/avg/stdev per stage, computed by LDS)
```
id, batch_id, jar_id, stage TEXT, chamber TEXT,
start_ts TEXT, end_ts TEXT, duration_h REAL,
metric TEXT,                              -- temp_c|rh_pct|co2_ppm|lux|vpd_kpa|airflow_ms
min REAL, max REAL, avg REAL, stdev REAL, p10 REAL, p90 REAL,
n_samples INTEGER, n_expected INTEGER, completeness REAL,
computed_ts TEXT, data_source TEXT
```

### 4.7 `observations`  (daily or scan-based visual scores)
```
id, ts, batch_id, jar_id, stage TEXT,
colonization_pct REAL,                    -- 0-100 step 5
mycelial_density TEXT,                    -- sparse|moderate|dense|very_dense
mycelial_color TEXT,                      -- white|cream|pale_yellow|orange|deep_orange|discolored
condensation_level TEXT,                  -- none|light|moderate|heavy|pooling
substrate_dryness TEXT,                   -- wet|moist|ideal|dry|cracked
contamination_status TEXT,                -- none|suspected|confirmed
contamination_type TEXT,                  -- trichoderma|bacterial_wetspot|aspergillus|penicillium|mucor_cobweb|yeast_sour|unknown|none
primordia_count INTEGER,
fruiting_body_count INTEGER,
avg_height_mm REAL,
morphology_score INTEGER,                 -- 1-5
photo_id INTEGER REFERENCES photos,
notes TEXT, operator, data_source, env_snapshot_id
```

### 4.8 `interventions`
```
id, ts, batch_id, jar_id, intervention_type TEXT,
-- misting|ventilation_adjust|lighting_change|cleaning|movement|recipe_change|
-- equipment_fault|corrective_action|calibration|other
detail TEXT, setpoint_before TEXT, setpoint_after TEXT,
equipment_id TEXT, duration_min REAL, notes TEXT,
operator, data_source, env_snapshot_id
```

### 4.9 `harvest_yield`
```
id, ts, batch_id, jar_id,
fresh_weight_g REAL, dry_weight_g REAL,
substrate_dry_g REAL,                      -- needed for BE; NULL if unknown
biological_efficiency_pct REAL,            -- NULL unless both inputs present
usable_jars INTEGER, rejected_jars INTEGER, contaminated_jars INTEGER,
grade TEXT,                                -- A|B|C|reject
drying_method TEXT,                        -- freeze_dry|dehydrator|oven|air
drying_temp_c REAL, drying_hours REAL,
packaging_date TEXT, package_type TEXT,
notes TEXT, operator, data_source
```
`biological_efficiency_pct = 100 * dry_weight_g / substrate_dry_g` — computed ONLY
when both are non-NULL; otherwise NULL.

### 4.10 `photos`
```
id, ts, batch_id, jar_id, stage TEXT, file_path TEXT, thumb_path TEXT,
caption TEXT, operator, data_source
```

### 4.11 `costs`
```
id, ts, batch_id, category TEXT,           -- ingredient|consumable|electricity|labor|waste|sale
item TEXT, quantity REAL, unit TEXT, unit_cost_inr REAL, total_inr REAL,
labor_minutes REAL, kwh REAL, equipment_id TEXT, notes TEXT, operator, data_source
```

### 4.12 `stage_durations` (view, derived from stage_events)
```
batch_id, jar_id,
h_autoclave_to_inoculation, h_inoculation_to_transfer, h_transfer_to_primordia,
h_primordia_to_harvest, h_total_cycle
```
NULL where either endpoint event is missing.

### 4.13 `raw_sensor_log` (separate, high-volume, linked by timestamp)
```
id, ts, chamber, entity_id, metric, value REAL, unit TEXT
```
Stored in a SEPARATE database file `/data/cordyceps_sensors.db`, joined to batches
by `chamber` + exact stage `start_ts`/`end_ts` from `stage_events`. Never merged
into batch tables.

---

## 5. LDS REST API

All endpoints require `Authorization: Bearer <lds_token>`.
All responses JSON. All mutating endpoints are idempotent on `client_event_id`
(UUID sent by HA) to survive tablet double-taps.

```
GET  /health
POST /batches                        -> create batch at autoclave logging; body may omit
                                        batch_id (LDS assigns next NN for the date);
                                        creates N jars if jar_count_planned > 0
GET  /batches?stage=&strain=&chamber=&limit=
GET  /batches/{batch_id}
PATCH /batches/{batch_id}
GET  /batches/{batch_id}/timeline    -> stages, events, durations, latest photo, env history
GET  /jars/{jar_id}
GET  /resolve?t=<scan_token>         -> {kind: batch|jar, batch_id, jar_id, strain,
                                        current_stage, current_location, display_name,
                                        allowed_actions:[...]}   <-- used by /lab-scan
POST /events                         -> generic stage/action event (see 4.4)
POST /events/transfer                -> the big Dark->Light action, validates required fields
POST /observations
POST /interventions
POST /harvest
POST /costs
POST /photos
POST /env/snapshot                   -> store env_snapshots row, returns id
POST /env/summarize                  -> recompute env_stage_summary for a batch/stage
GET  /compare?strain=&recipe_version=&chamber=&shelf=&transfer_age_h_min=&
              transfer_age_h_max=&temp_avg_min=&temp_avg_max=&yield_min=&yield_max=
GET  /completeness/{batch_id}        -> per-table field completeness score 0-100
GET  /report/weekly?weeks=1          -> correlation-only learning report (JSON + markdown)
GET  /export/{table}.csv             -> Batch Master, Jar Master, Stage Events,
                                        Observations, Environmental Stage Summaries,
                                        Harvest & Yield, Photos, Interventions
POST /labels                         -> queue label sheet generation, returns file path
```

`POST /events/transfer` REQUIRED body fields (reject 422 if absent, do NOT default):
`batch_id` or `jar_ids[]`, `ts`, `operator`, `source_location`, `dest_chamber`,
`rack_shelf`, `reason`, `colonization_pct`, `moisture_level`, `env` (object),
optional `notes`, `client_event_id`.

---

## 6. HA entity naming (v2 — all prefixed `cm2_` to avoid clashing with v1)

```
input_text.cm2_scan_payload          # tablet scanner writes token here
input_text.cm2_selected_id           # resolved Batch/Jar ID
input_text.cm2_selected_name         # human readable for confirmation
input_text.cm2_rack_shelf
input_text.cm2_notes
input_text.cm2_reason
input_select.cm2_pending_action      # none|inoculation|transfer_dark_to_light|...
input_select.cm2_operator
input_select.cm2_dest_chamber
input_select.cm2_source_location
input_select.cm2_moisture_level
input_select.cm2_strain
input_select.cm2_recipe_version
input_number.cm2_colonization_pct    # 0-100 step 5
input_boolean.cm2_scan_confirm_armed # must be ON before any scan action commits
input_datetime.cm2_event_ts
sensor.cm2_lds_status
sensor.cm2_selected_batch_stage
sensor.cm2_transfer_queue_count
script.cm2_resolve_scan
script.cm2_confirm_and_commit
script.cm2_transfer_dark_to_light
script.cm2_env_payload               # builds the env JSON with *_src flags
rest_command.cm2_post_event / cm2_post_transfer / cm2_resolve / ...
```

**Safeguard flow (mandatory):**
scan -> `cm2_resolve_scan` -> populates `cm2_selected_name` -> dashboard shows a
confirm card with the name + action -> user taps Confirm -> `cm2_confirm_and_commit`
posts to LDS. Nothing is written on scan alone. `cm2_scan_confirm_armed` auto-resets
after 120 s and after each commit.

**Sensor entity mapping** lives in ONE place: `ha/packages/cm2_sensor_map.yaml`
as a `variables:`-style script + comments marked `EDIT_ME`. Chambers:
`dark_room`, `light_room`, `fruit_1`, `fruit_2`, `drying`, `lab`.

---

## 7. Analysis rules (HARD REQUIREMENTS)

- The weekly learning report emits **correlations and hypotheses only**. Forbidden
  words in generated output: "causes", "caused by", "because of", "proves",
  "will increase", "guarantees". Use "associated with", "co-occurs with",
  "hypothesis", "not established".
- Every stated correlation MUST print: `n`, Spearman rho + p-value, missing-data %
  for both variables, and at least two named possible confounders.
- Report suppresses any correlation with `n < 5` and labels `n < 12` as
  "insufficient for inference".
- No automatic setpoint changes, ever. Proposed changes are rendered as an
  **experiment card**: hypothesis, single changed variable, control batch,
  sample size needed, success metric, duration, risks, and an explicit
  "Requires Aman's approval" field set to `false` until approved.
