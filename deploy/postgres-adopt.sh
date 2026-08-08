#!/usr/bin/env bash
# Task 6 boundary: validated planning plus a disposable before_commit rollback.
# Normal committed adoption and every restart/retirement path belong to Task 7.
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")/.." && pwd)
readonly ROOT
# shellcheck source=deploy/postgres-ownership.lib.sh
source "$ROOT/deploy/postgres-ownership.lib.sh"

CONFIRMATION=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --confirm-adoption)
            [ "$#" -ge 2 ] || { echo 'adoption confirmation token missing' >&2; exit 2; }
            CONFIRMATION=$2
            shift 2
            ;;
        *) echo 'unknown adoption argument' >&2; exit 2 ;;
    esac
done

log() { echo "$(date -u +%FT%TZ) $*"; }
fail() { log "ADOPTION REFUSED: $*" >&2; exit 1; }

[ "$CONFIRMATION" = AVELREN-POSTGRES-ADOPTION ] || fail 'exact confirmation token required'

TARGET_DB=${AVELREN_TARGET_DB:-}
ADMIN_DSN=${AVELREN_ADMIN_DSN:-}
EXPECTED_COMMIT=${AVELREN_EXPECTED_COMMIT:-}
RECOVERY_PREFLIGHT=${AVELREN_RECOVERY_PREFLIGHT_FILE:-}
EVIDENCE_DIR=${AVELREN_EVIDENCE_DIR:-}
STACK_DIR=${AVELREN_STACK_DIR:-$ROOT}
DOCKER_BIN=${AVELREN_DOCKER_BIN:-docker}
COMPOSE_FILE=${AVELREN_COMPOSE_FILE:-}
COMPOSE_PROJECT=${AVELREN_COMPOSE_PROJECT:-}
KNOWN_CLIENTS='caddy api collector notifier watchdog'

compose() {
    local args=("$DOCKER_BIN" compose)
    [ -z "$COMPOSE_FILE" ] || args+=(-f "$COMPOSE_FILE")
    [ -z "$COMPOSE_PROJECT" ] || args+=(-p "$COMPOSE_PROJECT")
    "${args[@]}" "$@"
}

[ -n "$TARGET_DB" ] || fail 'target database is required'
[ -n "$ADMIN_DSN" ] || fail 'admin connection is required'
[ -n "$EXPECTED_COMMIT" ] || fail 'expected commit is required'
[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail 'expected commit must be an exact SHA-1'
[ -n "$RECOVERY_PREFLIGHT" ] || fail 'recovery preflight evidence is required'
[ -n "$EVIDENCE_DIR" ] || fail 'evidence directory is required'

# Task 6 deliberately has no normal COMMIT path. The only SQL mutation exercise
# is disposable and must prove transaction rollback before Task 7 exists.
[ "${AVELREN_TEST_DB:-}" = 1 ] || fail 'Task 6 adoption execution is disposable-only'
case "$TARGET_DB" in *test*|*ci*) ;; *) fail 'disposable target name must contain test or ci' ;; esac
[ "${AVELREN_ADOPTION_FAILPOINT:-}" = before_commit ] || fail 'Task 6 requires before_commit failpoint'

GIT_BIN=${AVELREN_GIT_BIN:-git}
current_commit=$("$GIT_BIN" -C "$ROOT" rev-parse HEAD) || fail 'cannot read repository commit'
[ "$current_commit" = "$EXPECTED_COMMIT" ] || fail 'exact commit mismatch'
if [ "${AVELREN_ALLOW_DIRTY_TEST:-}" != 1 ]; then
    worktree_status=$("$GIT_BIN" -C "$ROOT" status --porcelain=v1 --untracked-files=all) || \
        fail 'cannot verify clean worktree'
    [ -z "$worktree_status" ] || fail 'worktree is dirty'
fi

