#!/usr/bin/env bash
# Real collector daemon and disposable DB; only HTTP transport is synthetic.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PROJECT="avelren-spool-test-${RANDOM}-${RANDOM}"
ROOT_FOR_COMPOSE=$ROOT
if command -v cygpath >/dev/null 2>&1; then ROOT_FOR_COMPOSE=$(cygpath -w "$ROOT"); fi
readonly ROOT PROJECT ROOT_FOR_COMPOSE
compose() {
    MSYS_NO_PATHCONV=1 docker compose -p "$PROJECT" -f "$ROOT_FOR_COMPOSE/ops/compose.collector-spool-test.yml" "$@"
}
cleanup() {
    local status=$?
    trap - EXIT
    if [ "$status" -ne 0 ]; then compose logs --tail 30 collector-test test-db || true; fi
    compose down --volumes --remove-orphans || status=1
    exit "$status"
}
trap cleanup EXIT
driver=/workspace/ops/collector-spool-daemon-test.py
admin_dsn=postgresql://avelren_admin:ci-only@test-db:5432/avelren_spool_test
compose build collector-test
compose up -d --wait test-db
compose exec -T \
    -e AVELREN_TEST_DB=1 -e AVELREN_DB_NAME=avelren_spool_test \
    -e AVELREN_ADMIN_DSN=postgresql://avelren_admin:ci-only@127.0.0.1:5432/postgres \
    -e AVELREN_ADMIN_PASSWORD=ci-only -e AVELREN_MIGRATOR_PASSWORD=ci-only \
    -e AVELREN_BACKUP_PASSWORD=ci-only -e AVELREN_COLLECTOR_PASSWORD=ci-only \
    -e AVELREN_NOTIFIER_PASSWORD=ci-only -e AVELREN_WATCHDOG_PASSWORD=ci-only \
    -e AVELREN_API_PASSWORD=ci-only \
    test-db bash /workspace/ops/postgres-bootstrap.sh fresh </dev/null
compose run --rm --no-deps -T \
    -e DATABASE_URL=postgresql://avelren_migrator:ci-only@test-db:5432/avelren_spool_test \
    collector-test python -m avelren.migrate /workspace/db/migrations </dev/null
compose run --rm --no-deps -T -e "DATABASE_URL=$admin_dsn" collector-test python "$driver" seed </dev/null
compose stop test-db
compose up -d collector-test
# Each process waits 60s before its first request, then 60s per further cycle.
# Budgets include 30s for container scheduling and spool completion.
compose exec -T collector-test python "$driver" wait-cycles 2 150
compose kill -s SIGKILL collector-test
# Preserve 60s between requests while restarting the disposable process.
compose run --rm --no-deps -T collector-test python "$driver" wait-next </dev/null
compose start collector-test
compose exec -T collector-test python "$driver" wait-cycles 5 210
compose exec -T collector-test python -m avelren.collector_control capture-only on
compose kill -s SIGKILL collector-test
compose run --rm --no-deps -T collector-test python "$driver" wait-next </dev/null
compose start collector-test
compose exec -T collector-test python "$driver" wait-cycles 6 90
compose exec -T collector-test python "$driver" wait-aged
compose up -d --wait test-db
compose exec -T -e "DATABASE_URL=$admin_dsn" collector-test python "$driver" paused
compose exec -T collector-test python "$driver" backup
compose exec -T collector-test python -m avelren.collector_control capture-only off
compose exec -T collector-test python "$driver" wait-empty
compose exec -T collector-test python -m avelren.collector_control capture-only on
compose exec -T -e "DATABASE_URL=$admin_dsn" collector-test python "$driver" verify
printf '%s\n' 'collector daemon outage/restart/capture-only/FIFO/recovery contract: PASS'
