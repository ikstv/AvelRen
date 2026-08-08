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
for arg in "$@"; do
    case "$arg" in
        *bootstrap.sql) stage=roles ;;
        *bootstrap-stage:create_database*) stage=create_database ;;
        *bootstrap-stage:extension*) stage=extension ;;
        *bootstrap-stage:acl*) stage=acl ;;
        *bootstrap-stage:verify*) stage=verify ;;
        *bootstrap-stage:cleanup*) stage=cleanup ;;
        *bootstrap_stage=*) stage=${arg##*=} ;;
    esac
done

[ -n "$stage" ] || { printf 'fake psql received an unlabelled statement\n' >&2; exit 97; }
printf '%s\n' "$stage" >>"$FAKE_CALLS"
[ "${PSQL_FAIL_ON:-}" != "$stage" ] || exit 91
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
        AVELREN_ADMIN_DSN='postgresql://admin@fake/postgres' \
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
run_bootstrap "$calls" fresh >"$WORK/success.out" 2>&1
assert_order "$calls" roles create_database extension acl verify
grep -Fxq migrate_handoff "$WORK/success.out" || fail 'missing migrate handoff'

for stage in roles create_database extension acl verify; do
    calls="$WORK/fail-${stage}.calls"
    if PSQL_FAIL_ON="$stage" run_bootstrap "$calls" fresh >"$WORK/fail-${stage}.out" 2>&1; then
        fail "expected stage failure: $stage"
    fi
    case "$stage" in
        roles) assert_not_contains "$calls" create_database ;;
        create_database) assert_not_contains "$calls" extension ;;
        extension) assert_not_contains "$calls" acl ;;
        acl) assert_not_contains "$calls" verify ;;
        verify) ! grep -Fxq migrate_handoff "$WORK/fail-${stage}.out" || fail 'handoff after verification failure' ;;
    esac
done

calls="$WORK/roles-acl.calls"
run_bootstrap "$calls" roles-acl >"$WORK/roles-acl.out" 2>&1
assert_order "$calls" roles acl verify
assert_not_contains "$calls" create_database
assert_not_contains "$calls" extension

all_output=$(cat "$WORK"/*.out 2>/dev/null || true)
for secret in admin migrator backup collector notifier watchdog api; do
    [[ "$all_output" != *"${secret}-secret-not-for-output"* ]] || fail 'secret appeared in output'
done

echo 'postgres bootstrap contract tests: 15 passed'
