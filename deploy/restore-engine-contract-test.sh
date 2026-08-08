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
[ "${PGPASSWORD:-}" = "${EXPECTED_ADMIN_PASSWORD:?}" ] || {
    echo 'admin password was not provided through the process environment' >&2
    exit 31
}
[[ " $args " == *' exec -T -e PGPASSWORD db '* ]] || {
    echo 'restore database tool did not receive the protected password environment' >&2
    exit 32
}
[[ " $args " == *' -U avelren_admin '* ]] || {
    echo 'restore database tool did not use the canonical admin role' >&2
    exit 33
}
[[ "$args" != *"$EXPECTED_ADMIN_PASSWORD"* ]] || {
    echo 'admin password leaked into docker argv' >&2
    exit 34
}
if [[ "$args" == *'ON_ERROR_STOP=1'* && "$query" == *'SELECT 1;'* ]] && [ "${FAKE_INGEST_FAIL:-0}" = 1 ]; then
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
    env PATH="$BIN:$PATH" ENGINE_LOG="$WORK/$name.calls" \
        AVELREN_ADMIN_PASSWORD=admin-contract-secret \
        EXPECTED_ADMIN_PASSWORD=admin-contract-secret "$@" \
        bash -c 'set -euo pipefail; source "$1/deploy/restore-engine.lib.sh"; avelren_restore_engine "$2" restore_test "$1" "" "" db' \
        bash "$WORK/stack" "$WORK/valid.sql.gz" >"$WORK/$name.out" 2>&1
}

run_engine success
grep -q ' dropdb ' "$WORK/success.calls"
grep -q ' createdb ' "$WORK/success.calls"
grep -q ' psql ' "$WORK/success.calls"
! grep -Eq -- '-U (avelren|avelren_backup|avelren_migrator)( |$)' "$WORK/success.calls"
! grep -q 'admin-contract-secret' "$WORK/success.calls"

# Missing credentials and non-admin role selection fail before any DB tool.
for item in \
    'missing-password:AVELREN_ADMIN_PASSWORD=' \
    'backup-role:AVELREN_ADMIN_DB_USER=avelren_backup' \
    'migrator-role:AVELREN_ADMIN_DB_USER=avelren_migrator' \
    'legacy-role:AVELREN_ADMIN_DB_USER=avelren'
do
    name=${item%%:*}; setting=${item#*:}
    if run_engine "$name" "$setting"; then
        echo "expected restore role gate failure: $name" >&2
        exit 1
    fi
    [ ! -s "$WORK/$name.calls" ]
done

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

echo "restore engine contract tests: 7 passed"
