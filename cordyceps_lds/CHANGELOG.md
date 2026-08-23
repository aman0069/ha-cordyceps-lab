# Changelog

## 2.1.0

Compatibility pass against HA Core 2026.8.3 / Supervisor 2026.07.5 / HAOS 18.2.

### Fixed
- **Multi-arch build.** The Dockerfile pinned `amd64-base-python`, which made the
  app uninstallable on aarch64 hosts. Now builds from the multi-arch
  `ghcr.io/home-assistant/base` with an explicit pinned tag.
- **Supervisor 2026.04.0 build contract.** `BUILD_FROM` is no longer injected and
  `build.yaml` is no longer read. The base image is declared with an explicit
  `FROM`, and the required `io.hass.*` labels are set in the Dockerfile.
- **`arch` list.** Was `amd64` only; now amd64, aarch64, armv7, armhf, i386.
- `/health` no longer requires the bearer token, so the Supervisor watchdog can
  actually poll it. Added `watchdog:` to the app config.
- `/env/summarize` accepts an omitted `stage` and summarizes every stage present
  for the batch.

### Added
- **`GET /s/<token>`** — unauthenticated 302 redirect to
  `<ha_base_url>/lab-scan?t=<token>`. Printed QR labels now point here instead of
  at Home Assistant directly, so changing the HA port or hostname no longer
  invalidates labels already stuck to jars.
- `ha_base_url` app option driving that redirect.
- `run.sh` refuses to start without a token instead of running the service open.

### Changed
- QR payload is now `http://<lds-host>:8099/s/<token>`. The old direct form is
  still available via `make_labels.py --link-mode direct`.

## 2.0.0

Initial release. Batch/jar identity, opaque scan tokens, stage machine,
env snapshots, stage summaries, observations, interventions, harvest, costs,
photos, CSV export, batch comparison, completeness scoring, weekly correlation
report.
