#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")/.." && pwd)
readonly ROOT
ROOT_FOR_COMPOSE=$ROOT
if command -v cygpath >/dev/null 2>&1; then
    ROOT_FOR_COMPOSE=$(cygpath -w "$ROOT")
fi
readonly ROOT_FOR_COMPOSE

PROJECT="avelren-production-restore-${RANDOM}-${RANDOM}"
COMPOSE_FILE_POSIX=$(mktemp)
COMPOSE_PROJECT_DIR_POSIX=$(mktemp -d)
COMPOSE_ENV_FILE_POSIX="$COMPOSE_PROJECT_DIR_POSIX/compose.env"
WORK=$(mktemp -d)
readonly PROJECT COMPOSE_FILE_POSIX COMPOSE_PROJECT_DIR_POSIX COMPOSE_ENV_FILE_POSIX WORK

printf '%s\n' 'AVELREN_COMPOSE_ENV_GUARD=isolated' >"$COMPOSE_ENV_FILE_POSIX"
printf '%s\n' 'AVELREN_COMPOSE_ENV_GUARD=poison' >"$COMPOSE_PROJECT_DIR_POSIX/.env"

COMPOSE_FILE=$COMPOSE_FILE_POSIX
COMPOSE_PROJECT_DIR=$COMPOSE_PROJECT_DIR_POSIX
COMPOSE_ENV_FILE=$COMPOSE_ENV_FILE_POSIX
if command -v cygpath >/dev/null 2>&1; then
    COMPOSE_FILE=$(cygpath -w "$COMPOSE_FILE_POSIX")
    COMPOSE_PROJECT_DIR=$(cygpath -w "$COMPOSE_PROJECT_DIR_POSIX")
    COMPOSE_ENV_FILE=$(cygpath -w "$COMPOSE_ENV_FILE_POSIX")
fi
readonly COMPOSE_FILE COMPOSE_PROJECT_DIR COMPOSE_ENV_FILE

REAL_DOCKER=$(command -v docker)
PYTHON_BIN=${PYTHON_BIN:-python3}
readonly REAL_DOCKER PYTHON_BIN

real_compose() {
    MSYS_NO_PATHCONV=1 "$REAL_DOCKER" compose \
        --project-directory "$COMPOSE_PROJECT_DIR" \
        --env-file "$COMPOSE_ENV_FILE" \
        -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
    local status=$?
    trap - EXIT
    real_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -f "$COMPOSE_FILE_POSIX"
    rm -rf "$COMPOSE_PROJECT_DIR_POSIX" "$WORK"
    exit "$status"
}
trap cleanup EXIT

cat >"$COMPOSE_FILE_POSIX" <<EOF
services:
  db:
    image: timescale/timescaledb:2.17.2-pg16
    environment:
      POSTGRES_USER: avelren_admin
      POSTGRES_PASSWORD: ci-only
      POSTGRES_DB: postgres
      AVELREN_COMPOSE_ENV_GUARD: \${AVELREN_COMPOSE_ENV_GUARD:?missing disposable Compose env guard}
    volumes:
      - '$ROOT_FOR_COMPOSE:/workspace:ro'
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U avelren_admin -d postgres"]
      interval: 2s
      timeout: 2s
      retries: 30
  test:
    build:
      context: '$ROOT_FOR_COMPOSE'
      dockerfile: app/Dockerfile.test
    environment:
      AVELREN_TEST_DB: "1"
    depends_on:
      db:
        condition: service_healthy
EOF

readonly ADMIN_PASSWORD=ci-only
readonly MIGRATOR_PASSWORD=ci-only
readonly BACKUP_PASSWORD=ci-only
readonly COLLECTOR_PASSWORD=ci-only
readonly SOURCE_DB=avelren_production_source_test
readonly PREFIX_SOURCE_DB=avelren_prefix_source_test
readonly TARGET_DB=avelren
readonly MARKER=production-orchestrator-marker-v2
readonly DUMP="$WORK/source.sql.gz"
readonly PREFIX_DUMP="$WORK/source-prefix.sql.gz"
readonly PREFIX_MIGRATIONS="$WORK/migrations-001-009"
PREFIX_MIGRATIONS_FOR_COMPOSE=$PREFIX_MIGRATIONS
if command -v cygpath >/dev/null 2>&1; then
    PREFIX_MIGRATIONS_FOR_COMPOSE=$(cygpath -w "$PREFIX_MIGRATIONS")
