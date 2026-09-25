#!/usr/bin/env bash
# Reboot only after maintenance-window.sh has published and verified the badge.
set -euo pipefail

PUBLISHER="${AVELREN_MAINTENANCE_PUBLISHER:-/usr/local/sbin/avelren-maintenance-window}"
if [[ ! -x "$PUBLISHER" ]]; then
  PUBLISHER="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/maintenance-window.sh"
fi

"$PUBLISHER" "$@"
exec systemctl reboot --message='Planned AvelRen maintenance'
