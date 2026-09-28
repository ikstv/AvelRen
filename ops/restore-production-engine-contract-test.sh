#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/stack"
printf 'SELECT 1;\n' | gzip -c >"$WORK/valid.sql.gz"

cat >"$WORK/bin/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
args="$*"
query=$(cat)
printf '%s %s\n' "$args" "$query" >>"$ENGINE_LOG"
[ "${PGPASSWORD:-}" = "${EXPECTED_ADMIN_PASSWORD:?}" ] || exit 31
[[ " $args " == *' exec -T -e PGPASSWORD db '* ]] || exit 32
[[ " $args " == *' -U avelren_admin '* ]] || exit 33
[[ "$args" != *"$EXPECTED_ADMIN_PASSWORD"* ]] || exit 34
if [[ "$args" == *'ON_ERROR_STOP=1'* && "$query" == *'SELECT 1;'* ]] && \
   [ "${FAKE_INGEST_FAIL:-0}" = 1 ]; then
    exit 23
fi
if [[ "$args $query" == *'timescaledb_post_restore()'* ]] && \
   [ "${FAKE_POST_FAIL:-0}" = 1 ]; then
    exit 29
fi
SH
chmod +x "$WORK/bin/docker"

run_engine() {
    local name=$1; shift
    env PATH="$WORK/bin:$PATH" ENGINE_LOG="$WORK/$name.calls" \
      AVELREN_ADMIN_PASSWORD=admin-contract-secret \
      EXPECTED_ADMIN_PASSWORD=admin-contract-secret "$@" \
      bash -c 'set -euo pipefail; source "$1"; avelren_restore_production_engine "$2" "$3" "" avelren db' \
        bash "$ROOT/ops/restore-production-engine.lib.sh" "$WORK/valid.sql.gz" "$WORK/stack" \
        >"$WORK/$name.out" 2>&1
}

run_engine success || { cat "$WORK/success.out" >&2; exit 1; }
grep -Eq ' dropdb .* avelren ' "$WORK/success.calls"
grep -Eq ' createdb .* avelren ' "$WORK/success.calls"
! grep -Eq ' (restore_test|postgres)($| )' "$WORK/success.calls"
grep -q 'restore application relation allowlist mismatch' "$WORK/success.calls"
grep -q 'OWNER TO avelren_migrator' "$WORK/success.calls"
grep -q 'timescaledb extension owner must remain avelren_admin' "$WORK/success.calls"
! grep -q 'admin-contract-secret' "$WORK/success.calls"
! grep -q 'AVELREN_COMPOSE_ENV_GUARD' "$WORK/success.calls"
pre_line=$(grep -n 'timescaledb_pre_restore()' "$WORK/success.calls" | head -1 | cut -d: -f1)
ingest_line=$(grep -n 'SELECT 1;' "$WORK/success.calls" | head -1 | cut -d: -f1)
post_line=$(grep -n 'timescaledb_post_restore()' "$WORK/success.calls" | head -1 | cut -d: -f1)
[ "$pre_line" -lt "$ingest_line" ] && [ "$ingest_line" -lt "$post_line" ]

for item in \
  'missing-password:AVELREN_ADMIN_PASSWORD=' \
  'wrong-role:AVELREN_ADMIN_DB_USER=avelren_backup'; do
    name=${item%%:*}; setting=${item#*:}
    if run_engine "$name" "$setting"; then
        echo "expected production engine role denial: $name" >&2; exit 1
    fi
    [ ! -s "$WORK/$name.calls" ]
done

set +e
run_engine primary-cleanup FAKE_INGEST_FAIL=1 FAKE_POST_FAIL=1
primary_status=$?
set -e
[ "$primary_status" -eq 23 ]
grep -q 'timescaledb_post_restore()' "$WORK/primary-cleanup.calls"
grep -q 'primary restore failure (exit=23)' "$WORK/primary-cleanup.out"
grep -q 'cleanup failed (exit=29)' "$WORK/primary-cleanup.out"

set +e
run_engine post-only FAKE_POST_FAIL=1
post_status=$?
set -e
[ "$post_status" -eq 29 ]
! grep -q 'SELECT (SELECT count' "$WORK/post-only.calls"

: >"$WORK/extra.calls"
if PATH="$WORK/bin:$PATH" ENGINE_LOG="$WORK/extra.calls" \
    AVELREN_ADMIN_PASSWORD=admin-contract-secret EXPECTED_ADMIN_PASSWORD=admin-contract-secret \
    bash -c 'source "$1"; avelren_restore_production_engine "$2" "$3" "" avelren db restore_test' \
      bash "$ROOT/ops/restore-production-engine.lib.sh" "$WORK/valid.sql.gz" "$WORK/stack"; then
    echo "production wrapper accepted an arbitrary target argument" >&2
    exit 1
fi
[ ! -s "$WORK/extra.calls" ]

if bash "$ROOT/ops/restore-production-engine.lib.sh" >"$WORK/direct.out" 2>&1; then
    echo "source-only production engine ran directly" >&2
    exit 1
fi
grep -q source-only "$WORK/direct.out"

echo "production restore engine contract: PASS"
