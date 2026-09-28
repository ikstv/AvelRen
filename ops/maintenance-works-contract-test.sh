#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/state"

cat >"$WORK/bin/id" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "${FAKE_UID:-0}"
SH
cat >"$WORK/bin/date" <<'SH'
#!/usr/bin/env bash
case "$*" in
  '-u +%s') printf '1790582400\n' ;;
  '-u -d @1790582400 +%Y-%m-%dT%H:%M:%SZ') printf '2026-09-28T06:40:00Z\n' ;;
  '-u -d @1790582520 +%Y-%m-%dT%H:%M:%SZ') printf '2026-09-28T06:42:00Z\n' ;;
  '-u -d @1790604000 +%Y-%m-%dT%H:%M:%SZ') printf '2026-09-28T12:40:00Z\n' ;;
  *) echo "unexpected date invocation" >&2; exit 1 ;;
esac
SH
cat >"$WORK/bin/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >"$CURL_LOG"
[[ "${CURL_SHOULD_FAIL:-0}" != 1 ]]
python3 - "$AVELREN_MAINTENANCE_DIR/maintenance.json" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
if set(payload) != {"starts_at", "ends_at"}:
    raise SystemExit(1)
print(json.dumps({"maintenance": {
    "starts_at": payload["starts_at"].replace("Z", "+00:00"),
    "ends_at": payload["ends_at"].replace("Z", "+00:00"),
}}))
PY
SH
cat >"$WORK/bin/sleep" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$1" >"$SLEEP_LOG"
SH
cat >"$WORK/bin/mv" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >"$MV_LOG"
/bin/mv "$@"
SH
chmod +x "$WORK/bin/id" "$WORK/bin/date" "$WORK/bin/curl" "$WORK/bin/sleep" "$WORK/bin/mv"

run_publisher() {
  PATH="$WORK/bin:$PATH" \
    AVELREN_MAINTENANCE_DIR="$WORK/state" \
    AVELREN_STATUS_URL="https://status.test/api/status" \
    CURL_LOG="$WORK/curl.log" \
    SLEEP_LOG="$WORK/sleep.log" \
    MV_LOG="$WORK/mv.log" \
    bash "$ROOT/ops/maintenance-works.sh" "$@"
}

for invalid in 119 21601 nope; do
  if run_publisher --duration-seconds "$invalid"; then
    echo "invalid duration was accepted: $invalid" >&2
    exit 1
  fi
done

if FAKE_UID=1000 run_publisher --duration-seconds 120; then
  echo "non-root publisher was accepted" >&2
  exit 1
fi

run_publisher --duration-seconds 21600

python3 - "$WORK/state/maintenance.json" <<'PY'
import json
import os
import stat
import sys

path = sys.argv[1]
payload = json.loads(open(path, encoding="utf-8").read())
assert payload == {
    "starts_at": "2026-09-28T06:40:00Z",
    "ends_at": "2026-09-28T12:40:00Z",
}
assert stat.S_IMODE(os.stat(path).st_mode) == 0o644
assert "restarts_at" not in payload
assert "boot_id" not in payload
PY
grep -Eq '^(-f )?.*/\.maintenance\.json\.[^ ]+ .*/maintenance\.json$' "$WORK/mv.log"
grep -q -- '--max-time 15 https://status.test/api/status' "$WORK/curl.log"
test "$(cat "$WORK/sleep.log")" = 60

rm -f "$WORK/state/maintenance.json"
if CURL_SHOULD_FAIL=1 run_publisher --duration-seconds 120; then
  echo "failed status confirmation was reported as success" >&2
  exit 1
fi
test ! -e "$WORK/state/maintenance.json" || {
  echo "failed confirmation left a false maintenance signal" >&2
  exit 1
}

echo "maintenance works contract: PASS"
