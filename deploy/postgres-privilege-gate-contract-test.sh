#!/usr/bin/env bash
# Contract test for the Stage 3B.2 production privilege_contracts gate runner
# (deploy/postgres-privilege-gate.sh). A fake `docker` on PATH records the argv
# it receives and returns a controllable exit code, so every assertion runs
# without a real Docker daemon or any container — safe in CI.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

BIN="$WORK/bin"
mkdir -p "$BIN"
# Fake docker: log the full argv, then exit with ${FAKE_DOCKER_EXIT:-0}. The
# runner `exec`s docker, so this exit code becomes the runner's exit code.
cat >"$BIN/docker" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${FAKE_LOG:?}"
exit "${FAKE_DOCKER_EXIT:-0}"
SH
chmod +x "$BIN/docker"

# Sentinel DSN values. If any of these ever reaches the docker argv/log the
# runner leaked a credential — the log assertions below prove it does not.
ADMIN='postgresql://avelren_admin:SENTINELadmin@db:5432/avelren'
COLLECTOR='postgresql://avelren_collector:SENTINELcollector@db:5432/avelren'
NOTIFIER='postgresql://avelren_notifier:SENTINELnotifier@db:5432/avelren'
WATCHDOG='postgresql://avelren_watchdog:SENTINELwatchdog@db:5432/avelren'
API='postgresql://avelren_api:SENTINELapi@db:5432/avelren'
BACKUP='postgresql://avelren_backup:SENTINELbackup@db:5432/avelren'

run_gate() {
    env PATH="$BIN:$PATH" FAKE_LOG="$FAKE_LOG" FAKE_DOCKER_EXIT="${FAKE_DOCKER_EXIT:-0}" \
        AVELREN_STACK_DIR="$ROOT" \
        AVELREN_COMPOSE_PROJECT=avelren \
        AVELREN_DOCKER_BIN=docker \
        AVELREN_ADMIN_TOOL_DSN="$ADMIN" \
        AVELREN_COLLECTOR_DSN="$COLLECTOR" \
        AVELREN_NOTIFIER_DSN="$NOTIFIER" \
        AVELREN_WATCHDOG_DSN="$WATCHDOG" \
        AVELREN_API_DSN="$API" \
        AVELREN_BACKUP_DSN="$BACKUP" \
        "$@" \
        bash "$ROOT/deploy/postgres-privilege-gate.sh" "${GATE_ARG-privilege_contracts}"
}

fail() { echo "GATE CONTRACT FAILED: $*" >&2; exit 1; }

# --- A: correct argument proceeds and issues exactly one compose run ----------
FAKE_LOG="$WORK/a.log"; : >"$FAKE_LOG"; FAKE_DOCKER_EXIT=0
run_gate >"$WORK/a.out" 2>&1 || { cat "$WORK/a.out" >&2; fail 'A: correct arg did not exit 0'; }
[ "$(wc -l <"$FAKE_LOG")" -eq 1 ] || { cat "$FAKE_LOG" >&2; fail 'A: expected exactly one docker invocation'; }
line=$(cat "$FAKE_LOG")

# --- B: --no-deps and one-off run, never a lifecycle command ------------------
case " $line " in *' run --rm --no-deps -T '*) ;; *) fail "B: missing 'run --rm --no-deps -T': $line" ;; esac
for verb in up create recreate start stop restart down; do
    case " $line " in
        *" $verb "*) fail "B: forbidden lifecycle verb '$verb' present: $line" ;;
    esac
done
echo 'B run --no-deps, no lifecycle command: PASS'

# --- C: introspection-only subset selected, DML tests excluded ----------------
for t in test_role_has_no_elevated_capability test_table_privileges_match_frozen_acl \
    test_sequence_privileges_match_frozen_acl test_device_column_privileges_match_frozen_acl \
    test_column_scoped_updates_match_frozen_acl test_column_scoped_selects_match_frozen_acl \
    test_public_has_no_existing_application_object_privileges; do
    case "$line" in *"$t"*) ;; *) fail "C: introspection test not selected: $t" ;; esac
