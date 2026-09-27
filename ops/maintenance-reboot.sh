#!/usr/bin/env bash
# Reboot only after maintenance-window.sh has published and verified the badge.
set -euo pipefail

OUT_DIR="${AVELREN_MAINTENANCE_DIR:-/var/lib/avelren-telemetry}"
if [[ $(id -u) -ne 0 ]]; then
  echo "must run as root to perform a planned production reboot" >&2
  exit 77
fi
command -v flock >/dev/null || {
  echo "flock is required to serialize planned reboots" >&2
  exit 69
}
install -d -m 0755 "$OUT_DIR"
exec 9>"$OUT_DIR/.maintenance-reboot.lock"
if ! flock --exclusive --nonblock 9; then
  echo "another planned reboot is already in progress" >&2
  exit 75
fi

PUBLISHER="${AVELREN_MAINTENANCE_PUBLISHER:-/usr/local/sbin/avelren-maintenance-window}"
if [[ ! -x "$PUBLISHER" ]]; then
  PUBLISHER="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/maintenance-window.sh"
fi

"$PUBLISHER" "$@"
if ! systemctl reboot --message='Planned AvelRen maintenance'; then
  rm -f "$OUT_DIR/maintenance.json"
  echo "reboot command failed; maintenance signal removed" >&2
  exit 69
fi
