#!/usr/bin/with-contenv bashio
# Entry point for both the Home Assistant app (options.json) and plain Docker
# Compose / systemd (environment variables). Environment always wins.
set -euo pipefail

opt() {
  # opt <json-key> <default>
  if [[ -f /data/options.json ]]; then
    python3 -c "import json,sys; print(json.load(open('/data/options.json')).get(sys.argv[1]) or sys.argv[2])" "$1" "$2"
  else
    printf '%s' "$2"
  fi
}

export LDS_TOKEN="${LDS_TOKEN:-$(opt token '')}"
export TZ="${TZ:-$(opt timezone 'Asia/Kolkata')}"
# Redirect target for printed QR labels (see /s/<token> in app/main.py).
export HA_BASE_URL="${HA_BASE_URL:-$(opt ha_base_url 'http://homeassistant.local:8123')}"
export LDS_DATA_DIR="${LDS_DATA_DIR:-/data}"
export AUTOCLAVE_DEFAULT_TEMPERATURE_C="${AUTOCLAVE_DEFAULT_TEMPERATURE_C:-$(opt autoclave_default_temperature_c '121')}"
export AUTOCLAVE_DEFAULT_PRESSURE_PSI="${AUTOCLAVE_DEFAULT_PRESSURE_PSI:-$(opt autoclave_default_pressure_psi '15')}"
export AUTOCLAVE_DEFAULT_DURATION_MIN="${AUTOCLAVE_DEFAULT_DURATION_MIN:-$(opt autoclave_default_duration_min '120')}"

# Apply entity IDs entered in the add-on Configuration tab to the HA package
# copied into /config. Empty values intentionally become `none`.
python3 - <<'PY'
import json
import re
from pathlib import Path

options_path = Path('/data/options.json')
package_path = Path('/config/packages/cm2_sensor_map.yaml')
if options_path.exists() and package_path.exists():
  options = json.loads(options_path.read_text())
  text = package_path.read_text()
  for key, raw_value in options.items():
    if not key.endswith('_entity'):
      continue
    value = str(raw_value or 'none').strip()
    if value != 'none' and not re.fullmatch(r'[a-z_]+\.[a-z0-9_]+', value):
      raise SystemExit(f'Invalid entity ID for {key}: {value}')
    pattern = rf'^(\s+{re.escape(key)}:\s+&\S+\s+)(\S+)(\s+# EDIT_ME\s*)$'
    text, count = re.subn(pattern, rf'\g<1>{value}\g<3>', text, count=1, flags=re.MULTILINE)
    if count != 1:
      print(f'WARNING: {key} is not present in {package_path}', flush=True)
  package_path.write_text(text)
PY

if [[ -z "${LDS_TOKEN}" ]]; then
  echo "FATAL: no API token set. Set 'token' in the app configuration (or LDS_TOKEN)." >&2
  echo "Refusing to start an unauthenticated lab data service." >&2
  exit 1
fi

echo "Cordyceps LDS starting | TZ=${TZ} | data=${LDS_DATA_DIR} | label redirect -> ${HA_BASE_URL}"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8099