[ -f "$RECOVERY_PREFLIGHT" ] && [ ! -L "$RECOVERY_PREFLIGHT" ] || fail 'recovery preflight file is invalid'
case "$(stat -c '%a' "$RECOVERY_PREFLIGHT")" in 400|600) ;; *) fail 'recovery preflight mode must be 0400 or 0600' ;; esac
[ "$(stat -c '%u' "$RECOVERY_PREFLIGHT")" = "$(id -u)" ] || fail 'recovery preflight owner mismatch'
[ "$(wc -l <"$RECOVERY_PREFLIGHT")" -eq 3 ] || fail 'recovery preflight has unexpected fields'
grep -Fxq 'status=PASS' "$RECOVERY_PREFLIGHT" || fail 'recovery preflight status is not PASS'
grep -Fxq 'backup_recovery=PASS' "$RECOVERY_PREFLIGHT" || fail 'backup/recovery preflight is not PASS'
grep -Fxq "exact_commit=$EXPECTED_COMMIT" "$RECOVERY_PREFLIGHT" || fail 'recovery preflight commit mismatch'

if [ -n "${AVELREN_CURRENT_DB_USER:-}" ]; then
    [ -n "${AVELREN_CATALOG_FIXTURE_DIR:-}" ] || fail 'database-user override is test-fixture-only'
    admin_user=$AVELREN_CURRENT_DB_USER
else
    admin_user=$(_adoption_psql "$ADMIN_DSN" -c 'SELECT current_user;') || fail 'admin connection failed'
fi
[ "$admin_user" = avelren_admin ] || fail 'admin connection must authenticate as avelren_admin'

prepare_evidence_dir "$EVIDENCE_DIR"
ORIGINAL_MANIFEST="$EVIDENCE_DIR/original.tsv"
FORWARD_PLAN="$EVIDENCE_DIR/forward.sql"
INVERSE_PLAN="$EVIDENCE_DIR/inverse.sql"
capture_manifest "$ADMIN_DSN" "$ORIGINAL_MANIFEST"
validate_owned_object_allowlist "$ORIGINAL_MANIFEST"
build_forward_plan "$ORIGINAL_MANIFEST" "$FORWARD_PLAN" "$ROOT/db/migrations/010_postgresql_least_privilege.sql"
build_inverse_plan "$ORIGINAL_MANIFEST" "$INVERSE_PLAN"

cd "$STACK_DIR"
running=$(compose ps --status running --services) || fail 'cannot inspect running services'
while IFS= read -r service; do
    [ -z "$service" ] && continue
    case " $KNOWN_CLIENTS db " in *" $service "*) ;; *) fail 'unexpected running service detected' ;; esac
done <<<"$running"

validate_plan_round_trip "$ADMIN_DSN" "$ORIGINAL_MANIFEST" "$FORWARD_PLAN" "$INVERSE_PLAN"
log 'catalog, allowlist, forward plan, inverse plan, and fingerprint preflight PASS'

MAINTENANCE_ENTERED=false
keep_runtime_stopped() {
    local status=$? cleanup_status=0 final_running service
    trap - EXIT HUP INT TERM
    if [ "$MAINTENANCE_ENTERED" = true ]; then
        set +e
        # Intentional fixed service list; no operator-provided word splitting.
        compose stop caddy api collector notifier watchdog >/dev/null || cleanup_status=1
        final_running=$(compose ps --status running --services) || cleanup_status=1
        for service in caddy api collector notifier watchdog; do
            if printf '%s\n' "$final_running" | grep -Fxq "$service"; then cleanup_status=1; fi
        done
        set -e
        if [ "$cleanup_status" -ne 0 ]; then
            log 'ADOPTION FAILED: maintenance verification incomplete; manual intervention required' >&2
        else
            log 'ADOPTION FAILED: runtime remains stopped' >&2
        fi
    fi
    exit "$status"
}
trap keep_runtime_stopped EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

log 'maintenance entry: stopping known clients'
MAINTENANCE_ENTERED=true
compose stop caddy api collector notifier watchdog

running=$(compose ps --status running --services) || fail 'cannot verify stopped services'
while IFS= read -r service; do
    [ -z "$service" ] && continue
    [ "$service" = db ] || fail 'client-stop gate found an unexpected running service'
done <<<"$running"
for service in caddy api collector notifier watchdog; do
    if printf '%s\n' "$running" | grep -Fxq "$service"; then fail 'known client is still running'; fi
done
log 'client-stop gate PASS; executing disposable before_commit transaction'

execute_before_commit_rollback "$ADMIN_DSN" "$ORIGINAL_MANIFEST" "$FORWARD_PLAN" "$EVIDENCE_DIR"
log 'before_commit rollback verified: exact owner/ACL fingerprint restored'

# The failed transaction is the expected Task 6 outcome. Returning non-zero
# prevents any caller from treating this pre-commit exercise as adoption.
exit 75
