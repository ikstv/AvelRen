#!/usr/bin/env bash
# Task 6 validates pre-commit rollback. Task 7 adds disposable committed adoption.
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")/.." && pwd)
readonly ROOT
# shellcheck source=deploy/postgres-ownership.lib.sh
source "$ROOT/deploy/postgres-ownership.lib.sh"

CONFIRMATION=
RETIRE_LEGACY=false
PRODUCTION_ADOPT=false
PROD_TOKEN_FILE=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --confirm-adoption)
            [ "$#" -ge 2 ] || { echo 'adoption confirmation token missing' >&2; exit 2; }
            CONFIRMATION=$2
            shift 2
            ;;
        --retire-legacy)
            [ "$RETIRE_LEGACY" = false ] || { echo 'duplicate retirement argument' >&2; exit 2; }
            RETIRE_LEGACY=true
            shift
            ;;
        --production-adopt)
            [ "$PRODUCTION_ADOPT" = false ] || { echo 'duplicate production argument' >&2; exit 2; }
            PRODUCTION_ADOPT=true
            shift
            ;;
        --production-token-file)
            [ "$#" -ge 2 ] || { echo 'production token file path missing' >&2; exit 2; }
            PROD_TOKEN_FILE=$2
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
FAILPOINT=${AVELREN_ADOPTION_FAILPOINT:-}
POST_COMMIT_GATE=${AVELREN_ADOPTION_POST_COMMIT_GATE:-}
COMMITTED_FAILPOINT=${AVELREN_ADOPTION_COMMITTED_FAILPOINT:-}
CORRUPT_INVERSE=${AVELREN_ADOPTION_CORRUPT_INVERSE:-0}
SUCCESS_GATE_RUNNER=${AVELREN_ADOPTION_SUCCESS_GATE_RUNNER:-}
RETIREMENT_GATE_RUNNER=${AVELREN_ADOPTION_RETIREMENT_GATE_RUNNER:-}
ACCEPTED_SOAK_FILE=${AVELREN_ACCEPTED_SOAK_FILE:-}
RETIREMENT_FAILPOINT=${AVELREN_RETIREMENT_FAILPOINT:-}

PRODUCTION_TOKEN_EXPECTED=AVELREN-POSTGRES-ADOPTION-PROD

# Stage 3B.2 production ownership/ACL adoption against the live `avelren`
# database. Role provisioning (db/security/bootstrap.sql, step 3B.1) is a prior,
# separate operation; this mode NEVER creates roles — it asserts the 7 roles
# already exist and then performs the same committed forward adoption the
# disposable path proves, holding BEFORE any migrate / DSN cutover / restart.
if [ "$PRODUCTION_ADOPT" = true ]; then
    [ "$RETIRE_LEGACY" = false ]        || fail 'production adoption forbids --retire-legacy'
    [ "${AVELREN_TEST_DB:-}" != 1 ]     || fail 'production adoption forbids AVELREN_TEST_DB'
    # Production target is exactly `avelren`. The integration suite exercises this
    # very path against a disposable database, so a narrow, test-fixture-only
    # override is allowed — but ONLY for a disposable *test*/*ci* target, never
    # for `avelren` itself. In production no override is set and the exact-name
    # check below is the sole gate; even if the override variable were somehow
    # set on the host, a production `avelren` target is not *test*/*ci* and is
    # rejected, so the guard cannot be bypassed against the real database.
    if [ -n "${AVELREN_PRODUCTION_TARGET_OVERRIDE:-}" ]; then
        case "$TARGET_DB" in
            *test*|*ci*) ;;
            *) fail 'production target override is limited to disposable *test*/*ci* targets' ;;
        esac
        [ "$TARGET_DB" = "$AVELREN_PRODUCTION_TARGET_OVERRIDE" ] || \
            fail 'production target does not match the fixture override'
    else
        [ "$TARGET_DB" = avelren ] || fail 'production target must be exactly avelren'
    fi
    [ -z "$FAILPOINT" ]                 || fail 'production adoption forbids an adoption failpoint'
    [ -z "$POST_COMMIT_GATE" ]          || fail 'production adoption forbids a post-commit gate injection'
    [ -z "$COMMITTED_FAILPOINT" ]       || fail 'production adoption forbids a committed-adoption failpoint'
    [ "$CORRUPT_INVERSE" = 0 ]          || fail 'production adoption forbids inverse corruption'
    [ -n "$SUCCESS_GATE_RUNNER" ]       || fail 'production adoption requires a privilege-contract gate runner'
    # Production confirmation token: read from a 0400/0600 file we own, never
    # from argv (no ps/argv exposure) and never echoed into logs or evidence.
    [ -n "$PROD_TOKEN_FILE" ]           || fail 'production adoption requires --production-token-file'
    [ -f "$PROD_TOKEN_FILE" ] && [ ! -L "$PROD_TOKEN_FILE" ] || fail 'production token file is invalid'
    case "$(stat -c '%a' "$PROD_TOKEN_FILE")" in 400|600) ;; *) fail 'production token file mode must be 0400 or 0600' ;; esac
    [ "$(stat -c '%u' "$PROD_TOKEN_FILE")" = "$(id -u)" ] || fail 'production token file owner mismatch'
    # `read` returns non-zero on EOF without a trailing newline even though it
    # captured the line, so validate the captured value rather than the status.
    _prod_token=
    IFS= read -r _prod_token <"$PROD_TOKEN_FILE" || true
    [ -n "$_prod_token" ] || fail 'cannot read production token file'
    [ "$_prod_token" = "$PRODUCTION_TOKEN_EXPECTED" ] || fail 'production token mismatch'
    unset _prod_token
    # Drive the committed-forward machinery like the success cutover, but a
    # production hold (below) intercepts before any post-commit gate or cutover.
    FAILPOINT=success
