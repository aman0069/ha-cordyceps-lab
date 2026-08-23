#!/usr/bin/env bash
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

if [[ -z "${LDS_TOKEN}" ]]; then
  echo "FATAL: no API token set. Set 'token' in the app configuration (or LDS_TOKEN)." >&2
  echo "Refusing to start an unauthenticated lab data service." >&2
  exit 1
fi

echo "Cordyceps LDS starting | TZ=${TZ} | data=${LDS_DATA_DIR} | label redirect -> ${HA_BASE_URL}"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8099