fi
readonly PREFIX_MIGRATIONS_FOR_COMPOSE
readonly BOOTSTRAP_DSN='postgresql://avelren_admin:ci-only@localhost:5432/postgres'
readonly MIGRATOR_SOURCE_DSN="postgresql://avelren_migrator:ci-only@db:5432/$SOURCE_DB"
readonly MIGRATOR_PREFIX_DSN="postgresql://avelren_migrator:ci-only@db:5432/$PREFIX_SOURCE_DB"
readonly ADMIN_TARGET_DSN="postgresql://avelren_admin:ci-only@db:5432/$TARGET_DB"
readonly MIGRATOR_TARGET_DSN="postgresql://avelren_migrator:ci-only@db:5432/$TARGET_DB"
readonly API_TARGET_DSN="postgresql://avelren_api:ci-only@db:5432/$TARGET_DB"

bootstrap_database() {
    local database=$1
    AVELREN_ADMIN_DSN="$BOOTSTRAP_DSN" \
    AVELREN_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    AVELREN_MIGRATOR_PASSWORD="$MIGRATOR_PASSWORD" \
    AVELREN_BACKUP_PASSWORD="$BACKUP_PASSWORD" \
    AVELREN_COLLECTOR_PASSWORD="$COLLECTOR_PASSWORD" \
    AVELREN_NOTIFIER_PASSWORD=ci-only \
    AVELREN_WATCHDOG_PASSWORD=ci-only \
    AVELREN_API_PASSWORD=ci-only \
    real_compose exec -T \
        -e AVELREN_ADMIN_DSN -e AVELREN_ADMIN_PASSWORD \
        -e AVELREN_MIGRATOR_PASSWORD -e AVELREN_BACKUP_PASSWORD \
        -e AVELREN_COLLECTOR_PASSWORD -e AVELREN_NOTIFIER_PASSWORD \
        -e AVELREN_WATCHDOG_PASSWORD -e AVELREN_API_PASSWORD \
        -e AVELREN_DB_NAME="$database" -e AVELREN_TEST_DB=1 \
        db bash /workspace/deploy/postgres-bootstrap.sh fresh
}

real_compose up --detach --wait db
# The expression is evaluated inside the database container.
# shellcheck disable=SC2016
real_compose exec -T db sh -c '[ "$AVELREN_COMPOSE_ENV_GUARD" = isolated ]'

bootstrap_database "$SOURCE_DB"
DATABASE_URL="$MIGRATOR_SOURCE_DSN" real_compose run --rm --no-deps -T \
    -e DATABASE_URL test python -m avelren.migrate db/migrations
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$SOURCE_DB" -v ON_ERROR_STOP=1 -q \
    -c "INSERT INTO checkpoints
        (id, title, for_vehicle_type, first_seen, last_seen)
        VALUES (987654321, '$MARKER', 1, now(), now());" \
    -c "INSERT INTO observations
        (time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused)
        VALUES (now(), 987654321, 60, 1, false);"

if PGPASSWORD="$BACKUP_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_backup -d "$SOURCE_DB" -v ON_ERROR_STOP=1 -q \
    -c "INSERT INTO checkpoints
        (id, title, for_vehicle_type, first_seen, last_seen)
        VALUES (987654320, 'backup-must-not-write', 1, now(), now());" \
    >"$WORK/backup-write.out" 2>&1; then
    echo 'production restore integration failed: backup role inserted a marker' >&2
    exit 1
fi
PGPASSWORD="$BACKUP_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    pg_dump --no-owner -U avelren_backup -d "$SOURCE_DB" | gzip -9 >"$DUMP"

# Build a genuine N-1 backup with physical schema and recorded history through
# 009 only. The explicit backup grants below are fixture preparation: production
# 009 predates the backup role, so admin grants only the read capabilities needed
# to prove its dump path. Migration 010 is deliberately not executed here.
mkdir -p "$PREFIX_MIGRATIONS"
cp "$ROOT"/db/migrations/00[1-9]_*.sql "$PREFIX_MIGRATIONS/"
bootstrap_database "$PREFIX_SOURCE_DB"
DATABASE_URL="$MIGRATOR_PREFIX_DSN" real_compose run --rm --no-deps -T \
    -v "$PREFIX_MIGRATIONS_FOR_COMPOSE:/prefix-migrations:ro" -e DATABASE_URL \
    test python -m avelren.migrate /prefix-migrations
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$PREFIX_SOURCE_DB" -v ON_ERROR_STOP=1 -q \
    -c "GRANT CONNECT ON DATABASE $PREFIX_SOURCE_DB TO avelren_backup;" \
    -c "GRANT USAGE ON SCHEMA public TO avelren_backup;" \
    -c "GRANT SELECT ON ALL TABLES IN SCHEMA public TO avelren_backup;" \
    -c "GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO avelren_backup;" \
    -c "INSERT INTO checkpoints
        (id, title, for_vehicle_type, first_seen, last_seen)
        VALUES (987654322, '$MARKER', 1, now(), now());" \
    -c "INSERT INTO observations
        (time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused)
        VALUES (now(), 987654322, 60, 1, false);"
