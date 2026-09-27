#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/state"
printf 'boot-before-restart\n' >"$WORK/boot_id"
printf '0\n' >"$WORK/date-calls"

cat >"$WORK/bin/id" <<'SH'
#!/usr/bin/env bash
echo 0
SH
cat >"$WORK/bin/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
python3 - "$AVELREN_MAINTENANCE_DIR/maintenance.json" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
public = {key: payload[key].replace("Z", "+00:00") for key in ("starts_at", "restarts_at", "ends_at")}
print(json.dumps({"maintenance": public}))
PY
SH
cat >"$WORK/bin/sleep" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$1" >"$SLEEP_LOG"
SH
cat >"$WORK/bin/date" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  '-u +%s')
    calls=$(cat "$DATE_CALL_LOG")
    if [[ "$calls" == 0 ]]; then printf '1790500000\n'; else printf '1790500015\n'; fi
    printf '%s\n' "$((calls + 1))" >"$DATE_CALL_LOG"
    ;;
  '-u -d @1790500000 +%Y-%m-%dT%H:%M:%SZ') printf '2026-09-27T07:33:20Z\n' ;;
  '-u -d @1790500090 +%Y-%m-%dT%H:%M:%SZ') printf '2026-09-27T07:34:50Z\n' ;;
  '-u -d @1790500600 +%Y-%m-%dT%H:%M:%SZ') printf '2026-09-27T07:43:20Z\n' ;;
  *) echo "unexpected date invocation: $*" >&2; exit 1 ;;
esac
SH
chmod +x "$WORK/bin/id" "$WORK/bin/curl" "$WORK/bin/sleep" "$WORK/bin/date"

PATH="$WORK/bin:$PATH" \
  AVELREN_MAINTENANCE_DIR="$WORK/state" \
  AVELREN_BOOT_ID_FILE="$WORK/boot_id" \
  AVELREN_STATUS_URL="https://status.test/api/status" \
  DATE_CALL_LOG="$WORK/date-calls" \
  SLEEP_LOG="$WORK/sleep.log" \
  bash "$ROOT/ops/maintenance-window.sh" --duration-seconds 600 --wait-seconds 75

python3 - "$WORK/state/maintenance.json" <<'PY'
import json
import re
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
assert set(payload) == {"starts_at", "restarts_at", "ends_at", "boot_id"}
assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", payload[key]) for key in ("starts_at", "restarts_at", "ends_at"))
assert payload["boot_id"] == "boot-before-restart"
from datetime import datetime
parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
assert (parse(payload["restarts_at"]) - parse(payload["starts_at"])).total_seconds() == 90
assert (parse(payload["ends_at"]) - parse(payload["starts_at"])).total_seconds() == 600
PY
test "$(cat "$WORK/sleep.log")" = 75

if PATH="$WORK/bin:$PATH" AVELREN_MAINTENANCE_DIR="$WORK/state" bash "$ROOT/ops/maintenance-window.sh" --duration-seconds 901; then
  echo "duration above 900 seconds was accepted" >&2
  exit 1
fi

if PATH="$WORK/bin:$PATH" AVELREN_MAINTENANCE_DIR="$WORK/state" AVELREN_BOOT_ID_FILE="$WORK/boot_id" bash "$ROOT/ops/maintenance-window.sh" --duration-seconds 120 --wait-seconds 75; then
  echo "maintenance window without a safe post-restart margin was accepted" >&2
  exit 1
fi

cat >"$WORK/bin/publisher" <<'SH'
#!/usr/bin/env bash
printf '{}\n' >"$AVELREN_MAINTENANCE_DIR/maintenance.json"
SH
cat >"$WORK/bin/systemctl" <<'SH'
#!/usr/bin/env bash
exit 1
SH
chmod +x "$WORK/bin/publisher" "$WORK/bin/systemctl"
if PATH="$WORK/bin:$PATH" \
  AVELREN_MAINTENANCE_DIR="$WORK/state" \
  AVELREN_MAINTENANCE_PUBLISHER="$WORK/bin/publisher" \
  bash "$ROOT/ops/maintenance-reboot.sh"; then
  echo "failed reboot command was reported as success" >&2
  exit 1
fi
test ! -e "$WORK/state/maintenance.json" || {
  echo "failed reboot command left a false maintenance signal" >&2
  exit 1
}

echo "maintenance window contract: PASS"