fi

# Read-only: every least-privilege role must already exist (provisioned in
# 3B.1). Production adoption reassigns ownership/ACL to them; it never creates
# them, so an absent role is a hard refusal, not something to paper over.
production_assert_roles_exist() {
    local role present admin_super
    for role in avelren_admin avelren_migrator avelren_backup avelren_collector \
        avelren_notifier avelren_watchdog avelren_api; do
        present=$(_adoption_psql "$ADMIN_DSN" -tAc \
            "SELECT 1 FROM pg_roles WHERE rolname='$role';") || \
            fail 'cannot inspect least-privilege roles'
        [ "$present" = 1 ] || \
            fail "role $role is absent; run role provisioning (3B.1 bootstrap.sql) first"
    done
    admin_super=$(_adoption_psql "$ADMIN_DSN" -tAc \
        "SELECT rolsuper FROM pg_roles WHERE rolname='avelren_admin';") || \
        fail 'cannot inspect avelren_admin attributes'
    [ "$admin_super" = t ] || fail 'role avelren_admin must be SUPERUSER before adoption'
}

# Invariant across 3B/3C/3D/3E: legacy `avelren` stays SUPERUSER+LOGIN until the
# separate retirement gate (3F). A violation here means adoption altered the
# legacy role and must roll back.
production_assert_legacy_untouched() {
    local state
    # Concatenating booleans yields the text 'true'/'false' (a bare boolean
    # column would render 't'/'f'); compare against that exact rendering.
    state=$(_adoption_psql "$ADMIN_DSN" -tAc \
        "SELECT rolsuper::text||','||rolcanlogin::text FROM pg_roles WHERE rolname='avelren';") || \
        route_post_commit_failure 'cannot verify legacy avelren role state'
    [ "$state" = 'true,true' ] || \
        route_post_commit_failure "legacy avelren role altered during adoption (rolsuper,rolcanlogin=$state)"
}

compose() {
    local args=("$DOCKER_BIN" compose)
    [ -z "$COMPOSE_FILE" ] || args+=(-f "$COMPOSE_FILE")
    [ -z "$COMPOSE_PROJECT" ] || args+=(-p "$COMPOSE_PROJECT")
    "${args[@]}" "$@"
}