prefix_latest_before_dump=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$PREFIX_SOURCE_DB" -At \
    -c 'SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1;')
[ "$prefix_latest_before_dump" = 009_observability ]
prefix_010_count_before_dump=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$PREFIX_SOURCE_DB" -At \
    -c "SELECT count(*) FROM schema_migrations WHERE version = '010_postgresql_least_privilege';")
[ "$prefix_010_count_before_dump" = 0 ]
prefix_collector_access_before_dump=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$PREFIX_SOURCE_DB" -At \
    -c "SELECT has_table_privilege('avelren_collector', 'checkpoints', 'SELECT');")
[ "$prefix_collector_access_before_dump" = f ]
PGPASSWORD="$BACKUP_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    pg_dump --no-owner -U avelren_backup -d "$PREFIX_SOURCE_DB" | gzip -9 >"$PREFIX_DUMP"

# Service lifecycle and HTTPS remain isolated process boundaries. Database
# exec/run calls are delegated to the real disposable Docker project.
BIN="$WORK/bin"
mkdir -p "$BIN"
cat >"$BIN/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$DR_SERVICE_LOG"
case " $* " in
    *' exec -T api python '*)
        "$PYTHON_BIN" -c 'import json,sys; v=json.load(sys.stdin); assert isinstance(v,dict); assert v.get("status") in {"ok","stale"}; assert "last_observation" in v; assert "age_seconds" in v'
        exit
        ;;
    *' ps --status running --services '*)
        if [ "$(cat "$DR_STATE" 2>/dev/null || true)" = running ]; then
            printf '%s\n' caddy api collector notifier watchdog
        fi
        exit 0
        ;;
    *' up -d api collector notifier watchdog '*)
        PGPASSWORD="$AVELREN_COLLECTOR_PASSWORD" "$REAL_DOCKER" compose \
            --project-directory "$DR_PROJECT_DIR" --env-file "$DR_ENV_FILE" \
            -p "$DR_PROJECT" -f "$DR_COMPOSE_FILE" exec -T -e PGPASSWORD db \
            psql -U avelren_collector -d avelren -q \
            -c "INSERT INTO collector_runs (time, rows_written, error) VALUES (now(), 1, NULL);"
        exit 0
        ;;
    *' up -d migrate '*)
        DATABASE_URL="$AVELREN_MIGRATOR_DATABASE_URL" "$REAL_DOCKER" compose \
            --project-directory "$DR_PROJECT_DIR" --env-file "$DR_ENV_FILE" \
            -p "$DR_PROJECT" -f "$DR_COMPOSE_FILE" run --rm --no-deps -T \
            -e DATABASE_URL test python -m avelren.migrate db/migrations
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
    env PATH="$BIN:$PATH" REAL_DOCKER="$REAL_DOCKER" PYTHON_BIN="$PYTHON_BIN" \
        DR_SERVICE_LOG="$WORK/services.log" DR_STATE="$WORK/service.state" \
        DR_PROJECT="$PROJECT" DR_COMPOSE_FILE="$COMPOSE_FILE" \
        DR_PROJECT_DIR="$COMPOSE_PROJECT_DIR" DR_ENV_FILE="$COMPOSE_ENV_FILE" \
        AVELREN_COMPOSE_ENV_GUARD=isolated \
        AVELREN_STACK_DIR="$ROOT" AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
        AVELREN_COMPOSE_PROJECT="$PROJECT" AVELREN_DB_SERVICE=db \
        AVELREN_VERIFY_SCHEMA_SERVICE=test AVELREN_VERIFY_API_SERVICE=test \
        AVELREN_VERIFY_MIGRATIONS_DIR=db/migrations \
        AVELREN_ADMIN_PASSWORD="$ADMIN_PASSWORD" AVELREN_ADMIN_DSN="$ADMIN_TARGET_DSN" \
        AVELREN_MIGRATOR_DSN="$MIGRATOR_TARGET_DSN" AVELREN_API_DSN="$API_TARGET_DSN" \
        AVELREN_MIGRATOR_DATABASE_URL="$MIGRATOR_TARGET_DSN" \
        AVELREN_COLLECTOR_PASSWORD="$COLLECTOR_PASSWORD" \
        AVELREN_READINESS_URL=https://disposable.invalid/health \
        AVELREN_READINESS_TIMEOUT_SECONDS=2 AVELREN_FRESHNESS_TIMEOUT_SECONDS=2 \
        AVELREN_PRE_RESTORE_SNAPSHOT_DIR="$WORK/pre-restore-snapshots" \
        "$@" bash "$ROOT/deploy/restore-production.sh" "$dump" \
        --confirm-production-restore AVELREN-PRODUCTION-RESTORE
}

