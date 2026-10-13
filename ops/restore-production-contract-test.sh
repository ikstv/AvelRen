#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source "$ROOT/ops/paired-backup-test-fixture.lib.sh"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK" "$GUARD_WORK"' EXIT
printf 'original artifact\n' >"$WORK/dump.sql.gz"
printf 'sidecar\n' >"$WORK/dump.sql.gz.sha256"
printf '{}\n' >"$WORK/evidence.json"

run_case() {
    local name=$1 fail_stage=${2:-} mutation=${3:-}
    : >"$WORK/$name.trace"
    set +e
    env TRACE="$WORK/$name.trace" FAIL_STAGE="$fail_stage" MUTATION="$mutation" \
      SECRET_SENTINEL='restore-contract-secret' \
      python3 "$ROOT/ops/paired_backup_state.py" --manifest "$AVELREN_RUNTIME_MANIFEST" operator -- bash -c '
        set -euo pipefail
        source "$1"
        step() {
          printf "%s\n" "$1" >>"$TRACE"
          if [ "${FAIL_STAGE:-}" = "$1" ]; then return 71; fi
        }
        avelren_require_production_operator() { step confirm; }
        avelren_require_supported_collector_topology() {
          case "${FAIL_STAGE:-}" in unsupported-collector-topology|docker-unavailable) return 71 ;; esac
        }
        avelren_verify_production_preflight() {
          step preflight || return
          AVELREN_VERIFIED_TARGET_COMMIT=$(printf "a%.0s" {1..40})
          AVELREN_VERIFIED_MIGRATION_PIN=001_init
          AVELREN_VERIFIED_ARTIFACT_SHA=$(sha256sum "$1" | awk "{print \$1}")
          export AVELREN_VERIFIED_TARGET_COMMIT AVELREN_VERIFIED_MIGRATION_PIN AVELREN_VERIFIED_ARTIFACT_SHA
        }
        avelren_create_safety_snapshot() { step snapshot; AVELREN_RESTORE_RECEIPT=/run/avelren-restore/safety-snapshot.json; }
        avelren_publish_restore_maintenance() {
          step maintenance || return
          AVELREN_RESTORE_MAINTENANCE_STARTED=true
          [ "${FAIL_STAGE:-}" != signal-int ] || kill -INT $$
          [ "${FAIL_STAGE:-}" != signal-term ] || kill -TERM $$
        }
        avelren_stop_production_clients() {
          step stop
          [ "${MUTATION:-}" != artifact ] || printf mutate >>"$AVELREN_RESTORE_ARTIFACT"
        }
        avelren_verify_production_quiescent_sessions() { step sessions; }
        if [ "${MUTATION:-}" != artifact ]; then
          avelren_recheck_restore_artifact() { step artifact-recheck; }
        fi
        avelren_restore_production_engine() { step engine; }
        avelren_verify_post_restore_schema_roles() { step schema-roles; }
        avelren_start_production_clients() { step start-clients; }
        avelren_verify_internal_api() { step api; }
        avelren_wait_for_collector_cycle() { step collector; }
        avelren_validate_caddy_config() { step caddy-config; }
        avelren_start_caddy() { step start-caddy; AVELREN_RESTORE_CADDY_STARTED=true; }
        avelren_verify_external_health() { step external-health; }
        avelren_clear_restore_maintenance() { step clear-maintenance; }
        avelren_stop_restore_clients_fail_closed() {
          step fail-closed
          AVELREN_RESTORE_FAILURE_STATE=stopped-verified
        }
        avelren_restore_production_main --artifact "$2" --sidecar "$3" --evidence "$4"
      ' bash "$ROOT/ops/restore-production.sh" "$WORK/dump.sql.gz" \
        "$WORK/dump.sql.gz.sha256" "$WORK/evidence.json" \
        >"$WORK/$name.out" 2>&1
    local status=$?
    set -e
    printf '%s' "$status"
}

status=$(run_case success)
[ "$status" -eq 0 ]
expected=$(printf '%s\n' confirm preflight snapshot maintenance stop sessions artifact-recheck engine \
  schema-roles start-clients api collector caddy-config start-caddy external-health clear-maintenance)
[ "$(cat "$WORK/success.trace")" = "$expected" ]

for stage in confirm preflight snapshot maintenance; do
    status=$(run_case "before-$stage" "$stage")
    [ "$status" -ne 0 ]
    ! grep -Eq '^(maintenance|stop|engine|start-caddy|clear-maintenance|fail-closed)$' "$WORK/before-$stage.trace"
