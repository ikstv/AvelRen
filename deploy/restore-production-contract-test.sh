#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
printf 'SELECT 1;\n' | gzip -c >"$WORK/valid.sql.gz"

denied() {
    if "$@" >/dev/null 2>&1; then
        echo "expected denial: $*" >&2; exit 1
    fi
}
denied bash "$ROOT/deploy/restore-production.sh" "$WORK/valid.sql.gz"
denied bash "$ROOT/deploy/restore-production.sh" "$WORK/valid.sql.gz" \
    --confirm-production-restore WRONG
denied bash "$ROOT/deploy/restore-production.sh" "$WORK/missing.sql.gz" \
    --confirm-production-restore AVELREN-PRODUCTION-RESTORE

# Fake only external process boundaries; execute the actual orchestrator.
BIN="$WORK/bin"; mkdir -p "$BIN" "$WORK/stack/deploy"
cp "$ROOT/deploy/restore-engine.lib.sh" "$ROOT/deploy/restore-verify.sh" "$WORK/stack/deploy/"
cat >"$BIN/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_LOG"
args="$*"
if [[ "$args" == *' ps --status running --services'* ]]; then
    printf '%s\n' "${FAKE_RUNNING_SERVICE:-caddy api collector notifier watchdog}"
    exit 0
fi
if [[ "$args" == *' exec -T db psql '* ]]; then
    query=$(cat)
    args="$args $query"
    if [[ "$args" == *'SELECT count(*) FROM pg_stat_activity'* ]]; then
        printf '%s\n' "${FAKE_SESSIONS:-0}"
    elif [[ "$args" == *'COALESCE(max(time)'* ]]; then
        printf '%s\n' "1970-01-01 00:00:00+00"
    elif [[ "$args" == *'SELECT EXISTS'* ]]; then
        printf '%s\n' "${FAKE_FRESH_RESULT:-t}"
    fi
fi
SH
cat >"$BIN/curl" <<'SH'
#!/usr/bin/env bash
printf 'HTTPS_READY\n' >>"$FAKE_LOG"
printf '{"status":"ok"}\n'
exit "${FAKE_CURL_STATUS:-0}"
SH
chmod +x "$BIN/docker" "$BIN/curl"

# Replace the source-only engine function and verifier in the isolated stack to observe
# orchestration ordering; engine behavior has separate real-DB integration.
cat >"$WORK/stack/deploy/restore-engine.lib.sh" <<'SH'
avelren_restore_engine() {
    printf 'ENGINE\n' >>"$FAKE_LOG"
    [ "${FAKE_ENGINE_FAIL:-0}" != 1 ]
}
SH
cat >"$WORK/stack/deploy/restore-verify.sh" <<'SH'
#!/usr/bin/env bash
printf 'VERIFY\n' >>"$FAKE_LOG"
[ "${FAKE_VERIFY_FAIL:-0}" != 1 ]
SH

run_fake() {
    local name=$1
    shift
    env PATH="$BIN:$PATH" FAKE_LOG="$WORK/$name.log" \
        AVELREN_STACK_DIR="$WORK/stack" AVELREN_READINESS_TIMEOUT_SECONDS=1 \
        AVELREN_FRESHNESS_TIMEOUT_SECONDS=1 "$@" \
        bash "$ROOT/deploy/restore-production.sh" "$WORK/valid.sql.gz" \
        --confirm-production-restore AVELREN-PRODUCTION-RESTORE \
        >"$WORK/$name.out" 2>&1
}

assert_failed_closed() {
    local name=$1 log="$WORK/$1.log" out="$WORK/$1.out"
    grep -q 'stop caddy' "$log"
    grep -q 'stop api collector notifier watchdog' "$log"
    ! grep -q 'production restore complete' "$out"
}

run_fake success
grep -q ENGINE "$WORK/success.log"; grep -q VERIFY "$WORK/success.log"

if run_fake sessions FAKE_SESSIONS=1; then echo "session gate should fail" >&2; exit 1; fi
! grep -q ENGINE "$WORK/sessions.log"
assert_failed_closed sessions

if run_fake engine FAKE_ENGINE_FAIL=1; then echo "engine failure expected" >&2; exit 1; fi
assert_failed_closed engine

if run_fake verify FAKE_VERIFY_FAIL=1; then echo "verify failure expected" >&2; exit 1; fi
grep -q VERIFY "$WORK/verify.log"; assert_failed_closed verify
! grep -q 'up -d api collector notifier watchdog' "$WORK/verify.log"
! grep -q 'up -d caddy' "$WORK/verify.log"
! grep -q HTTPS_READY "$WORK/verify.log"
! grep -q 'SELECT EXISTS' "$WORK/verify.log"

if run_fake readiness FAKE_CURL_STATUS=1; then echo "readiness failure expected" >&2; exit 1; fi
grep -q 'up -d caddy' "$WORK/readiness.log"
grep -q HTTPS_READY "$WORK/readiness.log"
assert_failed_closed readiness

if run_fake freshness FAKE_FRESH_RESULT=f; then echo "freshness failure expected" >&2; exit 1; fi
grep -q HTTPS_READY "$WORK/freshness.log"
grep -q 'SELECT EXISTS' "$WORK/freshness.log"
assert_failed_closed freshness

if run_fake running FAKE_RUNNING_SERVICE=collector; then echo "running service should abort" >&2; exit 1; fi
! grep -q ENGINE "$WORK/running.log"
! grep -q 'up -d ' "$WORK/running.log"
! grep -q HTTPS_READY "$WORK/running.log"
assert_failed_closed running

echo "production restore contract tests: 10 passed"
