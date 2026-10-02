#!/usr/bin/env bash
# Єдиний операторський entrypoint; Python використовує Linux flock(2).
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/collector-runtime-control.py" "$@"