done

for stage in unsupported-collector-topology docker-unavailable; do
    status=$(run_case "$stage" "$stage")
    [ "$status" -ne 0 ]
    [ "$(cat "$WORK/$stage.trace")" = confirm ]
    ! grep -q 'restore-contract-secret' "$WORK/$stage.out"
done

chmod 0666 "$WORK/dump.sql.gz"
status=$(run_case unsafe-input)
[ "$status" -ne 0 ]
[ "$(cat "$WORK/unsafe-input.trace")" = confirm ]
chmod 0644 "$WORK/dump.sql.gz"

chown 1000 "$WORK/evidence.json"
status=$(run_case unowned-input)
[ "$status" -ne 0 ]
[ "$(cat "$WORK/unowned-input.trace")" = confirm ]
chown 0 "$WORK/evidence.json"

for stage in stop sessions artifact-recheck engine schema-roles start-clients api collector caddy-config start-caddy external-health; do
    status=$(run_case "after-$stage" "$stage")
    [ "$status" -ne 0 ]
    grep -qx fail-closed "$WORK/after-$stage.trace"
    ! grep -qx clear-maintenance "$WORK/after-$stage.trace"
    grep -q 'phase=' "$WORK/after-$stage.out"
    grep -q 'runbook=ops/RECOVERY.md#production-restore-failure' "$WORK/after-$stage.out"
    ! grep -q 'restore-contract-secret' "$WORK/after-$stage.out"
done

status=$(run_case after-clear clear-maintenance)
[ "$status" -ne 0 ]
grep -qx fail-closed "$WORK/after-clear.trace"
grep -qx clear-maintenance "$WORK/after-clear.trace"

# Artifact identity is captured before maintenance and checked again after all
# clients stop. Replacing it then must fail before the engine.
cp "$WORK/dump.sql.gz" "$WORK/dump.original"
status=$(run_case artifact-replaced '' artifact)
[ "$status" -ne 0 ]
grep -qx fail-closed "$WORK/artifact-replaced.trace"
! grep -qx engine "$WORK/artifact-replaced.trace"
mv "$WORK/dump.original" "$WORK/dump.sql.gz"

for signal in signal-int signal-term; do
    status=$(run_case "$signal" "$signal")
    [ "$status" -ne 0 ]
    grep -qx fail-closed "$WORK/$signal.trace"
    ! grep -qx clear-maintenance "$WORK/$signal.trace"
done

# Confirmation is exact and date-bound. The entrypoint opens /dev/tty; this
# unit check supplies a dedicated descriptor directly to the narrow reader.
today=$(date -u +%F)
exec 7<<<"RESTORE avelren $today"
bash -c 'source "$1"; avelren_confirm_production_restore 7' 7<&7 \
  bash "$ROOT/ops/restore-production.sh"
exec 7<&-
exec 7<<<"RESTORE avelren 1999-01-01"
if bash -c 'source "$1"; avelren_confirm_production_restore 7' 7<&7 \
  bash "$ROOT/ops/restore-production.sh"; then
    echo "wrong confirmation date was accepted" >&2; exit 1
fi
exec 7<&-

if bash "$ROOT/ops/restore-production.sh" --artifact "$WORK/dump.sql.gz" \
    --sidecar "$WORK/dump.sql.gz.sha256" --evidence "$WORK/evidence.json" \
    >"$WORK/direct.out" 2>&1; then
    echo "non-interactive production restore unexpectedly ran" >&2
    exit 1
fi

# psql's uncast boolean output is t/f, which is the exact protocol consumed by
# the poll loop. Casting it to text would silently change it to true/false and
# make a successful collector cycle time out.
bash -c '
  set -euo pipefail
  source "$1"
  avelren_compose() {
    local sql
    sql=$(cat)
    [[ "$sql" == *"SELECT EXISTS ("* ]] || return 87
    [[ "$sql" != *"::text"* ]] || return 88
    printf "t\n"
  }
  AVELREN_ADMIN_PASSWORD=contract-secret
  AVELREN_RESTORE_RUNTIME_STARTED_AT=2026-09-28T00:00:00Z
  avelren_wait_for_collector_cycle
' bash "$ROOT/ops/restore-production.sh"

echo "production restore orchestrator contract: PASS"
