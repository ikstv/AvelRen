#!/usr/bin/env bash
# The only supported host reboot path for AvelRen planned maintenance.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$SCRIPT_DIR/maintenance-window.sh" "$@"
exec systemctl reboot --message='Planned AvelRen maintenance'