[ -n "$EVIDENCE_DIR" ] || fail 'evidence directory is required'
if [ "$RETIRE_LEGACY" = true ]; then
    retirement_attempt_commit=NOT_VERIFIED
    if [[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
        retirement_attempt_commit=$EXPECTED_COMMIT
    fi
    invalidate_legacy_retirement_success "$EVIDENCE_DIR" "$retirement_attempt_commit" || \
        fail 'legacy retirement attempt evidence invalidation failed'
fi
[ -n "$TARGET_DB" ] || fail 'target database is required'
[ -n "$ADMIN_DSN" ] || fail 'admin connection is required'
[ -n "$EXPECTED_COMMIT" ] || fail 'expected commit is required'
[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail 'expected commit must be an exact SHA-1'
[ -n "$RECOVERY_PREFLIGHT" ] || fail 'recovery preflight evidence is required'

# Task 6 deliberately has no normal COMMIT path. The only SQL mutation exercise
# is disposable and must prove transaction rollback before Task 7 exists.
if [ "$PRODUCTION_ADOPT" != true ]; then
    [ "${AVELREN_TEST_DB:-}" = 1 ] || fail 'Task 6 adoption execution is disposable-only'
    case "$TARGET_DB" in *test*|*ci*) ;; *) fail 'disposable target name must contain test or ci' ;; esac
fi
if [ "$RETIRE_LEGACY" = true ]; then
    [ -z "$FAILPOINT" ] || fail 'legacy retirement does not accept an adoption failpoint'
    [ -z "$POST_COMMIT_GATE" ] || fail 'legacy retirement does not accept a post-commit failpoint'
    [ -z "$COMMITTED_FAILPOINT" ] || fail 'legacy retirement does not accept a committed-adoption failpoint'
    [ "$CORRUPT_INVERSE" = 0 ] || fail 'legacy retirement does not accept inverse corruption'
    case "$RETIREMENT_FAILPOINT" in ''|alteration|verification|publication) ;;
        *) fail 'unknown retirement failpoint' ;;
    esac
    [ -z "$RETIREMENT_FAILPOINT" ] || [ "${AVELREN_TEST_DB:-}" = 1 ] || \
        fail 'retirement failure injection is disposable-only'
else
    case "$FAILPOINT" in before_commit|after_commit|success) ;; *) fail 'adoption failpoint must be before_commit, after_commit, or success' ;; esac
    [ "$FAILPOINT" = before_commit ] || [ "${AVELREN_TEST_DB:-}" = 1 ] || [ "$PRODUCTION_ADOPT" = true ] || fail 'committed adoption is disposable-only'
    [ -z "$POST_COMMIT_GATE" ] || case "$POST_COMMIT_GATE" in migrate|privilege_contracts|compose_credential_switch|smoke|collector_freshness|environment_isolation) ;; *) fail 'unknown post-commit gate' ;; esac
    [ -z "$COMMITTED_FAILPOINT" ] || case "$COMMITTED_FAILPOINT" in cleanup|capture|verification|signal_hup|signal_int|signal_term) ;; *) fail 'unknown committed-adoption failpoint' ;; esac
    case "$CORRUPT_INVERSE" in 0|1|invalid_sql|incomplete) ;; *) fail 'unknown inverse corruption mode' ;; esac
fi
if [ "$RETIRE_LEGACY" = false ] && [ "$FAILPOINT" = success ]; then
    [ -z "$POST_COMMIT_GATE" ] || fail 'success cutover does not accept a post-commit failure injection'
    [ -z "$COMMITTED_FAILPOINT" ] || fail 'success cutover does not accept a committed-adoption failure injection'
    [ "$CORRUPT_INVERSE" = 0 ] || fail 'success cutover does not accept inverse corruption'
fi
if [ "$RETIRE_LEGACY" = false ] && \
   { [ "$FAILPOINT" = success ] || [ "$FAILPOINT" = after_commit ]; }; then
    [ -n "$SUCCESS_GATE_RUNNER" ] || fail 'post-commit gate runner is required'
    [ -f "$SUCCESS_GATE_RUNNER" ] && [ ! -L "$SUCCESS_GATE_RUNNER" ] && \
        [ -x "$SUCCESS_GATE_RUNNER" ] || fail 'success cutover gate runner is invalid'
    [ "$(stat -c '%u' "$SUCCESS_GATE_RUNNER")" = "$(id -u)" ] || \
        fail 'post-commit gate runner owner mismatch'
    case "$(stat -c '%a' "$SUCCESS_GATE_RUNNER")" in
        500|700) ;;
        *) fail 'post-commit gate runner mode must be 0500 or 0700' ;;
    esac
fi
if [ "$RETIRE_LEGACY" = true ]; then
    [ -n "$ACCEPTED_SOAK_FILE" ] || fail 'accepted-soak evidence is required'
    [ -n "$RETIREMENT_GATE_RUNNER" ] || fail 'retirement gate runner is required'
    [ -f "$RETIREMENT_GATE_RUNNER" ] && [ ! -L "$RETIREMENT_GATE_RUNNER" ] && \
        [ -x "$RETIREMENT_GATE_RUNNER" ] || fail 'retirement gate runner is invalid'
    [ "$(stat -c '%u' "$RETIREMENT_GATE_RUNNER")" = "$(id -u)" ] || \
        fail 'retirement gate runner owner mismatch'
    case "$(stat -c '%a' "$RETIREMENT_GATE_RUNNER")" in
        500|700) ;;
        *) fail 'retirement gate runner mode must be 0500 or 0700' ;;
    esac
