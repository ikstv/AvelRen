#!/usr/bin/env bash
set -euo pipefail

SUITE=${1:-database}
case "$SUITE" in
    database|api) ;;
    *) echo 'Expected database or api' >&2; exit 2 ;;
esac

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PROJECT="avelren-db-test-${RANDOM}-${RANDOM}"
ENV_FILE=$(mktemp)
readonly ROOT PROJECT ENV_FILE

compose() {
    docker compose --env-file "$ENV_FILE" -p "$PROJECT" \
        -f "$ROOT/ops/compose.database-test.yml" "$@"
}

cleanup() {
    local status=$?
    trap - EXIT
    if [ "$status" -ne 0 ]; then compose logs --tail 60 test-db || true; fi
    compose down --volumes --remove-orphans || status=1
    rm -f -- "$ENV_FILE"
    exit "$status"
}
trap cleanup EXIT

# Образ будується до запуску контейнерів у мережі без зовнішнього доступу.
compose build test
compose up -d --wait test-db
compose exec -T \
    -e AVELREN_TEST_DB=1 -e AVELREN_DB_NAME=avelren_database_test \
    -e AVELREN_ADMIN_DSN=postgresql://avelren_admin:ci-only@127.0.0.1:5432/postgres \
    -e AVELREN_ADMIN_PASSWORD=ci-only -e AVELREN_MIGRATOR_PASSWORD=ci-only \
    -e AVELREN_BACKUP_PASSWORD=ci-only -e AVELREN_COLLECTOR_PASSWORD=ci-only \
    -e AVELREN_NOTIFIER_PASSWORD=ci-only -e AVELREN_WATCHDOG_PASSWORD=ci-only \
    -e AVELREN_API_PASSWORD=ci-only \
    test-db bash /workspace/ops/postgres-bootstrap.sh fresh </dev/null
compose run --rm --no-deps -T test python -m avelren.migrate db/migrations </dev/null
if [ "$SUITE" = api ]; then
    compose run --rm --no-deps -T test python -m pytest \
        -c services/backend/pytest.ini services/backend/tests/database/api \
        -q -p no:cacheprovider </dev/null
else
    compose run --rm --no-deps -T test python -m pytest \
        -c services/backend/pytest.ini services/backend/tests/database \
        --ignore=services/backend/tests/database/api -q -p no:cacheprovider </dev/null
fi
# Перевірка справжнього pg_dump під обмеженою backup-роллю; дані синтетичні.
compose exec -T -e PGPASSWORD=ci-only test-db \
    pg_dump -h 127.0.0.1 -U avelren_backup -d avelren_database_test \
    --no-owner --no-acl >/dev/null
