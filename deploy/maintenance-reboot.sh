#!/usr/bin/env bash
# The only supported host reboot path for AvelRen planned maintenance.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PUBLISHER=${AVELREN_MAINTENANCE_PUBLISHER:-/usr/local/sbin/avelren-maintenance-window}
if [ ! -x "$PUBLISHER" ]; then
    PUBLISHER="$SCRIPT_DIR/maintenance-window.sh"
fi
"$PUBLISHER" "$@"
exec systemctl reboot --message='Planned AvelRen maintenance'
