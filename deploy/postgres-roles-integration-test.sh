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
    printf 'usage: %s [--privileges-only]\n' "$0" >&2
    exit 2
}

case "${1:-}" in
    ""|--privileges-only) ;;
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

readonly BOOTSTRAP_DSN='postgresql://avelren_admin:ci-only@localhost:5432/postgres'
readonly TEST_DATABASE='avelren_roles_test'
readonly ADMIN_DATABASE_URL="postgresql://avelren_admin:ci-only@db:5432/$TEST_DATABASE"
readonly MIGRATOR_DATABASE_URL="postgresql://avelren_migrator:ci-only@db:5432/$TEST_DATABASE"
readonly BACKUP_DATABASE_URL="postgresql://avelren_backup:ci-only@db:5432/$TEST_DATABASE"
readonly COLLECTOR_DATABASE_URL="postgresql://avelren_collector:ci-only@db:5432/$TEST_DATABASE"
readonly NOTIFIER_DATABASE_URL="postgresql://avelren_notifier:ci-only@db:5432/$TEST_DATABASE"
readonly WATCHDOG_DATABASE_URL="postgresql://avelren_watchdog:ci-only@db:5432/$TEST_DATABASE"
readonly API_DATABASE_URL="postgresql://avelren_api:ci-only@db:5432/$TEST_DATABASE"

compose up --detach --wait db
if ! compose exec -T db sh -c '[ "$AVELREN_COMPOSE_ENV_GUARD" = isolated ]'; then
    printf '%s\n' 'postgres roles integration: explicit Compose env isolation failed' >&2
    exit 1
fi
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

compose run --rm --no-deps -T \
    -e DATABASE_URL="$MIGRATOR_DATABASE_URL" \
    -e AVELREN_TEST_DB=1 \
    test python -m avelren.migrate db/migrations

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
    test sh -c 'ruff check app/tests/test_db_privileges.py && python -m pytest app/tests/test_db_privileges.py -q -p no:cacheprovider'
