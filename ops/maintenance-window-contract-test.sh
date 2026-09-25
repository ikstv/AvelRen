#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/state"

cat >"$WORK/bin/id" <<'SH'
#!/usr/bin/env bash
echo 0
SH
cat >"$WORK/bin/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '{"maintenance":'
# The API serializes UTC with +00:00 even though the publisher stores Z.
sed 's/Z"/+00:00"/g' "$AVELREN_MAINTENANCE_DIR/maintenance.json"
printf '}\n'
SH
cat >"$WORK/bin/sleep" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$1" >"$SLEEP_LOG"
SH
chmod +x "$WORK/bin/id" "$WORK/bin/curl" "$WORK/bin/sleep"

PATH="$WORK/bin:$PATH" \
  AVELREN_MAINTENANCE_DIR="$WORK/state" \
  AVELREN_STATUS_URL="https://status.test/api/status" \
  SLEEP_LOG="$WORK/sleep.log" \
  bash "$ROOT/ops/maintenance-window.sh" --duration-seconds 120 --wait-seconds 60

python3 - "$WORK/state/maintenance.json" <<'PY'
import json
import re
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
assert set(payload) == {"starts_at", "ends_at"}
assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", payload[key]) for key in payload)
PY
test "$(cat "$WORK/sleep.log")" = 60

if PATH="$WORK/bin:$PATH" AVELREN_MAINTENANCE_DIR="$WORK/state" bash "$ROOT/ops/maintenance-window.sh" --duration-seconds 901; then
  echo "duration above 900 seconds was accepted" >&2
  exit 1
fi

echo "maintenance window contract: PASS"
