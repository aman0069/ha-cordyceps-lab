# ha-cordyceps-lab

Home Assistant add-on repository plus the YAML, dashboards, and tooling for
*Cordyceps militaris* batch tracking: QR-driven jar identity, a full cultivation
stage machine, and AI-ready structured records.

Verified against **HA Core 2026.8.3 · Supervisor 2026.07.5 · HAOS 18.2**.

`docs/CONTRACT.md` is the authoritative spec. Read it before changing anything.

---

## Layout

```
cordyceps_lds/        The app (add-on). Supervisor installs this.
homeassistant/        packages/, dashboards/, lab-scan.md — copy into /config
tools/                make_labels.py, learning_report.py, seed_demo.py
docs/CONTRACT.md      Schema, IDs, API, entity naming, analysis rules
samples/              Real label sheet + generated learning report
```

Only `cordyceps_lds/` contains a `config.yaml`, so Supervisor ignores everything
else. Do not add another file named `config.yaml` anywhere in this repo.

---

## 1. Install the app

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add:
   ```
   https://github.com/aman0069/ha-cordyceps-lab
   ```
2. **Cordyceps Lab Data Service** appears in the store. Install it.
3. In **Configuration** set:
   ```yaml
   token: "a-long-random-string-you-generate"
   timezone: Asia/Kolkata
   ha_base_url: "http://homeassistant.local:8123"
   ```
4. Start it. Enable **Start on boot** and **Watchdog**.

The app builds on-device from `ghcr.io/home-assistant/base:3.24-2026.08.0`.

**Supported architectures: `amd64` and `aarch64` only.** That is the full set the
Home Assistant base image publishes; there is no 32-bit ARM build, so this will
not install on a Raspberry Pi 3 or older, or on a 32-bit OS image.

If you change the pinned base image or the `arch:` list, run this first:
```bash
python tools/check_base_image.py
```
It confirms the tag actually exists in the registry and that every declared
architecture is really published. Base image tags are
`<alpine-version>-<build-version>` (e.g. `3.24-2026.08.0`) and do **not** track
the Home Assistant Core version — guessing one produces an install-time
`not found` and nothing else. CI runs this check on every push and weekly.

Non-HAOS alternative: `docker compose up -d` or the systemd unit, both in
`cordyceps_lds/`.

### Point Home Assistant at it

`/config/secrets.yaml`:
```yaml
lds_base_url: "http://a0d7b954-cordyceps_lds:8099"   # app internal hostname
lds_token: "the-same-long-random-string"
```

## 2. Install the Home Assistant side

1. `/config/configuration.yaml` needs:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
2. Copy `homeassistant/packages/*.yaml` into `/config/packages/`.
3. **Edit `cm2_sensor_map.yaml` only.** Point each `# EDIT_ME` line at your real
   ESPHome entity. Where a sensor does not exist, set it to `none` — the payload
   then emits `null` with `_src: missing`, never a zero or a last-known value.
4. Add the three files in `homeassistant/dashboards/` as Lovelace views.
5. Restart. `sensor.cm2_lds_status` should read `ok`.
6. Wire the tablet scanner per `homeassistant/lab-scan.md`.

All template entities use the modern `template:` syntax, so nothing here is
affected by the 2026.6 removal of the legacy `platform: template` form.

## 3. Print labels

```bash
python tools/make_labels.py --lds http://<host>:8099 --token XXX \
       --batch AC-20260821-01 --output sheet.pdf
```

Presets `a4_24up` (63.5 × 33.9 mm, Avery L7159) and `a4_65up_small`. Each sheet
leads with a batch master label, then one per jar. Every rendered QR is decoded
back from the page image before the file is written.

**The QR encodes only** `http://<lds-host>:8099/s/<22-char opaque token>`. No
strain, dates, recipe, weights, or operator. The app redirects that to
`<ha_base_url>/lab-scan?t=<token>`.

> Labels are permanent; Home Assistant's port is not. HA 2026.8 made the web
> server port editable in the UI and moved new HAOS installs off `:8123`. The
> redirect means changing your HA address is a one-line app option edit instead
> of reprinting every jar. Use `--link-mode direct` only if you accept that risk.

Unknown dates print as `____________`. They are never guessed.

## 4. Daily use

- **Autoclave logging creates the batch.** `POST /batches` mints
  `AC-YYYYMMDD-NN` plus `-J001…-JNNN` and one opaque token each.
- **Scanning never writes anything.** Scan → resolve → the tablet shows
  `AC-20260821-01-J007 · CM-Comm-A · dark_incubation · Dark Room` → you tap
  Confirm. The confirm arm expires after 120 s so a stale scan can't be committed.
- **Transfer Dark → Light** blocks and names the exact missing fields rather than
  defaulting them, then snapshots temperature, RH, CO₂, VPD, light state, lux,
  photoperiod, door, fan, humidifier, exhaust and airflow at the transfer instant,
  each with its own source flag.
- **Stage durations** come from the `stage_durations` SQL view and are `NULL`
  wherever an endpoint event is missing.

## 5. Analysis rules, enforced in code

- Correlations and hypotheses only. `learning_report.py` carries a
  `FORBIDDEN_WORDS` list and raises rather than emit a causal sentence.
- Every correlation prints n, Spearman rho, p, missing % for both variables, and
  at least two named plausible confounders.
- `n < 5` suppressed; `n < 12` labelled **insufficient for inference**.
- Proposals render as experiment cards: hypothesis, the single changed variable,
  control batch, computed minimum sample size, success metric, duration, risks,
  `approved_by_aman: false`.
- Nothing changes a setpoint, ever.

```bash
python tools/learning_report.py --db /path/to/cordyceps.db --out report.md
```

## 6. Exports

`GET /export/<table>.csv` for `batch_master`, `jar_master`, `stage_events`,
`observations`, `env_stage_summary`, `harvest_yield`, `photos`, `interventions`.
Missing values export as empty strings, never `0`.

---

## Testing

```bash
cd cordyceps_lds && python -m pytest tests -q
```

Covers batch + 20-jar minting, token uniqueness, resolve, illegal transition
rejected then forced, incomplete transfer rejected with 422, missing sensor value
stored as `NULL`/`missing` and not zero-filled, biological efficiency `NULL`
without substrate weight, and all 8 CSV exports.