fi
if [ "$RETIRE_LEGACY" = false ] && [ "$FAILPOINT" = after_commit ]; then
    if { [ -z "$POST_COMMIT_GATE" ] && [ -z "$COMMITTED_FAILPOINT" ]; } ||
       { [ -n "$POST_COMMIT_GATE" ] && [ -n "$COMMITTED_FAILPOINT" ]; }; then
        fail 'after_commit requires exactly one injected post-commit failure'
    fi
fi

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
if [ "$PRODUCTION_ADOPT" = true ]; then
    # 3B.2 bootstraps under the legacy `avelren` SUPERUSER: it is the only role
    # that can REASSIGN OWNED / GRANT before avelren_admin owns anything. The
    # avelren_admin identity is asserted below by role existence + attributes.
    [ "$admin_user" = avelren ] || \
        fail 'production adoption must bootstrap as the legacy avelren superuser'
    production_assert_roles_exist
else
    [ "$admin_user" = avelren_admin ] || fail 'admin connection must authenticate as avelren_admin'
fi

retire_legacy_role() {
    local stage_file original_manifest committed_manifest validated_manifest marker
    local original_fingerprint target_fingerprint current_fingerprint post_fingerprint
    local accepted_at now age legacy_login driver output
    local privilege_result=NOT_RUN isolation_result=NOT_RUN artifact
    local -a stage_lines soak_lines

    validate_protected_evidence_directory "$EVIDENCE_DIR" 'adoption evidence directory' || \
        fail 'adoption evidence directory is unsafe'
    for artifact in original.tsv forward.sql inverse.sql after-plan-validation.tsv \
        committed-forward.marker committed.tsv stage; do
        validate_protected_evidence_file "$EVIDENCE_DIR/$artifact" \
            'required adoption evidence file' || fail 'required adoption evidence file is invalid'
        if grep -Eq 'postgresql://|DATABASE_URL|PASSWORD' "$EVIDENCE_DIR/$artifact"; then
            fail 'required adoption evidence contains credential material'
        fi
    done

    stage_file="$EVIDENCE_DIR/stage"
    mapfile -t stage_lines <"$stage_file" || fail 'cutover stage evidence cannot be read'
    [ "${#stage_lines[@]}" -eq 10 ] || fail 'cutover stage evidence is malformed'
    [ "${stage_lines[0]}" = "exact_commit=$EXPECTED_COMMIT" ] || fail 'cutover stage commit mismatch'
    [ "${stage_lines[1]}" = 'stage=cutover_complete' ] || fail 'cutover stage is not complete'
    [[ "${stage_lines[2]}" =~ ^original_fingerprint=([0-9a-f]{64})$ ]] || \
        fail 'cutover original fingerprint is malformed'
    original_fingerprint=${BASH_REMATCH[1]}
    [[ "${stage_lines[3]}" =~ ^target_fingerprint=([0-9a-f]{64})$ ]] || \
        fail 'cutover target fingerprint is malformed'
    target_fingerprint=${BASH_REMATCH[1]}
    [ "${stage_lines[4]}" = 'inverse_verified=NOT_RUN' ] || fail 'cutover inverse state is inconsistent'
    [ "${stage_lines[5]}" = 'privilege_contract_result=PASS' ] || fail 'cutover privilege contracts are not PASS'
    [ "${stage_lines[6]}" = 'environment_isolation_result=PASS' ] || fail 'cutover environment isolation is not PASS'
    [ "${stage_lines[7]}" = 'smoke_result=PASS' ] || fail 'cutover smoke is not PASS'
    [ "${stage_lines[8]}" = 'freshness_result=PASS' ] || fail 'cutover freshness is not PASS'
    [ "${stage_lines[9]}" = 'accepted_cutover=PASS' ] || fail 'cutover acceptance is not PASS'

    original_manifest="$EVIDENCE_DIR/original.tsv"
    committed_manifest="$EVIDENCE_DIR/committed.tsv"
    validated_manifest="$EVIDENCE_DIR/after-plan-validation.tsv"
    marker="$EVIDENCE_DIR/committed-forward.marker"
    validate_owned_object_allowlist "$original_manifest" || fail 'original adoption manifest is invalid'
    [ "$(manifest_fingerprint "$original_manifest")" = "$original_fingerprint" ] || \
        fail 'original adoption fingerprint mismatch'
    cmp -s "$original_manifest" "$validated_manifest" || \
        fail 'forward/inverse validation evidence mismatch'
    [ "$(manifest_fingerprint "$committed_manifest")" = "$target_fingerprint" ] || \
        fail 'committed adoption fingerprint mismatch'
    [ "$(wc -l <"$marker")" -eq 1 ] && grep -Fxq 'FORWARD_TARGET_VERIFIED' "$marker" || \
        fail 'committed adoption marker is malformed'

    validate_protected_input_file "$ACCEPTED_SOAK_FILE" 'accepted-soak evidence' || \
        fail 'accepted-soak evidence file is invalid'
    mapfile -t soak_lines <"$ACCEPTED_SOAK_FILE" || fail 'accepted-soak evidence cannot be read'
    [ "${#soak_lines[@]}" -eq 4 ] || fail 'accepted-soak evidence is malformed'
    [ "${soak_lines[0]}" = 'accepted_soak=PASS' ] || fail 'accepted soak is not PASS'
    [ "${soak_lines[1]}" = "exact_commit=$EXPECTED_COMMIT" ] || fail 'accepted-soak commit mismatch'
    [ "${soak_lines[2]}" = "target_fingerprint=$target_fingerprint" ] || \
        fail 'accepted-soak target fingerprint mismatch'
    [[ "${soak_lines[3]}" =~ ^accepted_at_epoch=(0|[1-9][0-9]*)$ ]] || \
        fail 'accepted-soak evidence is malformed'
    accepted_at=${BASH_REMATCH[1]}
    now=$(date -u +%s) || fail 'cannot read current time for accepted soak'
    [ "$accepted_at" -le "$now" ] || fail 'accepted-soak evidence is malformed'
    age=$((now - accepted_at))
    [ "$age" -le 86400 ] || fail 'accepted-soak evidence is stale'

    capture_manifest "$ADMIN_DSN" "$EVIDENCE_DIR/retirement-before.tsv" || \
        fail 'cannot capture pre-retirement manifest'
    current_fingerprint=$(manifest_fingerprint "$EVIDENCE_DIR/retirement-before.tsv") || \
        fail 'cannot fingerprint pre-retirement manifest'
    cmp -s "$committed_manifest" "$EVIDENCE_DIR/retirement-before.tsv" || \
        fail 'current owner/ACL manifest differs from accepted cutover'
    [ "$current_fingerprint" = "$target_fingerprint" ] || \
        fail 'current owner/ACL fingerprint differs from accepted cutover'
    verify_target_ownership "$ADMIN_DSN" "$original_manifest" || \
        fail 'current target ownership verification failed'
    rm -f "$EVIDENCE_DIR/retirement-before.tsv" || fail 'cannot remove pre-retirement capture'

    legacy_login=$(_adoption_psql "$ADMIN_DSN" -c \
        "SELECT rolcanlogin FROM pg_roles WHERE rolname='avelren';") || \
        fail 'cannot inspect legacy role'
    [ "$legacy_login" = t ] || fail 'legacy role is not LOGIN-capable before retirement'

    driver=$(_evidence_temp "$EVIDENCE_DIR/legacy-retirement.sql") || \
        fail 'legacy role alteration driver creation failed'
    output=$(_evidence_temp "$EVIDENCE_DIR/legacy-retirement.marker") || {
        rm -f "$driver"
        fail 'legacy role alteration output creation failed'
    }
    {
        printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;' 'ALTER ROLE "avelren" NOLOGIN;'
        cat <<'SQL'
DO $avelren_legacy_retired$
BEGIN
    IF (SELECT rolcanlogin FROM pg_roles WHERE rolname = 'avelren') THEN
        RAISE EXCEPTION 'legacy role remained LOGIN-capable';
    END IF;
END
$avelren_legacy_retired$;
SQL
        if [ "$RETIREMENT_FAILPOINT" = alteration ]; then
            printf '%s\n' "DO \$avelren_retirement_fail\$ BEGIN RAISE EXCEPTION 'retirement alteration FAIL (injected)'; END \$avelren_retirement_fail\$;"
        fi
        printf '%s\n' "SELECT 'LEGACY_ROLE_NOLOGIN';" 'COMMIT;'
    } >"$driver" || {
        rm -f "$driver" "$output"
        fail 'legacy role alteration driver generation failed'
    }
    if ! _adoption_psql "$ADMIN_DSN" <"$driver" >"$output"; then
        rm -f "$driver" "$output"
        fail 'legacy role alteration failed'
    fi
    rm -f "$driver" || { rm -f "$output"; fail 'legacy role alteration driver cleanup failed'; }
    grep -Fxq 'LEGACY_ROLE_NOLOGIN' "$output" || {
        rm -f "$output"
        fail 'legacy role alteration was not proven'
    }
    rm -f "$output" || fail 'legacy role alteration output cleanup failed'

    if [ "$RETIREMENT_FAILPOINT" = verification ]; then
        fail 'post-retirement verification failed (injected)'
    fi
    legacy_login=$(_adoption_psql "$ADMIN_DSN" -c \
        "SELECT rolcanlogin FROM pg_roles WHERE rolname='avelren';") || \
        fail 'post-retirement verification failed'
    [ "$legacy_login" = f ] || fail 'post-retirement verification failed: legacy LOGIN remains enabled'
    capture_manifest "$ADMIN_DSN" "$EVIDENCE_DIR/retirement-after.tsv" || \
        fail 'post-retirement verification failed: manifest capture'
    post_fingerprint=$(manifest_fingerprint "$EVIDENCE_DIR/retirement-after.tsv") || \
        fail 'post-retirement verification failed: fingerprint capture'
    cmp -s "$committed_manifest" "$EVIDENCE_DIR/retirement-after.tsv" || \
        fail 'post-retirement verification failed: owner/ACL manifest changed'
    [ "$post_fingerprint" = "$target_fingerprint" ] || \
        fail 'post-retirement verification failed: owner/ACL fingerprint changed'
    verify_target_ownership "$ADMIN_DSN" "$original_manifest" || \
        fail 'post-retirement verification failed: target ownership'

    if ! env -u AVELREN_ADMIN_DSN -u AVELREN_ADMIN_TOOL_DSN -u ADMIN_DATABASE_URL \
        -u DATABASE_URL -u PGPASSWORD -u AVELREN_ADMIN_PASSWORD \
        "$RETIREMENT_GATE_RUNNER" privilege_contracts; then
        fail 'post-retirement verification failed: privilege contracts'
    fi
    privilege_result=PASS
    if ! env -u AVELREN_ADMIN_DSN -u AVELREN_ADMIN_TOOL_DSN -u ADMIN_DATABASE_URL \
        -u DATABASE_URL -u PGPASSWORD -u AVELREN_ADMIN_PASSWORD \
        "$RETIREMENT_GATE_RUNNER" environment_isolation; then
        fail 'post-retirement verification failed: environment isolation'
    fi
    isolation_result=PASS

    if ! publish_legacy_retirement "$EVIDENCE_DIR/legacy-retirement" "$EXPECTED_COMMIT" \
        "$target_fingerprint" "$post_fingerprint" "$privilege_result" \
        "$isolation_result" PASS; then
        log 'ADOPTION FAILED: legacy role is NOLOGIN but retirement evidence publication failed; manual intervention required' >&2
        return 1
    fi
    log 'legacy retirement complete: NOLOGIN and all post-retirement gates PASS'
}

