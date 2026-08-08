#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
BIN="$WORK/bin"
mkdir -p "$BIN" "$WORK/stack/deploy"
cp "$ROOT/deploy/restore-engine.lib.sh" "$WORK/stack/deploy/"
printf 'SELECT 1;\n' | gzip -c >"$WORK/valid.sql.gz"

cat >"$BIN/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
args="$*"
query=$(cat)
printf '%s %s\n' "$args" "$query" >>"$ENGINE_LOG"
if [[ "$args" == *'ON_ERROR_STOP=1'* ]] && [ "${FAKE_INGEST_FAIL:-0}" = 1 ]; then
    exit 23
fi
if [[ "$args $query" == *'timescaledb_post_restore()'* ]] && [ "${FAKE_POST_FAIL:-0}" = 1 ]; then
    exit 29
fi
exit 0
SH
chmod +x "$BIN/docker"

run_engine() {
    local name=$1
    shift
    env PATH="$BIN:$PATH" ENGINE_LOG="$WORK/$name.calls" "$@" \
        bash -c 'set -euo pipefail; source "$1/deploy/restore-engine.lib.sh"; avelren_restore_engine "$2" restore_test "$1" "" "" db' \
        bash "$WORK/stack" "$WORK/valid.sql.gz" >"$WORK/$name.out" 2>&1
}

set +e
run_engine primary-cleanup FAKE_INGEST_FAIL=1 FAKE_POST_FAIL=1
primary_status=$?
set -e
[ "$primary_status" -eq 23 ] || { cat "$WORK/primary-cleanup.out" >&2; exit 1; }
grep -q 'primary restore failure (exit=23)' "$WORK/primary-cleanup.out"
grep -q 'cleanup failed (exit=29)' "$WORK/primary-cleanup.out" || {
    cat "$WORK/primary-cleanup.out" >&2
    exit 1
}
! grep -q 'SELECT (SELECT count' "$WORK/primary-cleanup.calls"

set +e
run_engine cleanup-only FAKE_POST_FAIL=1
cleanup_status=$?
set -e
[ "$cleanup_status" -eq 29 ] || { cat "$WORK/cleanup-only.out" >&2; exit 1; }
grep -q 'timescaledb_post_restore failed (exit=29)' "$WORK/cleanup-only.out"
! grep -q 'SELECT (SELECT count' "$WORK/cleanup-only.calls"

echo "restore engine failure contract tests: 2 passed"
