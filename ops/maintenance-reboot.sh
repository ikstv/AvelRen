#!/usr/bin/env bash
# Reboot only after maintenance-window.sh has published and verified the badge.
set -euo pipefail

PUBLISHER="${AVELREN_MAINTENANCE_PUBLISHER:-/usr/local/sbin/avelren-maintenance-window}"
if [[ ! -x "$PUBLISHER" ]]; then
  PUBLISHER="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/maintenance-window.sh"
fi

"$PUBLISHER" "$@"
if ! systemctl reboot --message='Planned AvelRen maintenance'; then
  OUT_DIR="${AVELREN_MAINTENANCE_DIR:-/var/lib/avelren-telemetry}"
  rm -f "$OUT_DIR/maintenance.json"
  echo "reboot command failed; maintenance signal removed" >&2
  exit 69
fi
