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

PROJECT="avelren-restore-${RANDOM}-${RANDOM}"
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

compose() {
    MSYS_NO_PATHCONV=1 docker compose \
        --project-directory "$COMPOSE_PROJECT_DIR" \
        --env-file "$COMPOSE_ENV_FILE" \
        -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
    local status=$?
    trap - EXIT
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
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
      test: ["CMD-SHELL", "pg_isready -U avelren_admin -d postgres"]
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
readonly BACKUP_PASSWORD=ci-only
readonly MIGRATOR_PASSWORD=ci-only
readonly SOURCE_DB=avelren_restore_source_test
readonly TARGET_DB=restore_test
readonly MARKER=restore-integration-marker-v2
readonly DUMP="$WORK/source.sql.gz"
readonly UNEXPECTED_DUMP="$WORK/source-unexpected.sql.gz"
readonly MISSING_DUMP="$WORK/source-missing.sql.gz"
readonly BOOTSTRAP_DSN='postgresql://avelren_admin:ci-only@localhost:5432/postgres'
readonly MIGRATOR_SOURCE_DSN="postgresql://avelren_migrator:ci-only@db:5432/$SOURCE_DB"
readonly ADMIN_TARGET_DSN="postgresql://avelren_admin:ci-only@db:5432/$TARGET_DB"

run_restore() {
    local dump=$1
    AVELREN_STACK_DIR="$ROOT" \
    AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
    AVELREN_COMPOSE_PROJECT="$PROJECT" \
    AVELREN_DB_SERVICE=db \
    AVELREN_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    AVELREN_COMPOSE_ENV_GUARD=isolated \
    bash "$ROOT/deploy/restore.sh" "$dump" --target "$TARGET_DB"
}

compose up --detach --wait db
# The expression is evaluated inside the database container.
# shellcheck disable=SC2016
compose exec -T db sh -c '[ "$AVELREN_COMPOSE_ENV_GUARD" = isolated ]'

AVELREN_ADMIN_DSN="$BOOTSTRAP_DSN" \
AVELREN_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
AVELREN_MIGRATOR_PASSWORD="$MIGRATOR_PASSWORD" \
AVELREN_BACKUP_PASSWORD="$BACKUP_PASSWORD" \
AVELREN_COLLECTOR_PASSWORD=ci-only \
AVELREN_NOTIFIER_PASSWORD=ci-only \
AVELREN_WATCHDOG_PASSWORD=ci-only \
AVELREN_API_PASSWORD=ci-only \
compose exec -T \
    -e AVELREN_TEST_DB -e AVELREN_DB_NAME \
    -e AVELREN_ADMIN_DSN -e AVELREN_ADMIN_PASSWORD \
    -e AVELREN_MIGRATOR_PASSWORD -e AVELREN_BACKUP_PASSWORD \
    -e AVELREN_COLLECTOR_PASSWORD -e AVELREN_NOTIFIER_PASSWORD \
    -e AVELREN_WATCHDOG_PASSWORD -e AVELREN_API_PASSWORD \
    -e AVELREN_DB_NAME="$SOURCE_DB" -e AVELREN_TEST_DB=1 \
    db bash /workspace/deploy/postgres-bootstrap.sh fresh

DATABASE_URL="$MIGRATOR_SOURCE_DSN" compose run --rm --no-deps -T \
    -e DATABASE_URL test python -m avelren.migrate db/migrations

PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$SOURCE_DB" -v ON_ERROR_STOP=1 -q \
    -c "INSERT INTO checkpoints
        (id, title, for_vehicle_type, first_seen, last_seen)
        VALUES (987654320, '$MARKER', 1, now(), now());" \
    -c "INSERT INTO observations
        (time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused)
        VALUES (now(), 987654320, 60, 1, false);" \
    -c "CREATE TABLE public.unexpected_relation (marker text NOT NULL);" \
    -c "INSERT INTO public.unexpected_relation VALUES ('must-remain-admin-owned');" \
    -c "GRANT SELECT ON public.unexpected_relation TO avelren_backup;"

if PGPASSWORD="$BACKUP_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_backup -d "$SOURCE_DB" -v ON_ERROR_STOP=1 -q \
    -c "INSERT INTO checkpoints
        (id, title, for_vehicle_type, first_seen, last_seen)
        VALUES (987654319, 'backup-must-not-write', 1, now(), now());" \
    >"$WORK/backup-write.out" 2>&1; then
    echo 'restore integration failed: backup role inserted a marker' >&2
    exit 1
fi

PGPASSWORD="$BACKUP_PASSWORD" compose exec -T -e PGPASSWORD db \
    pg_dump --no-owner -U avelren_backup -d "$SOURCE_DB" | gzip -9 >"$UNEXPECTED_DUMP"
if run_restore "$UNEXPECTED_DUMP" >"$WORK/unexpected-restore.out" 2>&1; then
    echo 'restore integration failed: unexpected application relation passed ownership preflight' >&2
    exit 1
fi
grep -q 'restore application relation allowlist mismatch' "$WORK/unexpected-restore.out"
unexpected_state=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT relation.relname || ':' || owner.rolname || ':' ||
               (SELECT marker FROM public.unexpected_relation LIMIT 1)
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_roles AS owner ON owner.oid = relation.relowner
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'unexpected_relation';")
[ "$unexpected_state" = 'unexpected_relation:avelren_admin:must-remain-admin-owned' ]
canonical_owner_after_unexpected=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT tableowner FROM pg_tables
        WHERE schemaname = 'public' AND tablename = 'schema_migrations';")
[ "$canonical_owner_after_unexpected" = avelren_admin ] || {
    echo 'restore integration failed: ownership mutation began before unexpected-relation rejection' >&2
    exit 1
}

PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$SOURCE_DB" -v ON_ERROR_STOP=1 -q \
    -c 'DROP TABLE public.unexpected_relation;'

PGPASSWORD="$BACKUP_PASSWORD" compose exec -T -e PGPASSWORD db \
    pg_dump --no-owner -U avelren_backup -d "$SOURCE_DB" | gzip -9 >"$DUMP"

run_restore "$DUMP"

restored=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c 'SELECT title FROM checkpoints WHERE id = 987654320;')
[ "$restored" = "$MARKER" ] || {
    echo 'restore integration failed: deterministic marker missing' >&2
    exit 1
}
restored_owner=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename = 'schema_migrations';")
[ "$restored_owner" = avelren_migrator ] || {
    echo 'restore integration failed: application ownership was not restored to migrator' >&2
    exit 1
}

PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$SOURCE_DB" -v ON_ERROR_STOP=1 -q \
    -c 'DROP TABLE public.notification_cancels;'
PGPASSWORD="$BACKUP_PASSWORD" compose exec -T -e PGPASSWORD db \
    pg_dump --no-owner -U avelren_backup -d "$SOURCE_DB" | gzip -9 >"$MISSING_DUMP"
if run_restore "$MISSING_DUMP" >"$WORK/missing-restore.out" 2>&1; then
    echo 'restore integration failed: missing expected relation passed ownership preflight' >&2
    exit 1
fi
grep -q 'restore application relation allowlist mismatch' "$WORK/missing-restore.out"
missing_owner_state=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT tableowner FROM pg_tables
        WHERE schemaname = 'public' AND tablename = 'schema_migrations';")
[ "$missing_owner_state" = avelren_admin ] || {
    echo 'restore integration failed: ownership mutation began before missing-relation rejection' >&2
    exit 1
}
missing_relation=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT to_regclass('public.notification_cancels') IS NULL;")
[ "$missing_relation" = t ]

# Restore the unchanged canonical dump once more after the fail-closed fixture.
run_restore "$DUMP"

AVELREN_STACK_DIR="$ROOT" \
AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
AVELREN_COMPOSE_PROJECT="$PROJECT" \
AVELREN_VERIFY_APP_SERVICE=test \
AVELREN_VERIFY_MIGRATIONS_DIR=db/migrations \
AVELREN_VERIFY_DATABASE_URL="$ADMIN_TARGET_DSN" \
AVELREN_COMPOSE_ENV_GUARD=isolated \
bash "$ROOT/deploy/restore-verify.sh" "$TARGET_DB"

echo "restore integration passed: backup=read-only dump, target=$TARGET_DB, admin restore/schema/smoke verified"

bad_dump="$WORK/fails-after-pre.sql.gz"
{
    printf 'THIS IS NOT VALID SQL;\n'
    head -c 20000 /dev/urandom | base64
} | gzip -c >"$bad_dump"
failure_log="$WORK/failure.log"
if AVELREN_STACK_DIR="$ROOT" \
   AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
   AVELREN_COMPOSE_PROJECT="$PROJECT" \
   AVELREN_DB_SERVICE=db \
   AVELREN_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
   AVELREN_COMPOSE_ENV_GUARD=isolated \
   bash "$ROOT/deploy/restore.sh" "$bad_dump" --target "$TARGET_DB" \
       >"$failure_log" 2>&1; then
    echo 'restore failure after pre_restore was expected' >&2
    exit 1
fi
grep -q 'primary restore failure' "$failure_log"
grep -q 'timescaledb_post_restore cleanup succeeded' "$failure_log"
echo 'restore failure cleanup passed: post_restore attempted, primary failure preserved'
