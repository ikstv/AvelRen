#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

fail() {
    printf 'bootstrap contract failed: %s\n' "$*" >&2
    exit 1
}

make_fake_psql() {
    mkdir -p "$WORK/bin"
    cat >"$WORK/bin/psql" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

stage=
input=$(cat)
for arg in "$@"; do
    case "$arg" in
        *bootstrap.sql) stage=roles ;;
        *bootstrap-stage:create_database*) stage=create_database ;;
        *bootstrap-stage:database-exists*) stage=database_exists ;;
        *bootstrap-stage:extension*) stage=extension ;;
        *bootstrap-stage:acl*) stage=acl ;;
        *bootstrap-stage:verify*) stage=verify ;;
        *bootstrap-stage:cleanup*) stage=cleanup ;;
        *bootstrap_stage=*) stage=${arg##*=} ;;
    esac
done

[ -n "$stage" ] || { printf 'fake psql received an unlabelled statement\n' >&2; exit 97; }
if [ "$stage" = cleanup ]; then
    case "$input" in
        *bootstrap-cleanup:disposable-empty*) stage=cleanup_proof ;;
        *bootstrap-cleanup:drop*) stage=cleanup_drop ;;
        *) printf 'fake psql received an unlabelled cleanup statement\n' >&2; exit 96 ;;
    esac
fi

target_stage=0
case "$stage" in
    extension|acl|verify) target_stage=1 ;;
    cleanup_proof) target_stage=1 ;;
esac
if [ "$target_stage" -eq 1 ]; then
    dbname_count=0
    dbname_value=
    for arg in "$@"; do
        case "$arg" in
            --dbname=*)
                dbname_count=$((dbname_count + 1))
                dbname_value=${arg#--dbname=}
                ;;
        esac
    done
    [ "$dbname_count" -eq 1 ] || { printf 'target stage must receive exactly one dbname option\n' >&2; exit 95; }
    [ "$dbname_value" = "$FAKE_ADMIN_DSN" ] || { printf 'target stage changed the admin connection options\n' >&2; exit 94; }
    [[ " $* " == *" --set=target_db_name=$FAKE_TARGET_DB "* ]] || {
        printf 'target stage omitted the target database variable\n' >&2; exit 93;
    }
    [[ "$input" == *'\connect :target_db_name'* ]] || {
        printf 'target stage did not reconnect with the previous connection options\n' >&2; exit 92;
    }
fi

printf '%s\n' "$stage" >>"$FAKE_CALLS"
if [ "$stage" = create_database ] && [ "${FAKE_CREATE_RACE:-0}" = 1 ]; then
    [[ "$input" != *'WHERE NOT EXISTS'* ]] || {
        printf 'create stage can silently succeed after a concurrent database creation\n' >&2; exit 91;
    }
    exit 91
fi
if [[ ",${PSQL_FAIL_ON:-}," == *",$stage,"* ]] || [ "${PSQL_FAIL_ON:-}" = cleanup ]; then
    exit 91
fi
case "$stage" in
    database_exists) printf '%s\n' "${FAKE_DATABASE_EXISTS:-f}" ;;
    verify_memberships) printf '%s\n' "${FAKE_MEMBERSHIP_COUNT:-0}" ;;
    cleanup_proof)
        case " $* " in
            *' --quiet '*) printf '%s\n' "${FAKE_CLEANUP_PROOF:-t}" ;;
            *) printf 'You are now connected to database "%s".\n%s\n' "$FAKE_TARGET_DB" "${FAKE_CLEANUP_PROOF:-t}" ;;
        esac
        ;;
esac
SH
    chmod +x "$WORK/bin/psql"
}

assert_fails() {
    if "$@" >"$WORK/command.out" 2>&1; then
        cat "$WORK/command.out" >&2
        fail "expected command to fail: $*"
    fi
}

assert_order() {
    local calls=$1
    shift
    local last=0 stage line
    for stage in "$@"; do
        line=$(grep -n -m1 "^${stage}$" "$calls" | cut -d: -f1 || true)
        [ -n "$line" ] || fail "missing stage: $stage"
        [ "$line" -gt "$last" ] || fail "out-of-order stage: $stage"
        last=$line
    done
}

assert_not_contains() {
    local calls=$1 value=$2
    ! grep -Fxq "$value" "$calls" || fail "unexpected stage: $value"
}

