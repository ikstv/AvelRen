#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/state"

cat >"$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
cat "$AVELREN_MAINTENANCE_DIR/maintenance.json" | python3 -c '
import json, sys
window = json.load(sys.stdin)
print(json.dumps({"maintenance": window}, separators=(",", ":")))
'
EOF
cat >"$WORK/bin/sleep" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$1" >"$SLEEP_LOG"
EOF
chmod +x "$WORK/bin/curl" "$WORK/bin/sleep"

PATH="$WORK/bin:$PATH" \
AVELREN_MAINTENANCE_DIR="$WORK/state" \
AVELREN_STATUS_URL=https://status.test/api/status \
SLEEP_LOG="$WORK/sleep" \
bash "$ROOT/deploy/maintenance-window.sh" --duration-seconds 120 --wait-seconds 60

python3 - "$WORK/state/maintenance.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert set(payload) == {"starts_at", "ends_at"}
assert payload["starts_at"].endswith("Z") and payload["ends_at"].endswith("Z")
PY
[ "$(cat "$WORK/sleep")" = 60 ]

if PATH="$WORK/bin:$PATH" AVELREN_MAINTENANCE_DIR="$WORK/state" \
    bash "$ROOT/deploy/maintenance-window.sh" --duration-seconds 901 >/dev/null 2>&1; then
    echo 'invalid duration was accepted' >&2
    exit 1
fi

echo 'maintenance window contract: PASS'