done
for t in test_role_specific_negative_matrix test_runtime_role_cannot_escalate_or_change_migration_history \
    test_collector_positive_service_paths_commit_without_device_access \
    test_migrator_default_privileges_isolate_future_objects \
    test_api_positive_routes_use_api_role_for_reads_and_lifecycles \
    test_notifier_positive_service_paths_cover_delivery_and_cancel_lifecycle \
    test_watchdog_positive_service_paths_cover_health_and_recovery \
    test_watchdog_dead_fcm_token_updates_devices_under_watchdog_role; do
    case "$line" in
        *"$t"*) fail "C: mutating/DML test must NOT be selected: $t" ;;
    esac
done
# The gate must never run migrate.
case "$line" in *' migrate '*|*'avelren.migrate'*) fail 'C: gate must not run migrate' ;; esac
echo 'C introspection-only subset, no DML/positive-commit/migrate: PASS'

# --- D: DSNs forwarded by name only, never by value ---------------------------
for name in ADMIN_DATABASE_URL COLLECTOR_DATABASE_URL NOTIFIER_DATABASE_URL \
    WATCHDOG_DATABASE_URL API_DATABASE_URL BACKUP_DATABASE_URL; do
    case " $line " in *" -e $name "*) ;; *) fail "D: DSN not forwarded by name: $name" ;; esac
done
if grep -q SENTINEL "$FAKE_LOG"; then
    fail 'D: a DSN value leaked into the docker argv/log'
fi
echo 'D DSNs forwarded by name only, no value in argv/log: PASS'

# --- E: wrong argument is refused before any docker call ----------------------
FAKE_LOG="$WORK/e.log"; : >"$FAKE_LOG"
if GATE_ARG=migrate run_gate >"$WORK/e.out" 2>&1; then fail 'E: wrong arg was not refused'; fi
[ ! -s "$WORK/e.log" ] || fail 'E: docker ran despite a wrong argument'
grep -q "only 'privilege_contracts' is supported" "$WORK/e.out" || fail 'E: wrong refusal message'
echo 'E wrong argument refused, no docker call: PASS'

# --- F: missing argument is refused before any docker call --------------------
FAKE_LOG="$WORK/f.log"; : >"$FAKE_LOG"
if GATE_ARG='' run_gate >"$WORK/f.out" 2>&1; then fail 'F: missing arg was not refused'; fi
[ ! -s "$WORK/f.log" ] || fail 'F: docker ran despite a missing argument'
echo 'F missing argument refused, no docker call: PASS'

# --- G: pytest failure (docker non-zero) -> runner non-zero -------------------
FAKE_LOG="$WORK/g.log"; : >"$FAKE_LOG"
if FAKE_DOCKER_EXIT=1 run_gate >"$WORK/g.out" 2>&1; then
    fail 'G: gate returned success when pytest failed'
fi
echo 'G pytest failure propagates to non-zero: PASS'

# --- H: a missing per-role DSN fails closed before any docker call ------------
FAKE_LOG="$WORK/h.log"; : >"$FAKE_LOG"
if env PATH="$BIN:$PATH" FAKE_LOG="$WORK/h.log" \
    AVELREN_STACK_DIR="$ROOT" AVELREN_COMPOSE_PROJECT=avelren AVELREN_DOCKER_BIN=docker \
    AVELREN_ADMIN_TOOL_DSN="$ADMIN" AVELREN_COLLECTOR_DSN="$COLLECTOR" \
    AVELREN_NOTIFIER_DSN="$NOTIFIER" AVELREN_WATCHDOG_DSN="$WATCHDOG" \
    AVELREN_API_DSN="$API" \
    bash "$ROOT/deploy/postgres-privilege-gate.sh" privilege_contracts >"$WORK/h.out" 2>&1; then
    fail 'H: missing BACKUP DSN was not refused'
fi
[ ! -s "$WORK/h.log" ] || fail 'H: docker ran despite a missing DSN'
echo 'H missing per-role DSN fails closed: PASS'

echo 'postgres privilege gate contract: ALL PASS'