bootstrap_env() {
    env PATH="$WORK/bin:$PATH" FAKE_CALLS="${FAKE_CALLS:?FAKE_CALLS is required}" \
        FAKE_ADMIN_DSN="${FAKE_ADMIN_DSN:-postgresql://admin@fake.example:6543/postgres?sslmode=require}" \
        FAKE_TARGET_DB="${FAKE_TARGET_DB:-avelren_contract}" \
        AVELREN_ADMIN_DSN="${FAKE_ADMIN_DSN:-postgresql://admin@fake.example:6543/postgres?sslmode=require}" \
        AVELREN_DB_NAME='avelren_contract' \
        AVELREN_ADMIN_PASSWORD='admin-secret-not-for-output' \
        AVELREN_MIGRATOR_PASSWORD='migrator-secret-not-for-output' \
        AVELREN_BACKUP_PASSWORD='backup-secret-not-for-output' \
        AVELREN_COLLECTOR_PASSWORD='collector-secret-not-for-output' \
        AVELREN_NOTIFIER_PASSWORD='notifier-secret-not-for-output' \
        AVELREN_WATCHDOG_PASSWORD='watchdog-secret-not-for-output' \
        AVELREN_API_PASSWORD='api-secret-not-for-output' \
        "$@"
}

run_bootstrap() {
    local calls=$1
    shift
    : >"$calls"
    FAKE_CALLS="$calls" bootstrap_env bash "$ROOT/deploy/postgres-bootstrap.sh" "$@"
}

run_disposable_bootstrap() {
    local calls=$1
    shift
    : >"$calls"
    FAKE_CALLS="$calls" FAKE_TARGET_DB=avelren_cleanup_test bootstrap_env \
        env AVELREN_DB_NAME=avelren_cleanup_test AVELREN_TEST_DB=1 "$@" \
        bash "$ROOT/deploy/postgres-bootstrap.sh" fresh --disposable-empty-test
}

make_fake_psql

missing_calls="$WORK/missing-password.calls"
: >"$missing_calls"
FAKE_CALLS="$missing_calls" assert_fails bootstrap_env env -u AVELREN_API_PASSWORD \
    bash "$ROOT/deploy/postgres-bootstrap.sh" roles-acl
[ ! -s "$missing_calls" ] || fail 'psql was called before password validation'

test_target_calls="$WORK/test-target.calls"
: >"$test_target_calls"
FAKE_CALLS="$test_target_calls" assert_fails bootstrap_env env -u AVELREN_TEST_DB \
    AVELREN_DB_NAME=avelren_test bash "$ROOT/deploy/postgres-bootstrap.sh" fresh
[ ! -s "$test_target_calls" ] || fail 'psql was called for an unmarked test database'

calls="$WORK/success.calls"
if ! run_bootstrap "$calls" fresh >"$WORK/success.out" 2>&1; then
    cat "$WORK/success.out" >&2
    fail 'fresh bootstrap unexpectedly failed'
fi
assert_order "$calls" roles verify_memberships database_exists create_database extension acl verify
grep -Fxq migrate_handoff "$WORK/success.out" || fail 'missing migrate handoff'

# Fail-closed guard проти privilege-escalation через role membership: якщо
# після create_roles лишається заборонений avelren_% ↔ avelren_% membership,
# bootstrap ПАДАЄ до створення бази і НЕ робить автоматичний REVOKE (аудит #29,
# postgres-roles-integration-test.sh покриває реальну поведінку; тут — логіка
# скрипта на fake psql). FAKE_MEMBERSHIP_COUNT>0 імітує залишковий membership.
calls="$WORK/forbidden-membership.calls"
if FAKE_MEMBERSHIP_COUNT=1 run_bootstrap "$calls" fresh >"$WORK/forbidden-membership.out" 2>&1; then
    fail 'fresh bootstrap accepted a forbidden canonical role membership'
fi
grep -Fq 'forbidden canonical role membership detected' "$WORK/forbidden-membership.out" \
    || fail 'membership guard did not report the forbidden membership'
assert_order "$calls" roles verify_memberships
assert_not_contains "$calls" database_exists
assert_not_contains "$calls" create_database

for stage in roles database_exists create_database extension acl verify; do
    calls="$WORK/fail-${stage}.calls"
    if PSQL_FAIL_ON="$stage" run_bootstrap "$calls" fresh >"$WORK/fail-${stage}.out" 2>&1; then
        fail "expected stage failure: $stage"
    fi
    case "$stage" in
        roles) assert_not_contains "$calls" create_database ;;
        database_exists) assert_not_contains "$calls" create_database ;;
        create_database) assert_not_contains "$calls" extension ;;
        extension) assert_not_contains "$calls" acl ;;
        acl) assert_not_contains "$calls" verify ;;
        verify) ! grep -Fxq migrate_handoff "$WORK/fail-${stage}.out" || fail 'handoff after verification failure' ;;
    esac
done