if [ "$RETIRE_LEGACY" = true ]; then
    retire_legacy_role
    exit 0
fi

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
ADOPTION_CUTOVER_SUCCESSFUL=false
ADOPTION_FAILURE_ROUTING=false
ADOPTION_FAILURE_REASON=
ADOPTION_NEW_RUNTIME_START_ATTEMPTED=false
ADOPTION_NEW_RUNTIME_STOP_CONFIRMED=true

handle_adoption_signal() {
    local signal_name=$1 signal_status
    signal_status=$(adoption_signal_exit_status "$signal_name") || signal_status=1
    ADOPTION_FAILURE_REASON="signal $signal_name after adoption"
    exit "$signal_status"
}

keep_runtime_stopped() {
    local status=$? cleanup_status=0 final_running service
    trap - EXIT HUP INT TERM
    if [ "${ADOPTION_FORWARD_COMMITTED:-false}" = true ] \
        && [ "$ADOPTION_CUTOVER_SUCCESSFUL" != true ] \
        && [ "$ADOPTION_FAILURE_ROUTING" != true ]; then
        local failure_reason restart_allowed=true no_restart_reason=
        set +e
        failure_reason=${ADOPTION_FAILURE_REASON:-"post-COMMIT exit status $status"}
        if [ "${ADOPTION_COMMITTED_MARKER_PUBLISHED:-false}" != true ]; then
            restart_allowed=false
            no_restart_reason='committed marker evidence is unavailable'
        fi
        if [ "$ADOPTION_NEW_RUNTIME_START_ATTEMPTED" = true ] \
            && [ "$ADOPTION_NEW_RUNTIME_STOP_CONFIRMED" != true ]; then
            if compose stop caddy api collector notifier watchdog >/dev/null; then
                ADOPTION_NEW_RUNTIME_STOP_CONFIRMED=true
            else
                restart_allowed=false
                no_restart_reason='new-runtime stop was not confirmed'
            fi
        fi
        route_post_commit_failure "$failure_reason" "$restart_allowed" "$no_restart_reason" "$status"
    fi
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
trap 'handle_adoption_signal HUP' HUP
trap 'handle_adoption_signal INT' INT
trap 'handle_adoption_signal TERM' TERM

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
if [ "$FAILPOINT" = before_commit ]; then
    log 'client-stop gate PASS; executing disposable before_commit transaction'
    execute_before_commit_rollback "$ADMIN_DSN" "$ORIGINAL_MANIFEST" "$FORWARD_PLAN" "$EVIDENCE_DIR"
    log 'before_commit rollback verified: exact owner/ACL fingerprint restored'
    exit 75
fi

original_fingerprint=$(manifest_fingerprint "$ORIGINAL_MANIFEST")
target_fingerprint=-
privilege_result=NOT_RUN
isolation_result=NOT_RUN
smoke_result=NOT_RUN
freshness_result=NOT_RUN

rollback_committed_adoption() {
    local reason=$1 restart_allowed=${2:-true} no_restart_reason=${3:-}
    log "post-commit failure: $reason; executing verified inverse rollback" >&2
    if execute_inverse_rollback "$ADMIN_DSN" "$ORIGINAL_MANIFEST" "$INVERSE_PLAN" "$EVIDENCE_DIR"; then
        if [ "$restart_allowed" != true ]; then
            publish_adoption_stage "$EVIDENCE_DIR/stage" "$EXPECTED_COMMIT" rollback_failed \
                "$original_fingerprint" "$target_fingerprint" PASS "$privilege_result" \
                "$isolation_result" "$smoke_result" "$freshness_result" || true
            log "ADOPTION FAILED: inverse rollback verified but ${no_restart_reason:-committed marker evidence is unavailable}; runtime remains stopped; manual intervention required" >&2
            return 1
        fi
        if ! publish_adoption_stage "$EVIDENCE_DIR/stage" "$EXPECTED_COMMIT" post_commit_rollback \
            "$original_fingerprint" "$target_fingerprint" PASS "$privilege_result" \
            "$isolation_result" "$smoke_result" "$freshness_result"; then
            log 'ADOPTION FAILED: rollback restored but final evidence publication failed; manual intervention required' >&2
            return 1
        fi
        log 'post-commit inverse rollback verified: exact owner/ACL fingerprint restored'
        if ! compose up -d caddy api collector notifier watchdog; then
            log 'ADOPTION FAILED: verified rollback completed but previous runtime restart failed; manual intervention required' >&2
            return 1
        fi
        MAINTENANCE_ENTERED=false
        return 0
    fi
    publish_adoption_stage "$EVIDENCE_DIR/stage" "$EXPECTED_COMMIT" rollback_failed \
        "$original_fingerprint" "$target_fingerprint" FAIL "$privilege_result" \
        "$isolation_result" "$smoke_result" "$freshness_result" || true
    log 'ADOPTION FAILED: inverse rollback or verification failed; manual intervention required' >&2
    return 1
}

route_post_commit_failure() {
    local reason=$1 restart_allowed=${2:-true} no_restart_reason=${3:-} requested_status=${4:-}
    ADOPTION_FAILURE_ROUTING=true
    if rollback_committed_adoption "$reason" "$restart_allowed" "$no_restart_reason"; then
        [ -n "$requested_status" ] && exit "$requested_status"
        exit 76
    fi
    [ -n "$requested_status" ] && exit "$requested_status"
    exit 1
}

publish_committed_stage() {
    publish_adoption_stage "$EVIDENCE_DIR/stage" "$EXPECTED_COMMIT" committed \
        "$original_fingerprint" "$target_fingerprint" NOT_RUN "$privilege_result" \
        "$isolation_result" "$smoke_result" "$freshness_result"
}

if [ "$PRODUCTION_ADOPT" = true ]; then
    # Second, in-window manifest capture immediately before the first mutation.
    # ORIGINAL_MANIFEST was taken before maintenance; re-capture now and abort on
    # any catalog drift between preflight and the mutation window.
    capture_manifest "$ADMIN_DSN" "$EVIDENCE_DIR/pre-mutation.tsv"
    cmp -s "$ORIGINAL_MANIFEST" "$EVIDENCE_DIR/pre-mutation.tsv" || \
        fail 'catalog drifted between preflight and mutation window'
fi

log 'client-stop gate PASS; executing committed forward adoption'
ADOPTION_FORWARD_COMMITTED=false
if ! execute_committed_adoption "$ADMIN_DSN" "$ORIGINAL_MANIFEST" "$FORWARD_PLAN" "$EVIDENCE_DIR"; then
    [ "$ADOPTION_FORWARD_COMMITTED" = true ] || fail 'forward adoption failed before commit; runtime remains stopped'
    publish_committed_stage || true
    route_post_commit_failure 'committed forward capture, marker, or verification failed' \
        "${ADOPTION_COMMITTED_MARKER_PUBLISHED:-false}"
fi
if ! target_fingerprint=$(manifest_fingerprint "$EVIDENCE_DIR/committed.tsv"); then
    target_fingerprint=-
    publish_committed_stage || true
    route_post_commit_failure 'committed target fingerprint capture failed'
fi
if ! publish_committed_stage; then
    route_post_commit_failure 'committed stage evidence publication failed'
fi
log 'committed forward adoption verified'

run_post_commit_gate() {
    local gate=$1
    if [ "$POST_COMMIT_GATE" = "$gate" ]; then
        case "$gate" in
            privilege_contracts) privilege_result=FAIL ;;
            smoke) smoke_result=FAIL ;;
            collector_freshness) freshness_result=FAIL ;;
            environment_isolation) isolation_result=FAIL ;;
        esac
        log "post-commit gate $gate FAIL (injected)" >&2
        return 1
    fi
    "$SUCCESS_GATE_RUNNER" "$gate" || return 1
    case "$gate" in
        privilege_contracts) privilege_result=PASS ;;
        smoke) smoke_result=PASS ;;
        collector_freshness) freshness_result=PASS ;;
        environment_isolation) isolation_result=PASS ;;
    esac
    log "post-commit gate $gate PASS"
}

