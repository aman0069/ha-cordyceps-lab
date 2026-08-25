# Cordyceps Lab Data Service

Batch, jar, stage, and observation store for the Cordyceps militaris lab.
FastAPI + SQLite. Listens on 8099 inside the container, published on host port
8189 by default.

Verified against HA Core 2026.8.3 / Supervisor 2026.07.5 / HAOS 18.2.

## Configuration

| Option | Required | What it does |
|---|---|---|
| `token` | yes | Bearer token for the API. The app refuses to start without it. Use a long random string and put the same value in `secrets.yaml` as `lds_token`. |
| `timezone` | yes | Lab local time. `Asia/Kolkata`. All timestamps are stored with this offset. |
| `ha_base_url` | yes | Where a scanned QR label sends the tablet. **Change it here, never on the labels.** |

The add-on Configuration tab also contains one field for every chamber entity:
temperature, humidity, CO2, lux, light, door, fan, humidifier, exhaust, and
airflow for `dark_room`, `light_room`, `fruit_1`, `fruit_2`, `drying`, and
`lab`. Enter the Home Assistant `entity_id` (for example,
`sensor.dark_room_temperature`) in the matching field. Leave unavailable or
unused devices empty; they are written as `none` and remain explicit missing
data.

Copy `homeassistant/packages/cm2_sensor_map.yaml` into `/config/packages/` once.
The add-on updates its entity values from the Configuration tab whenever it
starts, so the YAML package does not need manual entity edits.

Example:
```yaml
token: "a-long-random-string-you-generate"
timezone: Asia/Kolkata
ha_base_url: "http://homeassistant.local:8123"
```

## Why `ha_base_url` matters

Printed QR labels encode `http://<this-host>:8189/s/<token>` and nothing else.
This app then redirects to `<ha_base_url>/lab-scan?t=<token>`.

Home Assistant 2026.8 made the web server port editable in the UI and moved new
HAOS installs off `:8123`. If the labels embedded Home Assistant's own port, then
changing that port would silently break every QR code already stuck to a jar.
With the redirect, you edit one option here instead of reprinting.

If you change your Home Assistant address or port, update `ha_base_url` and
restart this app. Existing labels keep working.

## Storage

- `/data/cordyceps.db` — batch, jar, stage, observation, harvest, cost records.
- `/data/cordyceps_sensors.db` — raw sensor history, kept separate on purpose and
  joined to batches by chamber plus exact stage start/end timestamps.

Both live in the app's `/data` volume and are included in Home Assistant backups.

## Endpoints

`/health` and `/s/<token>` are unauthenticated — the first so the Supervisor
watchdog can poll it, the second because the tablet's browser follows it before
any login. Neither exposes lab data. Everything else needs
`Authorization: Bearer <token>`.

Full API and data contract: `docs/CONTRACT.md` in the repository root.

## Data rules enforced in code

- Missing sensor readings are stored as `NULL` with a `_src` of `missing`. Values
  are never invented, interpolated, defaulted, or zero-filled.
- `/events/transfer` returns HTTP 422 naming the missing fields rather than
  substituting defaults.
- Biological efficiency stays `NULL` unless both dry weight and substrate dry
  weight are present.
- Illegal stage transitions return 409 unless explicitly forced, and a forced
  transition is recorded as `forced=1`.

## Troubleshooting

**Won't start, log says no API token set** — set `token` in Configuration.

**Watchdog keeps restarting it** — check `http://<host>:8189/health` returns
`{"status":"ok"}`. If the port is taken, change the host port mapping.

**Scanning a label opens the wrong address** — `ha_base_url` is stale. Fix it
here; do not reprint labels.

**Cannot start, port is already in use** — another service already publishes the
host port. Port 8099 in particular is the Home Assistant app ingress convention
and is very often taken, which is why this app publishes 8189 instead. Run
`python3 tools/check_port.py` from the Terminal & SSH app to see what holds it,
then change the host port under Configuration -> Network. Home Assistant is
unaffected; it uses the container port. Reprint labels only if you had already
printed some, since the host port is encoded in each QR code.

**Build fails on a Raspberry Pi** — this image is multi-arch and builds from
`ghcr.io/home-assistant/base`. Make sure you are on Supervisor 2026.04.0 or
newer, which no longer injects `BUILD_FROM`.
