#!/usr/bin/env bash
# Publish a short, verified maintenance window before a planned host operation.
# This script does not restart anything itself.
set -euo pipefail

OUT_DIR="${AVELREN_MAINTENANCE_DIR:-/var/lib/avelren-telemetry}"
OUT="$OUT_DIR/maintenance.json"
STATUS_URL="${AVELREN_STATUS_URL:-https://api.bordersignal.pp.ua/api/status}"
BOOT_ID_FILE="${AVELREN_BOOT_ID_FILE:-/proc/sys/kernel/random/boot_id}"
DURATION_SECONDS=600
WAIT_SECONDS=75
POST_RESTART_MARGIN_SECONDS=120

usage() {
  echo "usage: $0 [--duration-seconds 120..900] [--wait-seconds 60..300]; duration must leave 120s after wait" >&2
  exit 64
}

while (($#)); do
  case "$1" in
    --duration-seconds) DURATION_SECONDS="${2:-}"; shift 2 ;;
    --wait-seconds) WAIT_SECONDS="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ "$DURATION_SECONDS" =~ ^[0-9]+$ ]] || usage
[[ "$WAIT_SECONDS" =~ ^[0-9]+$ ]] || usage
(( DURATION_SECONDS >= 120 && DURATION_SECONDS <= 900 )) || usage
(( WAIT_SECONDS >= 60 && WAIT_SECONDS <= 300 )) || usage
(( DURATION_SECONDS - WAIT_SECONDS >= POST_RESTART_MARGIN_SECONDS )) || usage

if [[ $(id -u) -ne 0 ]]; then
  echo "must run as root to publish the production maintenance signal" >&2
  exit 77
fi

install -d -m 0755 "$OUT_DIR"
[[ -r "$BOOT_ID_FILE" ]] || {
  echo "cannot read boot identity; refusing planned reboot signal" >&2
  exit 69
}
boot_id=$(tr -d '\r\n' <"$BOOT_ID_FILE")
[[ "$boot_id" =~ ^[[:alnum:]_.-]{1,128}$ ]] || {
  echo "invalid boot identity; refusing planned reboot signal" >&2
  exit 69
}
starts_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
restarts_at=$(date -u -d "+${WAIT_SECONDS} seconds" +%Y-%m-%dT%H:%M:%SZ)
ends_at=$(date -u -d "+${DURATION_SECONDS} seconds" +%Y-%m-%dT%H:%M:%SZ)
temporary=$(mktemp "$OUT_DIR/.maintenance.json.XXXXXX")
cleanup() { rm -f "$temporary"; }
trap cleanup EXIT
printf '{"starts_at":"%s","restarts_at":"%s","ends_at":"%s","boot_id":"%s"}\n' \
  "$starts_at" "$restarts_at" "$ends_at" "$boot_id" >"$temporary"
chmod 0644 "$temporary"
mv -f "$temporary" "$OUT"

response=$(curl --fail --silent --show-error --max-time 15 "$STATUS_URL") || {
  rm -f "$OUT"
  echo "status endpoint did not confirm maintenance; refusing planned outage" >&2
  exit 69
}

python3 - "$starts_at" "$restarts_at" "$ends_at" "$response" <<'PY' || {
import json
import sys
from datetime import UTC, datetime

starts_at, restarts_at, ends_at, response = sys.argv[1:]
maintenance = json.loads(response).get("maintenance")
if not isinstance(maintenance, dict) or set(maintenance) != {"starts_at", "restarts_at", "ends_at"}:
    raise SystemExit(1)


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone is required")
    return parsed.astimezone(UTC)


if (utc(maintenance["starts_at"]) != utc(starts_at)
        or utc(maintenance["restarts_at"]) != utc(restarts_at)
        or utc(maintenance["ends_at"]) != utc(ends_at)):
    raise SystemExit(1)
PY
  rm -f "$OUT"
  echo "status endpoint did not return the published maintenance window; refusing planned outage" >&2
  exit 69
}

echo "maintenance window confirmed by $STATUS_URL; waiting ${WAIT_SECONDS}s before host operation"
sleep "$WAIT_SECONDS"