if [ "$PRODUCTION_ADOPT" = true ]; then
    # Production hold for Stage 3B.2: run ONLY the read-only privilege-contract
    # acceptance. Never run migrate (schema_migrations stays 009 by design — 010
    # is stamped later when the migrator runs on its own DSN), never
    # compose_credential_switch / DSN cutover, never smoke on a new runtime.
    if ! run_post_commit_gate privilege_contracts; then
        route_post_commit_failure 'production privilege-contract acceptance failed'
    fi
    production_assert_legacy_untouched
    publish_committed_stage || \
        route_post_commit_failure 'production committed stage evidence publication failed'
    log 'production adoption committed: 7 roles own/grant per contract; legacy avelren SUPERUSER+LOGIN intact; schema_migrations intentionally unchanged (009)'
    # Bring clients back on the UNCHANGED legacy DSN (.env untouched; DSN cutover
    # is a later, separate gate). This restart is not a cutover.
    if ! compose up -d caddy api collector notifier watchdog; then
        log 'ADOPTION WARNING: clients did not restart cleanly on the legacy DSN; manual check required' >&2
    fi
    MAINTENANCE_ENTERED=false
    log 'Stage 3B.2 production adoption complete; HARD STOP'
    exit 0
fi

for gate in migrate privilege_contracts compose_credential_switch smoke collector_freshness environment_isolation; do
    if ! run_post_commit_gate "$gate"; then
        route_post_commit_failure "post-commit gate $gate failed"
    fi
