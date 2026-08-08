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
cp "$ROOT/deploy/restore.sh" "$ROOT/deploy/restore-verify.sh" "$WORK/stack/deploy/"
cat >"$BIN/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_LOG"
args="$*"
if [[ "$args" == *' ps --status running --services'* ]]; then exit 0; fi
if [[ "$args" == *' exec -T db psql '* ]]; then
    if [[ "$args" == *'SELECT count(*) FROM pg_stat_activity'* ]]; then
        printf '%s\n' "${FAKE_SESSIONS:-0}"
    elif [[ "$args" == *'SELECT EXISTS'* ]]; then
        printf 't\n'
    fi
fi
SH
cat >"$BIN/curl" <<'SH'
#!/usr/bin/env bash
exit "${FAKE_CURL_STATUS:-0}"
SH
chmod +x "$BIN/docker" "$BIN/curl"

# Replace the two internal scripts only in the isolated stack to observe
# orchestration ordering; engine behavior has separate real-DB integration.
cat >"$WORK/stack/deploy/restore.sh" <<'SH'
#!/usr/bin/env bash
printf 'ENGINE\n' >>"$FAKE_LOG"
[ "${FAKE_ENGINE_FAIL:-0}" != 1 ]
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
        --confirm-production-restore AVELREN-PRODUCTION-RESTORE
}

run_fake success
grep -q ENGINE "$WORK/success.log"; grep -q VERIFY "$WORK/success.log"

if run_fake sessions FAKE_SESSIONS=1; then echo "session gate should fail" >&2; exit 1; fi
! grep -q ENGINE "$WORK/sessions.log"
grep -q 'stop caddy' "$WORK/sessions.log"

if run_fake engine FAKE_ENGINE_FAIL=1; then echo "engine failure expected" >&2; exit 1; fi
grep -q 'stop caddy' "$WORK/engine.log"

if run_fake verify FAKE_VERIFY_FAIL=1; then echo "verify failure expected" >&2; exit 1; fi
grep -q VERIFY "$WORK/verify.log"; grep -q 'stop caddy' "$WORK/verify.log"

echo "production restore contract tests: 6 passed"