# M-13 preconditions: production restore OVERWRITES an existing production
# database, and the pre-restore snapshot exists to capture that database before
# it is destroyed. The test must therefore restore INTO a real, pre-existing
# `avelren` — otherwise the orchestrator's `pg_dump -d avelren` fails with
# "database avelren does not exist", no snapshot is produced, and the M-13
# assertion below can never pass. Bootstrap + migrate + seed a distinct
# pre-restore marker so the snapshot dumps genuine prior production state
# (id 987654319 is overwritten by the restore's 987654321 marker).
bootstrap_database "$TARGET_DB"
DATABASE_URL="$MIGRATOR_TARGET_DSN" real_compose run --rm --no-deps -T \
    -e DATABASE_URL test python -m avelren.migrate db/migrations
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -v ON_ERROR_STOP=1 -q \
    -c "INSERT INTO checkpoints
        (id, title, for_vehicle_type, first_seen, last_seen)
        VALUES (987654319, 'pre-restore-original-state', 1, now(), now());"

run_orchestrator "$DUMP"
restored=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c 'SELECT title FROM checkpoints WHERE id=987654321;')
[ "$restored" = "$MARKER" ]

# M-13: знімок поточної бази справді зроблено ДО знищення (реальний pg_dump).
pre_restore_snap=$(ls "$WORK/pre-restore-snapshots"/avelren-pre-restore-*.sql.gz 2>/dev/null | head -1)
[ -n "$pre_restore_snap" ] || { echo 'pre-restore snapshot не створено' >&2; exit 1; }
gzip -t "$pre_restore_snap"
grep -q 'stop caddy' "$WORK/services.log"
grep -q 'up -d caddy' "$WORK/services.log"
grep -q HTTPS_READY "$WORK/services.log"
if grep -Eq -- 'psql -U (avelren|avelren_backup|avelren_migrator)( |$)' "$WORK/services.log"; then
    echo 'production orchestration logged a forbidden database role' >&2
    exit 1
fi
if grep -q 'ci-only' "$WORK/services.log"; then
    echo 'production orchestration logged a database credential' >&2
    exit 1
fi

run_orchestrator "$PREFIX_DUMP"
prefix_marker=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c 'SELECT title FROM checkpoints WHERE id=987654322;')
[ "$prefix_marker" = "$MARKER" ]
latest_migration=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c 'SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1;')
[ "$latest_migration" = 010_postgresql_least_privilege ]
prefix_collector_access_after_restore=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT has_table_privilege('avelren_collector', 'checkpoints', 'SELECT');")
[ "$prefix_collector_access_after_restore" = t ]
prefix_schema_owner=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename = 'schema_migrations';")
[ "$prefix_schema_owner" = avelren_migrator ]

before_lines=$(wc -l <"$WORK/services.log")
if run_orchestrator "$DUMP" FAKE_CURL_STATUS=1 >"$WORK/readiness-failure.log" 2>&1; then
    echo 'post-engine readiness failure expected' >&2
    exit 1
fi
readiness_log=$(tail -n +$((before_lines + 1)) "$WORK/services.log")
[ "$(printf '%s\n' "$readiness_log" | grep -c 'stop caddy')" -ge 2 ]
[ "$(cat "$WORK/service.state")" = stopped ]
grep -q 'RESTORE FAILED' "$WORK/readiness-failure.log"

PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -c 'SELECT pg_sleep(20);' >/dev/null &
holder=$!
sleep 2
before_lines=$(wc -l <"$WORK/services.log")
if run_orchestrator "$DUMP" >"$WORK/session-failure.log" 2>&1; then
    echo 'unknown active session should block production restore' >&2
    kill "$holder" 2>/dev/null || true
    exit 1
fi
kill "$holder" 2>/dev/null || true
wait "$holder" 2>/dev/null || true
grep -q 'active sessions' "$WORK/session-failure.log"
still_present=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c 'SELECT title FROM checkpoints WHERE id=987654321;')
[ "$still_present" = "$MARKER" ]
after_log=$(tail -n +$((before_lines + 1)) "$WORK/services.log")
if printf '%s\n' "$after_log" | grep -q ' dropdb '; then
    echo 'session gate allowed destructive restore command' >&2
    exit 1
fi

echo 'production restore integration passed: restricted dump/admin restore, N-1 migration, schema, smoke, restart, readiness, freshness, session gate'