done

if [ "$FAILPOINT" = success ]; then
    if ! publish_adoption_stage "$EVIDENCE_DIR/stage" "$EXPECTED_COMMIT" cutover_complete \
        "$original_fingerprint" "$target_fingerprint" NOT_RUN "$privilege_result" \
        "$isolation_result" "$smoke_result" "$freshness_result" PASS; then
        route_post_commit_failure 'accepted cutover evidence publication failed'
    fi
    log 'all success gates PASS; accepted cutover evidence published; starting new runtime'
    ADOPTION_NEW_RUNTIME_START_ATTEMPTED=true
    ADOPTION_NEW_RUNTIME_STOP_CONFIRMED=false
    if ! compose up -d caddy api collector notifier watchdog; then
        log 'new runtime start failed; restoring maintenance before inverse rollback' >&2
        if ! compose stop caddy api collector notifier watchdog; then
            log 'ADOPTION FAILED: partial new runtime could not be stopped; manual intervention required' >&2
            route_post_commit_failure 'new runtime start failed and stop was not confirmed' false \
                'new-runtime stop was not confirmed'
        fi
        ADOPTION_NEW_RUNTIME_STOP_CONFIRMED=true
        route_post_commit_failure 'new runtime start failed after accepted gates'
    fi
    ADOPTION_CUTOVER_SUCCESSFUL=true
    MAINTENANCE_ENTERED=false
    log 'successful committed adoption complete; new runtime started after every required gate'
    exit 0
fi

route_post_commit_failure 'after_commit reached a terminal path without completed cutover'
