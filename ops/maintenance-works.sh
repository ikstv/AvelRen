#!/usr/bin/env bash
# Publish a verified ordinary maintenance window before planned work.
# This script does not stop, restart, or otherwise mutate any service.
set -euo pipefail
umask 077

OUT_DIR="${AVELREN_MAINTENANCE_DIR:-/var/lib/avelren-telemetry}"
OUT="$OUT_DIR/maintenance.json"
STATUS_URL="${AVELREN_STATUS_URL:-https://api.bordersignal.pp.ua/api/status}"
DURATION_SECONDS=""
WAIT_SECONDS=60

usage() {
  echo "usage: $0 --duration-seconds 120..21600" >&2
  exit 64
}

while (($#)); do
  case "$1" in
    --duration-seconds) DURATION_SECONDS="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ "$DURATION_SECONDS" =~ ^[0-9]+$ ]] || usage
(( DURATION_SECONDS >= 120 && DURATION_SECONDS <= 21600 )) || usage

if [[ $(id -u) -ne 0 ]]; then
  echo "must run as root to publish the production maintenance signal" >&2
  exit 77
fi

install -d -m 0755 "$OUT_DIR"
start_epoch=$(date -u +%s)
starts_at=$(date -u -d "@${start_epoch}" +%Y-%m-%dT%H:%M:%SZ)
ends_at=$(date -u -d "@$((start_epoch + DURATION_SECONDS))" +%Y-%m-%dT%H:%M:%SZ)
temporary=$(mktemp "$OUT_DIR/.maintenance.json.XXXXXX")
published=false
wait_completed=false

cleanup() {
  rm -f "$temporary"
  if [[ "$published" == true && "$wait_completed" != true ]]; then
    rm -f "$OUT"
  fi
}
trap cleanup EXIT INT TERM

printf '{"starts_at":"%s","ends_at":"%s"}\n' "$starts_at" "$ends_at" >"$temporary"
chmod 0644 "$temporary"
mv -f "$temporary" "$OUT"
published=true

response=$(curl --fail --silent --show-error --max-time 15 "$STATUS_URL") || {
  echo "status endpoint did not confirm maintenance; refusing planned work" >&2
  exit 69
}

python3 - "$starts_at" "$ends_at" "$response" <<'PY' || {
import json
import sys
from datetime import UTC, datetime

starts_at, ends_at, response = sys.argv[1:]
maintenance = json.loads(response).get("maintenance")
if not isinstance(maintenance, dict) or set(maintenance) != {"starts_at", "ends_at"}:
    raise SystemExit(1)


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone is required")
    return parsed.astimezone(UTC)


if utc(maintenance["starts_at"]) != utc(starts_at) or utc(maintenance["ends_at"]) != utc(ends_at):
    raise SystemExit(1)
PY
  echo "status endpoint did not return the published maintenance window; refusing planned work" >&2
  exit 69
}

echo "maintenance window confirmed by $STATUS_URL; waiting ${WAIT_SECONDS}s before planned work"
sleep "$WAIT_SECONDS"
wait_completed=true
