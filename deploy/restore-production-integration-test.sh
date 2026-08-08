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
PREFIX_SOURCE_DB=avelren_prefix
TARGET_DB=avelren
MARKER=production-orchestrator-marker-v1
DUMP="$WORK/source.sql.gz"
PREFIX_DUMP="$WORK/source-prefix.sql.gz"
PREFIX_MIGRATIONS="$WORK/migrations-001-008"

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

# Build a real N-1 backup: migration history and physical schema are both the
# contiguous 001..008 prefix. The production migrate gate must apply 009.
mkdir -p "$PREFIX_MIGRATIONS"
cp "$ROOT"/db/migrations/00[1-8]_*.sql "$PREFIX_MIGRATIONS/"
real_compose exec -T test-db createdb -U avelren "$PREFIX_SOURCE_DB"
real_compose run --rm -T \
    -v "$PREFIX_MIGRATIONS:/prefix-migrations:ro" \
    -e "DATABASE_URL=postgresql://avelren:ci-only@test-db:5432/$PREFIX_SOURCE_DB" \
    test python -m avelren.migrate /prefix-migrations
real_compose exec -T test-db psql -U avelren -d "$PREFIX_SOURCE_DB" -q \
    -c 'CREATE TABLE restore_prefix_marker (value text PRIMARY KEY);' \
    -c "INSERT INTO restore_prefix_marker (value) VALUES ('$MARKER');"
real_compose exec -T test-db pg_dump -U avelren -d "$PREFIX_SOURCE_DB" --no-owner | gzip -9 >"$PREFIX_DUMP"

# Service lifecycle and HTTPS are isolated process boundaries in this stack;
# DB exec/run calls still go to the real Docker daemon.
BIN="$WORK/bin"; mkdir -p "$BIN"
cat >"$BIN/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$DR_SERVICE_LOG"
case " $* " in
    *' exec -T api python '*)
        python -c 'import json,sys; v=json.load(sys.stdin); assert isinstance(v,dict); assert v.get("status") in {"ok","stale"}; assert "last_observation" in v; assert "age_seconds" in v'
        exit
        ;;
    *' ps --status running --services '*)
        if [ "$(cat "$DR_STATE" 2>/dev/null || true)" = running ]; then
            printf '%s\n' caddy api collector notifier watchdog
        fi
        exit 0
        ;;
    *' up -d api collector notifier watchdog '*)
        "$REAL_DOCKER" compose -p "$DR_PROJECT" -f "$DR_COMPOSE_FILE" \
            exec -T test-db psql -U avelren -d avelren -q \
            -c "INSERT INTO collector_runs (time, rows_written, error) VALUES (now(), 1, NULL);"
        exit 0
        ;;
    *' up -d migrate '*)
        "$REAL_DOCKER" compose -p "$DR_PROJECT" -f "$DR_COMPOSE_FILE" \
            run --rm -T -e "DATABASE_URL=$AVELREN_VERIFY_DATABASE_URL" \
            test python -m avelren.migrate /workspace/db/migrations
        exit
        ;;
    *' up -d caddy '*) printf '%s\n' running >"$DR_STATE"; exit 0 ;;
    *' stop '*) printf '%s\n' stopped >"$DR_STATE"; exit 0 ;;
    *' up -d '*|*' wait migrate '*) exit 0 ;;
    *) exec "$REAL_DOCKER" "$@" ;;
esac
SH
cat >"$BIN/curl" <<'SH'
#!/usr/bin/env bash
printf 'HTTPS_READY\n' >>"$DR_SERVICE_LOG"
printf '{"status":"ok","last_observation":null,"age_seconds":null}\n'
exit "${FAKE_CURL_STATUS:-0}"
SH
chmod +x "$BIN/docker" "$BIN/curl"

run_orchestrator() {
    local dump=$1
    shift
    env PATH="$BIN:$PATH" REAL_DOCKER="$REAL_DOCKER" DR_SERVICE_LOG="$WORK/services.log" \
        DR_PROJECT="$PROJECT" DR_COMPOSE_FILE="$COMPOSE_FILE" DR_STATE="$WORK/service.state" \
        AVELREN_STACK_DIR="$ROOT" AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
        AVELREN_COMPOSE_PROJECT="$PROJECT" AVELREN_DB_SERVICE=test-db \
        AVELREN_VERIFY_APP_SERVICE=test \
        AVELREN_VERIFY_MIGRATIONS_DIR=/workspace/db/migrations \
        AVELREN_VERIFY_DATABASE_URL="postgresql://avelren:ci-only@test-db:5432/$TARGET_DB" \
        AVELREN_READINESS_URL=https://disposable.invalid/health \
        AVELREN_READINESS_TIMEOUT_SECONDS=2 AVELREN_FRESHNESS_TIMEOUT_SECONDS=2 \
        "$@" \
        bash "$ROOT/deploy/restore-production.sh" "$dump" \
        --confirm-production-restore AVELREN-PRODUCTION-RESTORE
}

run_orchestrator "$DUMP"
restored=$(real_compose exec -T test-db psql -U avelren -d "$TARGET_DB" -At \
    -c "SELECT value FROM restore_integration_marker WHERE value='$MARKER';")
[ "$restored" = "$MARKER" ]
grep -q 'stop caddy' "$WORK/services.log"
grep -q 'up -d caddy' "$WORK/services.log"
grep -q HTTPS_READY "$WORK/services.log"

# Restore the real 001..008 backup, run the real migrate gate, and prove the
# current migration was appended before full schema verification completed.
run_orchestrator "$PREFIX_DUMP"
prefix_marker=$(real_compose exec -T test-db psql -U avelren -d "$TARGET_DB" -At \
    -c "SELECT value FROM restore_prefix_marker WHERE value='$MARKER';")
[ "$prefix_marker" = "$MARKER" ]
latest_migration=$(real_compose exec -T test-db psql -U avelren -d "$TARGET_DB" -At \
    -c "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1;")
[ "$latest_migration" = 009_observability ]

# Actual engine succeeds, then readiness fails. The outer trap must perform a
# second maintenance stop after the temporary restart and leave final state stopped.
before_lines=$(wc -l <"$WORK/services.log")
if run_orchestrator "$DUMP" FAKE_CURL_STATUS=1 >"$WORK/readiness-failure.log" 2>&1; then
    echo "post-engine readiness failure expected" >&2
    exit 1
fi
readiness_log=$(tail -n +$((before_lines + 1)) "$WORK/services.log")
[ "$(printf '%s\n' "$readiness_log" | grep -c 'stop caddy')" -ge 2 ]
[ "$(cat "$WORK/service.state")" = stopped ]
grep -q 'RESTORE FAILED' "$WORK/readiness-failure.log"

# Unknown connection must abort before restore; the existing marker proves the
# target was not dropped. The held psql is intentionally not a known service.
real_compose exec -T test-db psql -U avelren -d "$TARGET_DB" \
    -c 'SELECT pg_sleep(20);' >/dev/null &
holder=$!
sleep 2
before_lines=$(wc -l <"$WORK/services.log")
if run_orchestrator "$DUMP" >"$WORK/session-failure.log" 2>&1; then
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
! printf '%s\n' "$after_log" | grep -q 'DROP DATABASE'

echo "production restore integration passed: restore, marker, N-1 migration, schema, read-only smoke, restart, readiness, session gate"
