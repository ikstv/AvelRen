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
    if [ -n "${FAKE_RUNNING_SERVICE:-}" ]; then
        printf '%s\n' "$FAKE_RUNNING_SERVICE"
    elif [ -n "${FAKE_POST_RUNNING_SERVICE:-}" ] && grep -q 'up -d caddy' "$FAKE_LOG"; then
        printf '%s\n' "$FAKE_POST_RUNNING_SERVICE"
    elif [ "$(cat "$FAKE_STATE" 2>/dev/null || true)" = running ]; then
        printf '%s\n' caddy api collector notifier watchdog
    fi
    exit 0
fi
if [[ "$args" == *' stop '* ]] && [ "${FAKE_CLEANUP_STOP_FAIL:-0}" = 1 ] && grep -q 'up -d caddy' "$FAKE_LOG"; then
    exit 41
fi
if [[ "$args" == *' stop '* ]]; then
    printf '%s\n' stopped >"$FAKE_STATE"
    exit 0
fi
if [[ "$args" == *' up -d caddy'* ]]; then
    printf '%s\n' running >"$FAKE_STATE"
    exit 0
fi
if [[ "$args" == *' exec -T api python '* ]]; then
    python -c 'import json,sys; v=json.load(sys.stdin); assert isinstance(v,dict); assert v.get("status") in {"ok","stale"}; assert "last_observation" in v; assert "age_seconds" in v'
    exit
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
if [ -n "${FAKE_CURL_BODY:-}" ]; then
    printf '%s\n' "$FAKE_CURL_BODY"
else
    printf '{"status":"ok","last_observation":null,"age_seconds":null}\n'
fi
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
    env PATH="$BIN:$PATH" FAKE_LOG="$WORK/$name.log" FAKE_STATE="$WORK/$name.state" \
        AVELREN_STACK_DIR="$WORK/stack" AVELREN_READINESS_TIMEOUT_SECONDS=1 \
        AVELREN_FRESHNESS_TIMEOUT_SECONDS=1 "$@" \
        bash "$ROOT/deploy/restore-production.sh" "$WORK/valid.sql.gz" \
        --confirm-production-restore AVELREN-PRODUCTION-RESTORE \
        >"$WORK/$name.out" 2>&1
}

assert_failed_closed() {
    local name=$1 log="$WORK/$1.log" out="$WORK/$1.out"
    if ! grep -q 'stop caddy' "$log" || \
       ! grep -q 'stop api collector notifier watchdog' "$log" || \
       grep -q 'production restore complete' "$out"; then
        echo "failed closed assertion: $name" >&2
        echo '--- service log ---' >&2
        sed -n '1,240p' "$log" >&2 || true
        echo '--- orchestrator output ---' >&2
        sed -n '1,240p' "$out" >&2 || true
        return 1
    fi
}

if ! run_fake success; then
    echo 'success scenario unexpectedly failed' >&2
    sed -n '1,240p' "$WORK/success.log" >&2 || true
    sed -n '1,240p' "$WORK/success.out" >&2 || true
    exit 1
fi
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

if run_fake malformed-json FAKE_CURL_BODY='debug {"status":"ok","last_observation":null,"age_seconds":null}'; then
    echo "malformed readiness JSON should fail" >&2; exit 1
fi
assert_failed_closed malformed-json

if run_fake nested-json FAKE_CURL_BODY='{"debug":{"status":"ok"},"last_observation":null,"age_seconds":null}'; then
    echo "nested readiness status should fail" >&2; exit 1
fi
assert_failed_closed nested-json

if run_fake freshness FAKE_FRESH_RESULT=f; then echo "freshness failure expected" >&2; exit 1; fi
grep -q HTTPS_READY "$WORK/freshness.log"
grep -q 'SELECT EXISTS' "$WORK/freshness.log"
assert_failed_closed freshness

if run_fake cleanup-stop FAKE_CURL_STATUS=1 FAKE_CLEANUP_STOP_FAIL=1; then
    echo "cleanup stop failure should preserve failure" >&2; exit 1
fi
grep -q 'cleanup stop failed' "$WORK/cleanup-stop.out"

if run_fake cleanup-running FAKE_CURL_STATUS=1 FAKE_POST_RUNNING_SERVICE=api; then
    echo "cleanup running service should preserve failure" >&2; exit 1
fi
grep -q 'cleanup left service running: api' "$WORK/cleanup-running.out"

if run_fake running FAKE_RUNNING_SERVICE=collector; then echo "running service should abort" >&2; exit 1; fi
! grep -q ENGINE "$WORK/running.log"
! grep -q 'up -d ' "$WORK/running.log"
! grep -q HTTPS_READY "$WORK/running.log"
assert_failed_closed running

echo "production restore contract tests: 14 passed"
