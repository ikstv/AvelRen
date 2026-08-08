#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
COMPOSE_FILE="$ROOT/docker-compose.backend-test.yml"
PROJECT=avelren_production_restore_integration
WORK=$(mktemp -d)
REAL_DOCKER=$(command -v docker)
trap '"$REAL_DOCKER" compose -p "$PROJECT" -f "$COMPOSE_FILE" down --volumes --remove-orphans >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT

real_compose() { "$REAL_DOCKER" compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"; }
SOURCE_DB=avelren_ci
TARGET_DB=avelren
MARKER=production-orchestrator-marker-v1
DUMP="$WORK/source.sql.gz"

real_compose up -d test-db
real_compose run --rm -T test python -m avelren.migrate db/migrations
real_compose exec -T test-db psql -U avelren -d "$SOURCE_DB" -q \
    -c 'CREATE TABLE restore_integration_marker (value text PRIMARY KEY);' \
    -c "INSERT INTO restore_integration_marker (value) VALUES ('$MARKER');" \
    -c "INSERT INTO checkpoints
        (id, title, for_vehicle_type, first_seen, last_seen)
        VALUES (987654321, 'DR fixture', 1, now(), now());" \
    -c "INSERT INTO observations
        (time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused)
        VALUES (now(), 987654321, 60, 1, false);"
real_compose exec -T test-db pg_dump -U avelren -d "$SOURCE_DB" --no-owner | gzip -9 >"$DUMP"

# Service lifecycle and HTTPS are isolated process boundaries in this stack;
# DB exec/run calls still go to the real Docker daemon.
BIN="$WORK/bin"; mkdir -p "$BIN"
cat >"$BIN/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$DR_SERVICE_LOG"
case " $* " in
    *' stop '*|*' ps --status running --services '*|*' up -d '*|*' wait migrate '*) exit 0 ;;
    *) exec "$REAL_DOCKER" "$@" ;;
esac
SH
cat >"$BIN/curl" <<'SH'
#!/usr/bin/env bash
printf 'HTTPS_READY\n' >>"$DR_SERVICE_LOG"
exit 0
SH
chmod +x "$BIN/docker" "$BIN/curl"

run_orchestrator() {
    env PATH="$BIN:$PATH" REAL_DOCKER="$REAL_DOCKER" DR_SERVICE_LOG="$WORK/services.log" \
        AVELREN_STACK_DIR="$ROOT" AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
        AVELREN_COMPOSE_PROJECT="$PROJECT" AVELREN_DB_SERVICE=test-db \
        AVELREN_VERIFY_APP_SERVICE=test \
        AVELREN_VERIFY_MIGRATIONS_DIR=/workspace/db/migrations \
        AVELREN_VERIFY_DATABASE_URL="postgresql://avelren:ci-only@test-db:5432/$TARGET_DB" \
        AVELREN_READINESS_URL=https://disposable.invalid/health \
        AVELREN_READINESS_TIMEOUT_SECONDS=2 AVELREN_FRESHNESS_TIMEOUT_SECONDS=2 \
        bash "$ROOT/deploy/restore-production.sh" "$DUMP" \
        --confirm-production-restore AVELREN-PRODUCTION-RESTORE
}

run_orchestrator
restored=$(real_compose exec -T test-db psql -U avelren -d "$TARGET_DB" -At \
    -c "SELECT value FROM restore_integration_marker WHERE value='$MARKER';")
[ "$restored" = "$MARKER" ]
grep -q 'stop caddy' "$WORK/services.log"
grep -q 'up -d caddy' "$WORK/services.log"
grep -q HTTPS_READY "$WORK/services.log"

# Unknown connection must abort before restore; the existing marker proves the
# target was not dropped. The held psql is intentionally not a known service.
real_compose exec -T test-db psql -U avelren -d "$TARGET_DB" \
    -c 'SELECT pg_sleep(20);' >/dev/null &
holder=$!
sleep 2
before_lines=$(wc -l <"$WORK/services.log")
if run_orchestrator >"$WORK/session-failure.log" 2>&1; then
    echo "unknown active session should block production restore" >&2
    kill "$holder" 2>/dev/null || true
    exit 1
fi
kill "$holder" 2>/dev/null || true
wait "$holder" 2>/dev/null || true
grep -q 'active sessions' "$WORK/session-failure.log"
still_present=$(real_compose exec -T test-db psql -U avelren -d "$TARGET_DB" -At \
    -c "SELECT value FROM restore_integration_marker WHERE value='$MARKER';")
[ "$still_present" = "$MARKER" ]
after_log=$(tail -n +$((before_lines + 1)) "$WORK/services.log")
! printf '%s\n' "$after_log" | grep -q 'restore.sh'

echo "production restore integration passed: restore, marker, schema, read-only smoke, restart, readiness, session gate"
