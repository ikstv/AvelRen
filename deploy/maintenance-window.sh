#!/usr/bin/env bash
# Publish a short, client-cacheable maintenance window before a planned outage.
#
# The public API only reads this file from its read-only /telemetry mount.  This
# host-side command is deliberately fail-closed: if the API cannot confirm the
# exact window, it does not wait for or authorize the disruptive next step.
set -euo pipefail

OUT_DIR=${AVELREN_MAINTENANCE_DIR:-/var/lib/avelren-telemetry}
OUT="$OUT_DIR/maintenance.json"
STATUS_URL=${AVELREN_STATUS_URL:-https://api.bordersignal.pp.ua/api/status}
DURATION_SECONDS=600
WAIT_SECONDS=75

usage() {
    echo "usage: $0 [--duration-seconds 120..900] [--wait-seconds 60..300]" >&2
    exit 2
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --duration-seconds) DURATION_SECONDS=${2:-}; shift 2 ;;
        --wait-seconds) WAIT_SECONDS=${2:-}; shift 2 ;;
        *) usage ;;
    esac
done

case "$DURATION_SECONDS" in ''|*[!0-9]*) usage ;; esac
case "$WAIT_SECONDS" in ''|*[!0-9]*) usage ;; esac
[ "$DURATION_SECONDS" -ge 120 ] && [ "$DURATION_SECONDS" -le 900 ] || usage
[ "$WAIT_SECONDS" -ge 60 ] && [ "$WAIT_SECONDS" -le 300 ] || usage
[ "$(id -u)" -eq 0 ] || { echo 'maintenance publisher must run as root' >&2; exit 1; }

mkdir -p "$OUT_DIR"
start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
end=$(date -u -d "+$DURATION_SECONDS seconds" +%Y-%m-%dT%H:%M:%SZ)
tmp=$(mktemp "$OUT_DIR/.maintenance.json.XXXXXX")
cleanup() { rm -f -- "$tmp"; }
trap cleanup EXIT HUP INT TERM

printf '{"starts_at":"%s","ends_at":"%s"}\n' "$start" "$end" >"$tmp"
chmod 0644 "$tmp"
mv -f -- "$tmp" "$OUT"

# The API must observe the exact state before a caller may stop it.  Python is
# available on the host as part of the deployed Python runtime; it avoids a
# fragile grep over JSON and keeps secrets out of process arguments and logs.
if ! curl --fail --silent --show-error --max-time 15 "$STATUS_URL" |
    START="$start" END="$end" python3 -c '
import json, os, sys
from datetime import datetime

def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

payload = json.load(sys.stdin)
window = payload.get("maintenance")
assert isinstance(window, dict)
assert parse(window["starts_at"]) == parse(os.environ["START"])
assert parse(window["ends_at"]) == parse(os.environ["END"])
'; then
    rm -f -- "$OUT"
    echo 'maintenance window was not confirmed by the public API; refusing outage' >&2
    exit 1
fi

echo "maintenance window confirmed until $end; waiting ${WAIT_SECONDS}s for client refresh"
sleep "$WAIT_SECONDS"
