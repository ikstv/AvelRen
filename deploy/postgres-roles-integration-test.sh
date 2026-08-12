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
PROJECT="avelren-roles-${RANDOM}-${RANDOM}"
readonly PROJECT
COMPOSE_FILE_POSIX=$(mktemp)
COMPOSE_PROJECT_DIR_POSIX=$(mktemp -d)
COMPOSE_ENV_FILE_POSIX="$COMPOSE_PROJECT_DIR_POSIX/compose.env"
readonly COMPOSE_FILE_POSIX COMPOSE_PROJECT_DIR_POSIX COMPOSE_ENV_FILE_POSIX

# Compose must never discover a developer's repository .env.  This disposable
# project directory deliberately contains a poison default .env; the service
# guard below proves that only this explicit test-only env file was used.
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

usage() {
    printf 'usage: %s [--privileges-only|--positive-only]\n' "$0" >&2
    exit 2
}

PYTEST_ARGS=()
case "${1:-}" in
    "") ;;
    --privileges-only) PYTEST_ARGS=(-k "not positive") ;;
    --positive-only) PYTEST_ARGS=(-k positive) ;;
    *) usage ;;
esac

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
    rm -rf "$COMPOSE_PROJECT_DIR_POSIX"
    exit "$status"
}
trap cleanup EXIT

cat >"$COMPOSE_FILE" <<EOF
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

readonly BOOTSTRAP_DSN='postgresql://avelren_admin:ci-only@localhost:5432/postgres'
readonly TEST_DATABASE='avelren_roles_test'
readonly ADMIN_DATABASE_URL="postgresql://avelren_admin:ci-only@db:5432/$TEST_DATABASE"
readonly MIGRATOR_DATABASE_URL="postgresql://avelren_migrator:ci-only@db:5432/$TEST_DATABASE"
readonly BACKUP_DATABASE_URL="postgresql://avelren_backup:ci-only@db:5432/$TEST_DATABASE"
readonly COLLECTOR_DATABASE_URL="postgresql://avelren_collector:ci-only@db:5432/$TEST_DATABASE"
readonly NOTIFIER_DATABASE_URL="postgresql://avelren_notifier:ci-only@db:5432/$TEST_DATABASE"
readonly WATCHDOG_DATABASE_URL="postgresql://avelren_watchdog:ci-only@db:5432/$TEST_DATABASE"
readonly API_DATABASE_URL="postgresql://avelren_api:ci-only@db:5432/$TEST_DATABASE"

run_bootstrap() {
    compose exec -T \
    -e AVELREN_TEST_DB=1 \
    -e AVELREN_DB_NAME="$TEST_DATABASE" \
    -e AVELREN_ADMIN_DSN="$BOOTSTRAP_DSN" \
    -e AVELREN_ADMIN_PASSWORD=ci-only \
    -e AVELREN_MIGRATOR_PASSWORD=ci-only \
    -e AVELREN_BACKUP_PASSWORD=ci-only \
    -e AVELREN_COLLECTOR_PASSWORD=ci-only \
    -e AVELREN_NOTIFIER_PASSWORD=ci-only \
    -e AVELREN_WATCHDOG_PASSWORD=ci-only \
    -e AVELREN_API_PASSWORD=ci-only \
    db bash /workspace/deploy/postgres-bootstrap.sh fresh
}

compose up --detach --wait db
if ! compose exec -T db sh -c '[ "$AVELREN_COMPOSE_ENV_GUARD" = isolated ]'; then
    printf '%s\n' 'postgres roles integration: explicit Compose env isolation failed' >&2
    exit 1
fi
run_bootstrap

compose run --rm --no-deps -T \
    -e DATABASE_URL="$MIGRATOR_DATABASE_URL" \
    -e AVELREN_TEST_DB=1 \
    test python -m avelren.migrate db/migrations

# PostgreSQL 16 keeps SET ROLE separate from inheritance.  Prove the exploit on
# the real server first, then require idempotent bootstrap to fail closed before
# it can accept a non-canonical membership graph.
compose exec -T db psql -U avelren_admin -d postgres -v ON_ERROR_STOP=1 -q \
    -c 'GRANT avelren_collector TO avelren_api;'
membership_exploit=$(compose exec -T -e PGPASSWORD=ci-only db \
    psql -h 127.0.0.1 -U avelren_api -d "$TEST_DATABASE" \
    -v ON_ERROR_STOP=1 -qAt \
    -c "SET ROLE avelren_collector;
        INSERT INTO collector_runs (time, rows_written, error)
        VALUES (now(), 0, 'membership-red');
        SELECT current_user;")
[ "$membership_exploit" = avelren_collector ] || {
    printf '%s\n' 'postgres roles integration: SET ROLE exploit fixture was not proven' >&2
    exit 1
}
if run_bootstrap >"$COMPOSE_PROJECT_DIR_POSIX/forbidden-membership.out" 2>&1; then
    printf '%s\n' 'postgres roles integration: bootstrap accepted a forbidden membership' >&2
    exit 1
fi
grep -Fxq 'postgres bootstrap: forbidden canonical role membership detected' \
    "$COMPOSE_PROJECT_DIR_POSIX/forbidden-membership.out"

compose exec -T db psql -U avelren_admin -d postgres -v ON_ERROR_STOP=1 -q \
    -c 'REVOKE avelren_collector FROM avelren_api;'
run_bootstrap
canonical_memberships=$(compose exec -T db psql -U avelren_admin -d postgres -qAt \
    -c "SELECT count(*)
        FROM pg_auth_members AS membership
        JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
        JOIN pg_roles AS member_role ON member_role.oid = membership.member
        WHERE granted_role.rolname LIKE 'avelren_%'
           OR member_role.rolname LIKE 'avelren_%';")
[ "$canonical_memberships" = 0 ] || {
    printf '%s\n' 'postgres roles integration: clean bootstrap left canonical memberships' >&2
    exit 1
}

compose run --rm --no-deps -T \
    -e DATABASE_URL="$ADMIN_DATABASE_URL" \
    -e ADMIN_DATABASE_URL="$ADMIN_DATABASE_URL" \
    -e MIGRATOR_DATABASE_URL="$MIGRATOR_DATABASE_URL" \
    -e BACKUP_DATABASE_URL="$BACKUP_DATABASE_URL" \
    -e COLLECTOR_DATABASE_URL="$COLLECTOR_DATABASE_URL" \
    -e NOTIFIER_DATABASE_URL="$NOTIFIER_DATABASE_URL" \
    -e WATCHDOG_DATABASE_URL="$WATCHDOG_DATABASE_URL" \
    -e API_DATABASE_URL="$API_DATABASE_URL" \
    -e AVELREN_TEST_DB=1 \
    test sh -c 'ruff check app/tests/test_db_privileges.py && python -m pytest app/tests/test_db_privileges.py -q -p no:cacheprovider "$@"' \
    sh "${PYTEST_ARGS[@]}"