# roles-acl mutates ownership and ACLs of an existing database, so it carries the
# same disposable-only boundary as adoption: an unmarked or non-disposable target
# must be refused before any psql call.
# The target name deliberately avoids the *_test suffix so that only the
# roles-acl AVELREN_TEST_DB requirement can produce this refusal.
unmarked_roles_acl_calls="$WORK/unmarked-roles-acl.calls"
: >"$unmarked_roles_acl_calls"
FAKE_CALLS="$unmarked_roles_acl_calls" FAKE_TARGET_DB=avelren_ci \
    assert_fails bootstrap_env env -u AVELREN_TEST_DB \
    AVELREN_DB_NAME=avelren_ci bash "$ROOT/deploy/postgres-bootstrap.sh" roles-acl
[ ! -s "$unmarked_roles_acl_calls" ] || fail 'psql was called for an unmarked roles-acl target'

production_roles_acl_calls="$WORK/production-roles-acl.calls"
: >"$production_roles_acl_calls"
FAKE_CALLS="$production_roles_acl_calls" FAKE_TARGET_DB=avelren \
    assert_fails bootstrap_env env AVELREN_TEST_DB=1 \
    AVELREN_DB_NAME=avelren bash "$ROOT/deploy/postgres-bootstrap.sh" roles-acl
[ ! -s "$production_roles_acl_calls" ] || fail 'psql was called for a non-disposable roles-acl target'

calls="$WORK/roles-acl.calls"
: >"$calls"
FAKE_CALLS="$calls" FAKE_TARGET_DB=avelren_contract_test bootstrap_env \
    env AVELREN_DB_NAME=avelren_contract_test AVELREN_TEST_DB=1 \
    bash "$ROOT/deploy/postgres-bootstrap.sh" roles-acl >"$WORK/roles-acl.out" 2>&1
assert_order "$calls" roles verify_memberships acl verify
assert_not_contains "$calls" create_database
assert_not_contains "$calls" extension

calls="$WORK/preexisting-disposable.calls"
if FAKE_DATABASE_EXISTS=t PSQL_FAIL_ON=extension run_disposable_bootstrap "$calls" >"$WORK/preexisting-disposable.out" 2>&1; then
    fail 'expected existing disposable target stage failure'
fi
assert_order "$calls" roles database_exists extension
assert_not_contains "$calls" cleanup_proof
assert_not_contains "$calls" cleanup_drop

calls="$WORK/created-disposable.calls"
if PSQL_FAIL_ON=extension run_disposable_bootstrap "$calls" >"$WORK/created-disposable.out" 2>&1; then
    fail 'expected created disposable target stage failure'
fi
assert_order "$calls" roles database_exists create_database extension cleanup_proof cleanup_drop
assert_not_contains "$calls" acl

calls="$WORK/create-race-disposable.calls"
if FAKE_CREATE_RACE=1 run_disposable_bootstrap "$calls" >"$WORK/create-race-disposable.out" 2>&1; then
    fail 'expected concurrent database creation failure'
fi
assert_order "$calls" roles database_exists create_database
assert_not_contains "$calls" cleanup_proof
assert_not_contains "$calls" cleanup_drop
! grep -q 'can silently succeed' "$WORK/create-race-disposable.out" || fail 'database creation race was not fail-closed'

calls="$WORK/cleanup-not-empty.calls"
if PSQL_FAIL_ON=extension FAKE_CLEANUP_PROOF=f run_disposable_bootstrap "$calls" >"$WORK/cleanup-not-empty.out" 2>&1; then
    fail 'expected disposable target stage failure'
fi
assert_order "$calls" roles database_exists create_database extension cleanup_proof
assert_not_contains "$calls" cleanup_drop

calls="$WORK/cleanup-proof-failure.calls"
if PSQL_FAIL_ON=extension,cleanup_proof run_disposable_bootstrap "$calls" >"$WORK/cleanup-proof-failure.out" 2>&1; then
    fail 'expected cleanup proof failure'
fi
assert_order "$calls" roles database_exists create_database extension cleanup_proof
assert_not_contains "$calls" cleanup_drop

calls="$WORK/cleanup-drop-failure.calls"
if PSQL_FAIL_ON=extension,cleanup_drop run_disposable_bootstrap "$calls" >"$WORK/cleanup-drop-failure.out" 2>&1; then
    fail 'expected cleanup drop failure'
fi
assert_order "$calls" roles database_exists create_database extension cleanup_proof cleanup_drop
assert_not_contains "$calls" acl

all_output=$(cat "$WORK"/*.out 2>/dev/null || true)
for secret in admin migrator backup collector notifier watchdog api; do
    [[ "$all_output" != *"${secret}-secret-not-for-output"* ]] || fail 'secret appeared in output'
done

echo 'postgres bootstrap contract tests: 24 passed'
